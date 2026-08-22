# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI commands for the optics module (DESIGN_OPTICS.md section 9).

- ``Lapidary_OpticsStudy``: create a study under the active Gem and open
  the minimal input task panel (4a).
- ``Lapidary_RunOptics``: execute the selected (or only) study with a
  cancellable progress dialog; results are stored in the document and
  the results dock opens (4a/4b).
- ``Lapidary_OpticsResults``: reopen the results dock (4b).
- ``Lapidary_TraceRay``: pick a point on the stone and draw that primary
  ray's branch tree as energy-colored polylines; invoke again to clear
  (4b). Fails soft headless, like the Phase 1 azimuth marker.

GUI-only module: imported from init_gui, never from headless code.
"""

import os

import FreeCAD
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.faceting.commands import find_target_gem
from freecad.lapidary.optics import materials as _materials
from freecad.lapidary.optics import study_feature
from freecad.lapidary.optics.polytope import PolytopeError, extract_polytope
from freecad.lapidary.optics.tracer import TraceCancelled

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "resources", "icons")


def _icon(name):
    return os.path.join(ICON_DIR, name)


def find_target_study(show_message=True):
    """The study to run: from the selection, else the single study of the
    single Gem of the active document."""
    for obj in Gui.Selection.getSelection():
        if study_feature.is_study(obj):
            return obj
        if gem_feature.is_gem(obj):
            studies = study_feature.find_studies(obj)
            if len(studies) == 1:
                return studies[0]
    gem = find_target_gem(show_message=False)
    if gem is not None:
        studies = study_feature.find_studies(gem)
        if len(studies) == 1:
            return studies[0]
        if len(studies) > 1 and show_message:
            FreeCAD.Console.PrintError(
                "Lapidary: %s has several optics studies — select the one "
                "to run.\n" % gem.Label)
            return None
    if show_message:
        FreeCAD.Console.PrintError(
            "Lapidary: no optics study found; create one with "
            "Lapidary_OpticsStudy first.\n")
    return None


class StudyPanel:
    """Minimal task panel for the study's input properties."""

    def __init__(self, study, created=False):
        self.study = study
        self.created = created
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Optics Study")
        layout = QtWidgets.QFormLayout(self.form)

        self.material = QtWidgets.QComboBox()
        self.material.addItems([study_feature.CUSTOM_MATERIAL]
                               + _materials.preset_names())
        self.material.setCurrentText(study.MaterialPreset)
        self.material.setToolTip(
            "Sets the optical constants below and the 3D-view tint. The "
            "tint is cosmetic only — it carries no optical information.")
        layout.addRow("Material", self.material)

        cosmetic_note = QtWidgets.QLabel(
            "<i>The material's viewport tint is cosmetic only; results "
            "come from the ray trace, never from the 3D view.</i>")
        cosmetic_note.setWordWrap(True)
        layout.addRow(cosmetic_note)

        self.ri = QtWidgets.QDoubleSpinBox()
        self.ri.setRange(1.001, 4.0)
        self.ri.setDecimals(3)
        self.ri.setSingleStep(0.01)
        self.ri.setValue(study.RefractiveIndex)
        layout.addRow("Refractive index n_d", self.ri)

        self.dispersion = QtWidgets.QDoubleSpinBox()
        self.dispersion.setRange(0.0, 0.5)
        self.dispersion.setDecimals(3)
        self.dispersion.setSingleStep(0.001)
        self.dispersion.setValue(study.Dispersion)
        layout.addRow("Dispersion (B\u2013G)", self.dispersion)

        self.lighting = QtWidgets.QComboBox()
        self.lighting.addItems(study_feature.LIGHTING_MODELS)
        self.lighting.setCurrentText(study.LightingModel)
        layout.addRow("Lighting", self.lighting)

        self.head = QtWidgets.QDoubleSpinBox()
        self.head.setRange(0.0, 90.0)
        self.head.setSuffix(" deg")
        self.head.setValue(study.HeadShadowDeg)
        self.head.setToolTip("Observer head-shadow cone half-angle; 0 = off")
        layout.addRow("Head shadow", self.head)

        self.resolution = QtWidgets.QSpinBox()
        self.resolution.setRange(16, 2048)
        self.resolution.setValue(study.GridResolution)
        self.resolution.setToolTip(
            "View grid resolution per axis — the speed/quality dial")
        layout.addRow("Grid resolution", self.resolution)

        self.tilt_max = QtWidgets.QDoubleSpinBox()
        self.tilt_max.setRange(0.0, 90.0)
        self.tilt_max.setSuffix(" deg")
        self.tilt_max.setValue(study.TiltMaxDeg)
        layout.addRow("Tilt curve max", self.tilt_max)

        self.tilt_steps = QtWidgets.QSpinBox()
        self.tilt_steps.setRange(0, 33)
        self.tilt_steps.setValue(study.TiltSteps)
        layout.addRow("Tilt curve steps", self.tilt_steps)

        self.wavelengths = QtWidgets.QComboBox()
        self.wavelengths.addItems(study_feature.WAVELENGTH_CHOICES)
        self.wavelengths.setCurrentText(study.Wavelengths)
        self.wavelengths.setToolTip(
            "1 = brightness only (d line). 3 or 5 wavelength samples add "
            "the Lapidary Fire Index and the fire spread map (slower).")
        layout.addRow("Wavelengths", self.wavelengths)

        self.absorption = QtWidgets.QDoubleSpinBox()
        self.absorption.setRange(0.0, 10.0)
        self.absorption.setDecimals(4)
        self.absorption.setSingleStep(0.005)
        self.absorption.setSuffix(" /mm")
        self.absorption.setValue(study.AbsorptionPerMM)
        self.absorption.setToolTip(
            "APPROXIMATE single-coefficient Beer-Lambert body color, "
            "applied per escaping branch over its internal path length. "
            "0 = off (the default).")
        layout.addRow("Absorption", self.absorption)

        self.material.currentTextChanged.connect(self._preset_changed)
        self._preset_changed(self.material.currentText())

    def _preset_changed(self, name):
        preset = _materials.PRESETS.get(name)
        custom = preset is None
        self.ri.setEnabled(custom)
        self.dispersion.setEnabled(custom)
        if preset is not None:
            self.ri.setValue(preset.n_d)
            self.dispersion.setValue(preset.dispersion)

    def accept(self):
        study = self.study
        study.MaterialPreset = self.material.currentText()
        study.RefractiveIndex = self.ri.value()
        study.Dispersion = self.dispersion.value()
        study.LightingModel = self.lighting.currentText()
        study.HeadShadowDeg = self.head.value()
        study.GridResolution = self.resolution.value()
        study.TiltMaxDeg = self.tilt_max.value()
        study.TiltSteps = self.tilt_steps.value()
        study.Wavelengths = self.wavelengths.currentText()
        study.AbsorptionPerMM = self.absorption.value()
        study.Document.recompute()
        Gui.Control.closeDialog()
        FreeCAD.Console.PrintMessage(
            "Lapidary: %s configured; run it with Lapidary_RunOptics.\n"
            % study.Label)
        return True

    def reject(self):
        if self.created:
            # Cancelling the creation panel removes the fresh study.
            doc = self.study.Document
            doc.removeObject(self.study.Name)
        Gui.Control.closeDialog()
        return True


