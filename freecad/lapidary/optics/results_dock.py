# SPDX-License-Identifier: LGPL-2.1-or-later
"""The optics results dock (DESIGN_OPTICS.md sections 8 and 9, Phase 4b).

Shows a study's stored results — headline numbers, the brightness and
window/leak classification maps, the tilt series and curve, and the
per-tier attribution table — straight from the document properties; the
dock never traces. A stale study shows its (old) results behind a clearly
visible warning banner.

GUI module, but constructable offscreen for the structural smoke tests
(same guard style as faceting/diagram_dock.py: behaviour, not imports).
"""

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from freecad.lapidary.optics import imaging, study_feature

__all__ = ["OpticsResultsDock", "show_results_dock"]

_DOCK_OBJECT_NAME = "LapidaryOpticsResultsDock"


def _map_pixmap(path, max_width=280):
    """A QPixmap from a stored map file, scaled for the dock, or None."""
    if not path:
        return None
    pixmap = QtGui.QPixmap(path)
    if pixmap.isNull():
        return None
    if pixmap.width() > max_width:
        pixmap = pixmap.scaledToWidth(
            max_width, QtCore.Qt.SmoothTransformation)
    return pixmap


class OpticsResultsDock(QtWidgets.QDockWidget):
    """Dock displaying one study's stored results."""

    def __init__(self, parent=None):
        super().__init__("Optics Results", parent)
        self.setObjectName(_DOCK_OBJECT_NAME)
        self._study = None
        self.setWidget(self._build_body())

    # -- construction ----------------------------------------------------

    def _build_body(self):
        body = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(body)

        top = QtWidgets.QHBoxLayout()
        self._title = QtWidgets.QLabel("No study")
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)
        top.addWidget(self._title)
        top.addStretch(1)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)

        self._stale_banner = QtWidgets.QLabel(
            "STALE — geometry or inputs changed since these results were "
            "computed. Run the study again.")
        self._stale_banner.setWordWrap(True)
        self._stale_banner.setStyleSheet(
            "background-color: #f5b7b1; color: #641e16; padding: 4px;")
        self._stale_banner.hide()
        layout.addWidget(self._stale_banner)

        scroll = QtWidgets.QScrollArea(body)
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget(scroll)
        self._inner_layout = QtWidgets.QVBoxLayout(inner)

        self._headline = QtWidgets.QLabel("")
        self._headline.setWordWrap(True)
        self._headline.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse)
        self._inner_layout.addWidget(self._headline)

        self._maps = {}
        for key, title in (("BrightnessMapFile", "Brightness"),
                           ("ClassificationMapFile",
                            "Window / leak classification"),
                           ("TiltMapsFile", "Tilt series"),
                           ("TiltCurveFile", "Brightness vs. tilt"),
                           ("SpreadMapFile", "Fire spread")):
            caption = QtWidgets.QLabel("<b>%s</b>" % title)
            image = QtWidgets.QLabel("")
            image.setAlignment(QtCore.Qt.AlignHCenter)
            self._inner_layout.addWidget(caption)
            self._inner_layout.addWidget(image)
            self._maps[key] = (caption, image)

        legend = ", ".join("%s: %s" % pair for pair in imaging.CLASS_LEGEND)
        legend_label = QtWidgets.QLabel("<i>%s</i>" % legend)
        legend_label.setWordWrap(True)
        self._inner_layout.addWidget(legend_label)

        self._tier_caption = QtWidgets.QLabel(
            "<b>Per-tier attribution</b> (by first pavilion interaction, "
            "% of incident energy)")
        self._tier_caption.setWordWrap(True)
        self._inner_layout.addWidget(self._tier_caption)
        self._tier_table = QtWidgets.QTableWidget(0, 3)
        self._tier_table.setHorizontalHeaderLabels(
            ["Tier", "Return %", "Leak %"])
        self._tier_table.horizontalHeader().setStretchLastSection(True)
        self._tier_table.verticalHeader().hide()
        self._tier_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self._inner_layout.addWidget(self._tier_table)
        self._inner_layout.addStretch(1)

        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        return body

    # -- state -----------------------------------------------------------

    def set_study(self, study):
        self._study = study
        self.refresh()

    def _target_study(self):
        study = self._study
        if study is not None:
            try:
                if study.Document is not None and not study.Removing:
                    return study
            except (ReferenceError, AttributeError):
                pass
            self._study = None
        return None

    def refresh(self):
        study = self._target_study()
        if study is None:
            self._title.setText("No study — run Lapidary_RunOptics first.")
            self._headline.setText("")
            self._stale_banner.hide()
            self._tier_table.setRowCount(0)
            for caption, image in self._maps.values():
                caption.hide()
                image.hide()
            return
        self._title.setText("%s (%s)" % (study.Label, study.Document.Name))
        self._stale_banner.setVisible(bool(study.Stale))
        headline = (
            "Light return %.1f %%   Leak %.1f %%   Pruned %.2f %%\n"
            "Mean path %.2f mm   Max path %.2f mm   Runtime %.2f s"
            % (study.LightReturnPct, study.LeakPct, study.PrunedPct,
               study.MeanPathLength, study.MaxPathLength, study.RuntimeS))
        if list(study.WavelengthsNm):
            headline += ("\nLapidary Fire Index %.3f deg over %d "
                         "wavelengths (definition in the study summary)"
                         % (study.FireIndex, len(study.WavelengthsNm)))
        self._headline.setText(headline)
        for key, (caption, image) in self._maps.items():
            pixmap = _map_pixmap(getattr(study, key, ""))
            visible = pixmap is not None
            caption.setVisible(visible)
            image.setVisible(visible)
            if visible:
                image.setPixmap(pixmap)
        names = list(study.TierNames)
        returns = list(study.TierReturnPct)
        leaks = list(study.TierLeakPct)
        self._tier_table.setRowCount(len(names))
        for row, (name, ret, leak) in enumerate(zip(names, returns, leaks)):
            for column, text in enumerate(
                    (name, "%.1f" % ret, "%.1f" % leak)):
                item = QtWidgets.QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self._tier_table.setItem(row, column, item)
        self._tier_table.resizeRowsToContents()


def _find_dock():
    window = Gui.getMainWindow()
    if window is None:
        return None
    return window.findChild(OpticsResultsDock, _DOCK_OBJECT_NAME)


def show_results_dock(study):
    """Open (or front) the results dock showing ``study``."""
    window = Gui.getMainWindow()
    dock = _find_dock()
    if dock is None:
        dock = OpticsResultsDock(window)
        if window is not None:
            window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.set_study(study)
    dock.show()
    dock.raise_()
    return dock
