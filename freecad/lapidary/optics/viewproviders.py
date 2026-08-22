# SPDX-License-Identifier: LGPL-2.1-or-later
"""ViewProvider for the OpticsStudy object.

GUI-only module (imported behind FreeCAD.GuiUp guards). The stale state is
shown by swapping the tree icon for the stale variant — the FEM-style
"results no longer match the mesh" cue of DESIGN_OPTICS.md section 7.
"""

import os

import FreeCADGui as Gui  # noqa: F401  (GUI-only module by contract)

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "resources", "icons")


def _icon(name):
    return os.path.join(ICON_DIR, name)


class ViewProviderOpticsStudy:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        obj = getattr(getattr(self, "vobj", None), "Object", None)
        if obj is not None and getattr(obj, "Stale", True):
            return _icon("Lapidary_OpticsStudyStale.svg")
        return _icon("Lapidary_OpticsStudy.svg")

    def updateData(self, obj, prop):
        if prop == "Stale":
            # Repaint the tree icon when the staleness flag flips.
            # signalChangeIcon exists on 1.1 view objects; fail soft if a
            # future version drops it (the icon then refreshes lazily).
            vobj = getattr(self, "vobj", None)
            signal = getattr(vobj, "signalChangeIcon", None)
            if signal is not None:
                signal()

    def onChanged(self, vobj, prop):
        pass

    def claimChildren(self):
        """Nest the study's RayTrace objects and its results sheet under
        it in the tree, so a trace can be toggled, edited or deleted like
        any child feature."""
        obj = getattr(getattr(self, "vobj", None), "Object", None)
        if obj is None:
            return []
        from freecad.lapidary.optics.ray_feature import ray_traces_of
        from freecad.lapidary.optics.study_feature import results_sheet_of
        children = list(ray_traces_of(obj))
        sheet = results_sheet_of(obj)
        if sheet is not None:
            children.append(sheet)
        return children

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        from freecad.lapidary.optics.commands import open_study_panel
        return open_study_panel(vobj.Object)

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        return bool(self.setEdit(vobj, 0))

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderRayTrace:
    """ViewProvider for a RayTrace object: wavelength-colored lines."""

    def __init__(self, vobj):
        vobj.Proxy = self
        try:
            from freecad.lapidary.optics.rays import wavelength_color
            vobj.LineColor = wavelength_color(vobj.Object.WavelengthNm)
            vobj.LineWidth = 3.0
            vobj.PointSize = 1.0
        except Exception:
            pass

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return _icon("Lapidary_TraceRay.svg")

    def updateData(self, obj, prop):
        if prop == "WavelengthNm":
            try:
                from freecad.lapidary.optics.rays import wavelength_color
                obj.ViewObject.LineColor = wavelength_color(
                    obj.WavelengthNm)
            except Exception:
                pass

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderResultsSheet:
    """ViewProvider for the results sheet: double-click opens the dock."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return _icon("Lapidary_OpticsResults.svg")

    def updateData(self, obj, prop):
        pass

    def onChanged(self, vobj, prop):
        pass

    def doubleClicked(self, vobj):
        study = getattr(vobj.Object, "Study", None)
        if study is not None:
            from freecad.lapidary.optics.results_dock import (
                show_results_dock)
            show_results_dock(study)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None
