# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI commands for the faceting module (DESIGN.md section 4).

All commands are implemented: Lapidary_NewGem, Lapidary_FacetTier,
Lapidary_CuttingSheet, Lapidary_Report (Phase 1), Lapidary_ImportASC /
Lapidary_ExportASC (Phase 2) and Lapidary_Diagram (Phase 3).
Lapidary_DopTransfer was removed after 0.1.0: the FacetTier panel's side
toggle flips the camera itself, which made the separate command redundant.

GUI-only module: imported from init_gui, never from headless code.
"""

import os

import FreeCAD
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.lapidary.faceting import gem_feature, reports

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "resources", "icons")


def _icon(name):
    return os.path.join(ICON_DIR, name)


def _main_window():
    return Gui.getMainWindow()


def find_target_gem(show_message=True):
    """The Gem to operate on: from the current selection, else the single Gem
    of the active document."""
    for obj in Gui.Selection.getSelection():
        if gem_feature.is_gem(obj):
            return obj
        gem = gem_feature.find_gem(obj)
        if gem is not None:
            return gem
    doc = FreeCAD.ActiveDocument
    if doc is not None:
        gems = [o for o in doc.Objects if gem_feature.is_gem(o)]
        if len(gems) == 1:
            return gems[0]
        if gems and show_message:
            FreeCAD.Console.PrintError(
                "Lapidary: multiple gems in the document — select one "
                "first.\n")
            return None
    if show_message:
        FreeCAD.Console.PrintError(
            "Lapidary: no Gem found; create one with Lapidary_NewGem "
            "first.\n")
    return None


class _GemCommand:
    """Base for commands that need an existing Gem."""

    def IsActive(self):
        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            gem_feature.is_gem(o) for o in doc.Objects)


class NewGemCommand:
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_NewGem.svg"),
                "MenuText": "New Gem",
                "ToolTip": "Create a new Gem: stock habit, dimensions, "
                           "index gear, handedness"}

    def IsActive(self):
        return True

    def Activated(self):
        from freecad.lapidary.faceting.taskpanels.newgem_panel import (
            NewGemPanel)
        if Gui.Control.activeDialog():
            return
        Gui.Control.showDialog(NewGemPanel())


class FacetTierCommand(_GemCommand):
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_FacetTier.svg"),
                "MenuText": "Facet Tier",
                "ToolTip": "Add a facet tier: working side, angle, distance "
                           "and index list (live preview)"}

    def Activated(self):
        gem = find_target_gem()
        if gem is None:
            return
        from freecad.lapidary.faceting.taskpanels.facettier_panel import (
            open_new_tier)
        open_new_tier(gem)


class DiagramCommand(_GemCommand):
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_Diagram.svg"),
                "MenuText": "Faceting Diagram",
                "ToolTip": "Show the printable 2D faceting diagram: crown, "
                           "pavilion and elevation views with the index ring, "
                           "tier table and stone data (SVG/PDF export)"}

    def Activated(self):
        from freecad.lapidary.faceting.diagram_dock import show_diagram_dock
        # A gem is optional: the dock falls back to the active document's
        # single gem and reports what it is waiting for.
        show_diagram_dock(find_target_gem(show_message=False))


class CuttingSheetDialog(QtWidgets.QDialog):
    """Collects the cutting sheet's options before the file dialog."""

    def __init__(self, gem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cutting Sheet")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Printable cutting instructions for %s." % gem.Label))
        self.report_check = QtWidgets.QCheckBox("Include the stone report")
        self.report_check.setChecked(True)
        layout.addWidget(self.report_check)
        self.diagram_check = QtWidgets.QCheckBox(
            "Include the 2D faceting diagram")
        self.diagram_check.setChecked(True)
        self.diagram_check.setToolTip(
            "Embeds the diagram in the sheet as inline SVG, so the file "
            "stays self-contained")
        layout.addWidget(self.diagram_check)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CuttingSheetCommand(_GemCommand):
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_CuttingSheet.svg"),
                "MenuText": "Cutting Sheet",
                "ToolTip": "Export ordered cutting instructions as a "
                           "printable HTML table, optionally with the "
                           "faceting diagram"}

    def Activated(self):
        gem = find_target_gem()
        if gem is None:
            return
        options = CuttingSheetDialog(gem, _main_window())
        if options.exec() != QtWidgets.QDialog.Accepted:
            return
        default = os.path.join(
            os.path.expanduser("~"),
            (gem.DesignName or gem.Label) + "_cutting_sheet.html")
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            _main_window(), "Export cutting sheet", default,
            "HTML files (*.html *.htm)")
        if not path:
            return
        report = (reports.gem_report(gem)
                  if options.report_check.isChecked() else None)
        html = reports.cutting_sheet_html(
            gem, report, include_diagram=options.diagram_check.isChecked())
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(html)
        FreeCAD.Console.PrintMessage(
            "Lapidary: cutting sheet written to %s\n" % path)
        QtCore.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


