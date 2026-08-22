# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lapidary_NewGem task panel (DESIGN.md section 4, item 1): stock habit,
dimensions, index gear, handedness. Creates Gem + Stock at the origin,
mass-centered, on OK.

The **Rough source** dropdown lists every document object carrying a
single solid (a Part primitive, a PartDesign Body, imported rough, ...);
choosing one makes the stock copy that solid, re-centered on its volume
centroid, instead of building a habit. A body selected in the 3D view
when the panel opens lands preselected, but any listed body can be
chosen after the fact."""

import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets

from freecad.lapidary.core import registry
from freecad.lapidary.core.gemmath import DEFAULT_HANDEDNESS
from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.faceting.stock_feature import make_stock


def _rough_candidates():
    """Every document object that could serve as custom rough: a
    non-Lapidary object carrying exactly one solid (a Part primitive, a
    PartDesign Body, imported rough, ...). Ordered with any currently
    selected candidate first so it lands preselected in the combo."""
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return []
    candidates = []
    for obj in doc.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", "").startswith(
                "Lapidary::"):
            continue
        shape = getattr(obj, "Shape", None)
        if shape is not None and not shape.isNull()                 and len(shape.Solids) == 1:
            candidates.append(obj)
    try:
        selected = set(Gui.Selection.getSelection())
    except Exception:
        selected = set()
    candidates.sort(key=lambda o: o not in selected)
    return candidates


def _is_selected(name):
    """True when the named object is in the current 3D selection."""
    try:
        return any(o.Name == name for o in Gui.Selection.getSelection())
    except Exception:
        return False


class NewGemPanel:
    """Task panel creating a Gem + Stock."""

    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("New Gem")
        layout = QtWidgets.QVBoxLayout(self.form)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit("Gem")
        form.addRow("Name", self.name_edit)

        # Rough source: a dropdown of every eligible body in the
        # document, choosable after the panel is open (it used to
        # require selecting the body before invoking New Gem).
        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.setToolTip(
            "Use a document object's solid as the starting rough, "
            "re-centered so its volume centroid sits at the origin (the "
            "source object itself is not modified) — or build a stock "
            "habit from the dimensions below.")
        self.source_combo.addItem("Stock habit (dimensions below)", None)
        for candidate in _rough_candidates():
            self.source_combo.addItem(
                "Body: %s" % candidate.Label, candidate.Name)
        if self.source_combo.count() > 1 and _rough_candidates() and                 _is_selected(self.source_combo.itemData(1)):
            self.source_combo.setCurrentIndex(1)
        self.source_combo.currentIndexChanged.connect(self._source_toggled)
        form.addRow("Rough source", self.source_combo)

        self.habit_combo = QtWidgets.QComboBox()
        for key in registry.habit_keys():
            self.habit_combo.addItem(registry.get_habit(key).label, key)
        form.addRow("Stock habit", self.habit_combo)

        self.gear_spin = QtWidgets.QSpinBox()
        self.gear_spin.setRange(1, 720)
        self.gear_spin.setValue(96)
        self.gear_spin.setToolTip("Index gear teeth count "
                                  "(common: 96, 80, 77, 72, 64, 120)")
        form.addRow("Index gear", self.gear_spin)

        self.handedness_combo = QtWidgets.QComboBox()
        for value in gem_feature.HANDEDNESS_VALUES:
            self.handedness_combo.addItem(value)
        # Default to the gemmath default (GemCad convention, dir = +1).
        self.handedness_combo.setCurrentIndex(
            0 if DEFAULT_HANDEDNESS == -1 else 1)
        form.addRow("Handedness", self.handedness_combo)

        self.dims_group = QtWidgets.QGroupBox("Dimensions (mm)")
        self.dims_form = QtWidgets.QFormLayout(self.dims_group)
        layout.addWidget(self.dims_group)
        layout.addStretch(1)

        self.dim_spins = {}
        self.habit_combo.currentIndexChanged.connect(self._rebuild_dims)
        self._rebuild_dims()
        self._source_toggled()

    def _source_object(self):
        """The chosen rough body, or None for a stock habit."""
        name = self.source_combo.currentData()
        if not name:
            return None
        doc = FreeCAD.ActiveDocument
        return None if doc is None else doc.getObject(name)

    def _source_toggled(self, *_args):
        enabled = self._source_object() is None
        self.habit_combo.setEnabled(enabled)
        self.dims_group.setEnabled(enabled)

    def _rebuild_dims(self):
        while self.dims_form.rowCount():
            self.dims_form.removeRow(0)
        self.dim_spins = {}
        key = self.habit_combo.currentData()
        for name, label, default in registry.get_habit(key).params:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0.01, 10000.0)
            spin.setDecimals(2)
            spin.setValue(default)
            spin.setSuffix(" mm")
            self.dims_form.addRow(label, spin)
            self.dim_spins[name] = spin

    def accept(self):
        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument()
        doc.openTransaction("New gem")
        try:
            gem = gem_feature.make_gem(
                doc,
                label=self.name_edit.text() or "Gem",
                index_gear=self.gear_spin.value(),
                handedness=-1 if self.handedness_combo.currentIndex() == 0
                else 1)
            dims = {name: spin.value()
                    for name, spin in self.dim_spins.items()}
            make_stock(gem, self.habit_combo.currentData(), dims,
                       source=self._source_object())
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        Gui.Control.closeDialog()
        Gui.SendMsgToActiveView("ViewFit")
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True
