# SPDX-License-Identifier: LGPL-2.1-or-later
"""Solo-view of pipeline features on tree selection.

Selecting a FacetTier (or the Stock) in the model tree shows that
feature alone — every other feature of the same gem's pipeline is
hidden — so clicking down the tree steps through the stone's cutting
history one stage at a time, PartDesign-tip style. Only whole-object
selections count: a 3D pick of a vertex/edge/face (the Auto flow, or
plain inspection) carries a subelement name and is ignored, as is any
selection made while a task panel is open (panels manage visibility
themselves).

GUI-only module: installed by the workbench on activation, removed on
deactivation.
"""

import FreeCAD
import FreeCADGui as Gui

from freecad.lapidary.faceting import gem_feature

_observer = None


class _SoloPipelineObserver:
    """Selection observer: show only the selected pipeline feature."""

    def addSelection(self, doc_name, obj_name, sub, _pos):
        if sub:                    # subelement pick in the 3D view
            return
        try:
            if Gui.Control.activeDialog():
                return
        except Exception:
            pass
        try:
            doc = FreeCAD.getDocument(doc_name)
            obj = doc.getObject(obj_name)
        except Exception:
            return
        if obj is None or not (gem_feature.is_tier(obj)
                               or gem_feature.is_stock(obj)):
            return
        gem = gem_feature.find_gem(obj)
        if gem is None:
            return
        for feature in gem_feature.pipeline_features(gem):
            if hasattr(feature, "Visibility"):
                visible = feature is obj
                if feature.Visibility != visible:
                    feature.Visibility = visible


def install():
    """Register the observer (idempotent)."""
    global _observer
    if _observer is None:
        _observer = _SoloPipelineObserver()
        Gui.Selection.addObserver(_observer)


def remove():
    """Unregister the observer (idempotent, fail-soft)."""
    global _observer
    if _observer is not None:
        try:
            Gui.Selection.removeObserver(_observer)
        except Exception:
            pass
        _observer = None
