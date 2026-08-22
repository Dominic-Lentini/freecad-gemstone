# SPDX-License-Identifier: LGPL-2.1-or-later
"""ViewProviders for the faceting features.

This module is ONLY imported from GUI code paths (guarded by FreeCAD.GuiUp in
the feature modules), so importing FreeCADGui here is safe. Nothing in the
modeling pipeline depends on it -- everything recomputes headless without it.
"""

import os

import FreeCAD
import FreeCADGui as Gui

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "resources", "icons")


def icon(name):
    return os.path.join(ICON_DIR, name)


class _ViewProviderBase:
    """Shared plumbing for Lapidary view providers."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def updateData(self, obj, prop):
        pass

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderStock(_ViewProviderBase):
    def getIcon(self):
        return icon("Lapidary_Stock.svg")


class ViewProviderFacetTier(_ViewProviderBase):
    def getIcon(self):
        # Warning marker in the tree for no-op cuts (DESIGN.md section 3);
        # FreeCAD adds its own error overlay for the recoverable-error state.
        obj = getattr(getattr(self, "vobj", None), "Object", None)
        state = getattr(obj, "TierState", "") if obj is not None else ""
        if state.startswith("Warning"):
            return icon("Lapidary_TierWarning.svg")
        return icon("Lapidary_FacetTier.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        from freecad.lapidary.faceting.taskpanels.facettier_panel import (
            open_tier_editor)
        return open_tier_editor(vobj.Object)

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        # Re-edit an existing tier via double-click (DESIGN.md section 4).
        return bool(self.setEdit(vobj, 0))
