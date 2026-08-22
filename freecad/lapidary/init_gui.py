# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lapidary workbench registration: workbench class, toolbars, menus.

Loaded by FreeCAD's GUI startup for every ``freecad.*`` namespace package that
provides an ``init_gui`` module. Never imported headless, so importing
FreeCADGui here is safe.
"""

import os

import FreeCADGui as Gui

from freecad.lapidary.version import __version__

ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")

# (command name, menu text, tooltip, icon file), in toolbar/menu order.
# Every one of these is implemented in faceting.commands; the placeholder
# fallback below only exists so a future phase can list a command here before
# it is written without breaking workbench activation.
FACETING_COMMANDS = [
    ("Lapidary_NewGem", "New Gem",
     "Create a new Gem with stock habit, dimensions, index gear and handedness",
     "Lapidary_NewGem.svg"),
    ("Lapidary_FacetTier", "Facet Tier",
     "Add a facet tier: working side, angle, distance and index list",
     "Lapidary_FacetTier.svg"),
    ("Lapidary_ImportASC", "Import ASC",
     "Import a GemCad .ASC design file",
     "Lapidary_ImportASC.svg"),
    ("Lapidary_ExportASC", "Export ASC",
     "Export the current design as a GemCad .ASC file",
     "Lapidary_ExportASC.svg"),
    ("Lapidary_Diagram", "Faceting Diagram",
     "Show the live 2D faceting diagram; export it as SVG or PDF",
     "Lapidary_Diagram.svg"),
    ("Lapidary_CuttingSheet", "Cutting Sheet",
     "Export ordered cutting instructions as a printable table",
     "Lapidary_CuttingSheet.svg"),
    ("Lapidary_Report", "Stone Report",
     "Report stone measurements: L/W, depth %, table %, facet count",
     "Lapidary_Report.svg"),
    ("Lapidary_DopTransfer", "Flip Stone (Dop Transfer)",
     "Mirror the whole stone through the girdle plane: every tier's "
     "working side flips, fixing an upside-down stone",
     "Lapidary_DopTransfer.svg"),
]

# --- Optics (Phase 4a) ---
# Registered separately from FACETING_COMMANDS so the Phase 3/4 merge in
# this file stays trivial. (command name, menu text, tooltip, icon file).
OPTICS_COMMANDS = [
    ("Lapidary_OpticsStudy", "Optics Study",
     "Create a ray-trace study of the finished stone",
     "Lapidary_OpticsStudy.svg"),
    ("Lapidary_RunOptics", "Run Optics Study",
     "Trace the stone: light return, leakage, per-tier and tilt results",
     "Lapidary_RunOptics.svg"),
    ("Lapidary_OpticsResults", "Optics Results",
     "Show the optics results dock: maps, numbers, per-tier table",
     "Lapidary_OpticsResults.svg"),
    ("Lapidary_TraceRay", "Trace Ray",
     "Pick a point on the stone and draw its ray's branch tree",
     "Lapidary_TraceRay.svg"),
    ("Lapidary_ExportRenderMaterial", "Export Render Material",
     "Write a Render-workbench material card with correct glass optics",
     "Lapidary_ExportRenderMaterial.svg"),
]
# --- end Optics (Phase 4a) ---


class PlaceholderCommand:
    """Stand-in command for not-yet-implemented phases: shows a dialog."""

    def __init__(self, name, menu_text, tooltip, icon_file):
        self.name = name
        self.menu_text = menu_text
        self.tooltip = tooltip
        self.icon = os.path.join(ICON_DIR, icon_file)

    def GetResources(self):
        return {
            "Pixmap": self.icon,
            "MenuText": self.menu_text,
            "ToolTip": self.tooltip + " (not yet implemented)",
        }

    def IsActive(self):
        return True

    def Activated(self):
        import FreeCAD

        FreeCAD.Console.PrintWarning(
            "Lapidary: {} ({}) is not yet implemented; see CHANGELOG.md "
            "for what this release ships.\n".format(self.menu_text, self.name))


class LapidaryWorkbench(Gui.Workbench):
    """Lapidary: parametric faceted-gemstone design."""

    MenuText = "Lapidary"
    ToolTip = "Design faceted gemstones: facet tiers, GemCad .ASC interchange, diagrams"
    Icon = os.path.join(ICON_DIR, "Lapidary_Workbench.svg")

    def Initialize(self):
        """Called once, when the workbench is first activated."""
        from freecad.lapidary.faceting.commands import COMMANDS

        command_names = []
        for name, menu_text, tooltip, icon_file in FACETING_COMMANDS:
            command_class = COMMANDS.get(name)
            if command_class is not None:
                Gui.addCommand(name, command_class())
            else:
                Gui.addCommand(name, PlaceholderCommand(
                    name, menu_text, tooltip, icon_file))
            command_names.append(name)
        self.appendToolbar("Faceting", command_names)
        self.appendMenu("Faceting", command_names)

        # --- Optics (Phase 4a) ---
        from freecad.lapidary.optics.commands import COMMANDS as OPTICS
        optics_names = []
        for name, menu_text, tooltip, icon_file in OPTICS_COMMANDS:
            command_class = OPTICS.get(name)
            if command_class is not None:
                Gui.addCommand(name, command_class())
            else:
                Gui.addCommand(name, PlaceholderCommand(
                    name, menu_text, tooltip, icon_file))
            optics_names.append(name)
        self.appendToolbar("Optics", optics_names)
        self.appendMenu("Optics", optics_names)
        # --- end Optics (Phase 4a) ---

    def Activated(self):
        from freecad.lapidary.faceting import tree_visibility
        tree_visibility.install()

    def Deactivated(self):
        from freecad.lapidary.faceting import tree_visibility
        tree_visibility.remove()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(LapidaryWorkbench())