class ReportDialog(QtWidgets.QDialog):
    def __init__(self, gem, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stone Report - %s" % gem.Label)
        layout = QtWidgets.QVBoxLayout(self)
        view = QtWidgets.QPlainTextEdit(text)
        view.setReadOnly(True)
        font = view.font()
        font.setFamily("Consolas")
        font.setStyleHint(font.StyleHint.Monospace
                          if hasattr(font, "StyleHint") else font.Monospace)
        view.setFont(font)
        layout.addWidget(view)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(420, 320)


class ReportCommand(_GemCommand):
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_Report.svg"),
                "MenuText": "Stone Report",
                "ToolTip": "Stone measurements: L/W, depth %, crown/pavilion "
                           "%, table %, girdle thickness, facet count"}

    def Activated(self):
        gem = find_target_gem()
        if gem is None:
            return
        report = reports.gem_report(gem)
        if report is None:
            FreeCAD.Console.PrintWarning(
                "Lapidary: %s has no solid geometry to measure yet.\n"
                % gem.Label)
            return
        # The Gem's measurement properties are refreshed on every
        # recompute (gem_feature.update_measurements); this command is the
        # formatted sheet, not the only way to see the numbers.
        text = reports.report_text(report)
        # Phase 4b: append the optics section when a fresh study exists.
        optics_text = reports.optics_section_text(gem)
        if optics_text:
            text += "\n\n" + optics_text
        FreeCAD.Console.PrintMessage(
            "Lapidary report for %s:\n%s\n" % (gem.Label, text))
        ReportDialog(gem, text, _main_window()).exec()


class DopTransferCommand(_GemCommand):
    """Flip the whole stone through the girdle plane.

    Revived from the pre-0.1.0 Lapidary_DopTransfer with stronger
    semantics: the old command only set the *active side* for future
    tiers; this one mirrors the existing geometry — every tier's
    WorkingSide toggles (the exact n_z sign flip of the facet-plane
    math) with each plane's distance preserved. The rescue for "cut a
    pavilion tier set while Crown was selected": the stone is upside
    down, and this flips the z axis back.
    """

    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_DopTransfer.svg"),
                "MenuText": "Flip Stone (Dop Transfer)",
                "ToolTip": "Mirror the whole stone through the girdle "
                           "plane: every tier's working side flips "
                           "(crown\N{LEFT RIGHT ARROW}pavilion), each "
                           "facet plane kept at its exact distance"}

    def Activated(self):
        from freecad.lapidary.faceting.tier_feature import flip_gem

        gem = find_target_gem()
        if gem is None:
            return
        answer = QtWidgets.QMessageBox.question(
            _main_window(), "Flip Stone",
            "Mirror %s through the girdle plane?\n\n"
            "Every tier's working side flips (crown\N{LEFT RIGHT ARROW}"
            "pavilion) and the stone turns upside down. Run it again to "
            "flip back." % gem.Label,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes)
        if answer != QtWidgets.QMessageBox.Yes:
            return
        doc = gem.Document
        doc.openTransaction("Flip stone")
        try:
            count = flip_gem(gem)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        FreeCAD.Console.PrintMessage(
            "Lapidary: flipped %s through the girdle plane (%d tiers; "
            "active side is now %s).\n"
            % (gem.Label, count, gem.ActiveSide))


class ImportAscCommand:
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_ImportASC.svg"),
                "MenuText": "Import ASC",
                "ToolTip": "Import a GemCad .ASC design file"}

    def IsActive(self):
        return True

    def Activated(self):
        from freecad.lapidary.faceting.asc_io.document import design_to_gem
        from freecad.lapidary.faceting.asc_io.parser import (
            AscParseError, read_asc)

        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            _main_window(), "Import GemCad .ASC design", "",
            "GemCad ASC files (*.asc *.ASC);;All files (*)")
        if not path:
            return
        try:
            design = read_asc(path)
        except (AscParseError, OSError) as err:
            FreeCAD.Console.PrintError(
                "Lapidary: could not read %s: %s\n" % (path, err))
            return
        for warning in design.warnings:
            FreeCAD.Console.PrintWarning("ASC import: %s\n" % warning)

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument()
        doc.openTransaction("Import ASC design")
        try:
            gem = design_to_gem(
                doc, design,
                source_file=os.path.basename(path))
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        FreeCAD.Console.PrintMessage(
            "Lapidary: imported %s (%d tiers)\n"
            % (gem.Label, len(design.tiers)))
        Gui.SendMsgToActiveView("ViewFit")


class ExportAscCommand(_GemCommand):
    def GetResources(self):
        return {"Pixmap": _icon("Lapidary_ExportASC.svg"),
                "MenuText": "Export ASC",
                "ToolTip": "Export the current design as a GemCad .ASC file"}

    def Activated(self):
        from freecad.lapidary.faceting.asc_io.document import (
            AscExportError, gem_to_design)
        from freecad.lapidary.faceting.asc_io.writer import write_asc

        gem = find_target_gem()
        if gem is None:
            return
        default = os.path.join(os.path.expanduser("~"),
                               (gem.DesignName or gem.Label) + ".asc")
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            _main_window(), "Export GemCad .ASC design", default,
            "GemCad ASC files (*.asc)")
        if not path:
            return
        try:
            write_asc(gem_to_design(gem), path)
        except AscExportError as err:
            FreeCAD.Console.PrintError(
                "Lapidary: cannot export %s: %s\n" % (gem.Label, err))
            return
        FreeCAD.Console.PrintMessage(
            "Lapidary: exported %s to %s\n" % (gem.Label, path))


#: Implemented commands, keyed by command name (see init_gui).
COMMANDS = {
    "Lapidary_NewGem": NewGemCommand,
    "Lapidary_FacetTier": FacetTierCommand,
    "Lapidary_Diagram": DiagramCommand,
    "Lapidary_CuttingSheet": CuttingSheetCommand,
    "Lapidary_Report": ReportCommand,
    "Lapidary_DopTransfer": DopTransferCommand,
    "Lapidary_ImportASC": ImportAscCommand,
    "Lapidary_ExportASC": ExportAscCommand,
}