def open_study_panel(study, created=False):
    if Gui.Control.activeDialog():
        return False
    Gui.Control.showDialog(StudyPanel(study, created=created))
    return True


class OpticsStudyCommand:
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_OpticsStudy.svg"),
                "MenuText": "Optics Study",
                "ToolTip": "Create a ray-trace study of the finished stone: "
                           "material, lighting and tracing parameters"}

    def IsActive(self):
        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            gem_feature.is_gem(o) for o in doc.Objects)

    def Activated(self):
        gem = find_target_gem()
        if gem is None:
            return
        doc = gem.Document
        doc.openTransaction("Optics study")
        try:
            study = study_feature.make_study(gem)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        open_study_panel(study, created=True)


class RunOpticsCommand:
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_RunOptics.svg"),
                "MenuText": "Run Optics Study",
                "ToolTip": "Trace the stone and store light return, "
                           "leakage, per-tier and tilt results"}

    def IsActive(self):
        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            study_feature.is_study(o) for o in doc.Objects)

    def Activated(self):
        study = find_target_study()
        if study is None:
            return
        dialog = QtWidgets.QProgressDialog(
            "Tracing %s..." % study.Label, "Cancel", 0, 1000,
            Gui.getMainWindow())
        dialog.setWindowModality(QtCore.Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        def progress(fraction):
            dialog.setValue(int(fraction * 1000))
            QtWidgets.QApplication.processEvents()
            return not dialog.wasCanceled()

        try:
            study_feature.run_study(study, progress=progress)
        except TraceCancelled:
            FreeCAD.Console.PrintWarning(
                "Lapidary: %s cancelled; stored results unchanged.\n"
                % study.Label)
            return
        except PolytopeError as err:
            FreeCAD.Console.PrintError("Lapidary: %s\n" % err)
            return
        finally:
            dialog.close()
        FreeCAD.Console.PrintMessage(
            "Lapidary optics results for %s:\n%s\n"
            % (study.Label, study.ResultSummary))
        from freecad.lapidary.optics.results_dock import show_results_dock
        show_results_dock(study)


class OpticsResultsCommand:
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_OpticsResults.svg"),
                "MenuText": "Optics Results",
                "ToolTip": "Show the optics results dock: maps, headline "
                           "numbers and the per-tier table of the stored "
                           "study"}

    def IsActive(self):
        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            study_feature.is_study(o) for o in doc.Objects)

    def Activated(self):
        study = find_target_study()
        if study is None:
            return
        from freecad.lapidary.optics.results_dock import show_results_dock
        show_results_dock(study)


# ---------------------------------------------------------------------------
# Lapidary_TraceRay: traces become document objects under the study
# ---------------------------------------------------------------------------

class _RayPickObserver:
    """One-shot selection observer: reports the first picked 3D point."""

    def __init__(self, callback):
        self.callback = callback

    def addSelection(self, doc, obj_name, sub, pos):
        self.callback(doc, obj_name, sub, pos)


class TraceRayCommand:
    """Trace the face-up primary ray through a picked point.

    Each invocation creates real ``RayTrace`` document objects — one per
    wavelength sample of the study — nested under the study in the tree,
    where they can be toggled, edited (move PickPoint / WavelengthNm in
    the property editor) or deleted like any feature. No more transient
    overlay to clear.
    """

    def __init__(self):
        self._observer = None
        self._study = None

    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_TraceRay.svg"),
                "MenuText": "Trace Ray",
                "ToolTip": "Pick a point on the stone; the face-up "
                           "primary ray through it is traced into "
                           "RayTrace objects under the optics study "
                           "(one per wavelength sample), editable and "
                           "deletable in the tree"}

    def IsActive(self):
        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            study_feature.is_study(o) for o in doc.Objects)

    def Activated(self):
        if self._observer is not None:
            self._disarm()
            FreeCAD.Console.PrintMessage(
                "Lapidary: ray pick cancelled.\n")
            return
        study = find_target_study()
        if study is None:
            return
        self._study = study
        self._observer = _RayPickObserver(self._picked)
        Gui.Selection.addObserver(self._observer)
        FreeCAD.Console.PrintMessage(
            "Lapidary: click a point on the stone to trace its face-up "
            "ray into %s (run Trace Ray again to cancel).\n" % study.Label)

    def _disarm(self):
        if self._observer is not None:
            try:
                Gui.Selection.removeObserver(self._observer)
            except Exception:
                pass
            self._observer = None

    def _picked(self, _doc, _obj_name, _sub, pos):
        self._disarm()
        study = self._study
        from freecad.lapidary.optics import materials as mats
        from freecad.lapidary.optics.fire import wavelength_samples
        from freecad.lapidary.optics.ray_feature import make_ray_trace

        if study.Wavelengths == "1":
            samples = (mats.WAVELENGTH_D,)
        else:
            samples = wavelength_samples(int(study.Wavelengths))
        doc = study.Document
        doc.openTransaction("Trace ray")
        try:
            created = [make_ray_trace(study, pos, wavelength)
                       for wavelength in samples]
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass
        FreeCAD.Console.PrintMessage(
            "Lapidary: created %d RayTrace object%s under %s — edit or "
            "delete them in the tree.\n"
            % (len(created), "" if len(created) == 1 else "s",
               study.Label))



class ExportRenderMaterialCommand:
    """DESIGN_OPTICS.md §6.1 (Phase 4c): write a Render-workbench material
    card carrying the tracer's own constants — including the LuxCore
    Cauchy-B coefficient, NOT the gemological dispersion figure (see
    optics/render_export.py for the unit trap)."""

    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_ExportRenderMaterial.svg"),
                "MenuText": "Export Render Material",
                "ToolTip": "Write a FreeCAD Material card (.FCMat) with "
                           "correct glass parameters for the external "
                           "Render workbench (metadata only; renders are "
                           "artistic output, not optical analysis)"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from freecad.lapidary.optics.render_export import (
            default_card_name, write_material_card)

        # Prefill from the target gem's single study, if any.
        preset_name = "Quartz"
        gem = find_target_gem(show_message=False)
        if gem is not None:
            studies = study_feature.find_studies(gem)
            if len(studies) == 1:
                preset_name = studies[0].MaterialPreset

        names = _materials.preset_names()
        current = names.index(preset_name) if preset_name in names else 0
        name, ok = QtWidgets.QInputDialog.getItem(
            Gui.getMainWindow(), "Export Render Material",
            "Gem material (optical constants from the Lapidary presets):",
            names, current, False)
        if not ok:
            return
        material = _materials.PRESETS[name]
        default = os.path.join(os.path.expanduser("~"),
                               default_card_name(material) + ".FCMat")
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            Gui.getMainWindow(), "Export Render material card", default,
            "FreeCAD material cards (*.FCMat)")
        if not path:
            return
        write_material_card(material, path)
        FreeCAD.Console.PrintMessage(
            "Lapidary: Render material card for %s written to %s "
            "(LuxCore cauchyb = Cauchy-B %.4g um^2, not the gemological "
            "%.3g).\n" % (material.name, path, material.cauchy_b_um2(),
                          material.dispersion))


COMMANDS = {
    "Lapidary_OpticsStudy": OpticsStudyCommand,
    "Lapidary_RunOptics": RunOpticsCommand,
    "Lapidary_OpticsResults": OpticsResultsCommand,
    "Lapidary_TraceRay": TraceRayCommand,
    "Lapidary_ExportRenderMaterial": ExportRenderMaterialCommand,
}
