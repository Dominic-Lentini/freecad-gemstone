# SPDX-License-Identifier: LGPL-2.1-or-later
"""The RayTrace document object (final-polish rework of Lapidary_TraceRay).

A traced ray used to be a transient pivy overlay: invisible in the tree,
un-editable, cleared by re-invoking the command. It is now a real
document object living under its OpticsStudy — one object per traced
wavelength — whose Shape is the branch tree as B-Rep edges. That makes a
trace everything a document object is: visible and toggleable in the
tree, editable (move ``PickPoint`` or ``WavelengthNm`` in the property
editor and the trace recomputes), deletable, and saved with the file.

The geometry is the same headless branch tree as before
(:func:`~freecad.lapidary.optics.rays.ray_tree`): the incident approach,
every internal leg, and a short terminal twig per escaping branch.

Importable headless; the ViewProvider is attached only when a GUI is up.
"""

import FreeCAD

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.optics import materials as _materials
from freecad.lapidary.optics import rays as _rays
from freecad.lapidary.optics.polytope import PolytopeError, extract_polytope

__all__ = ["RAY_SCHEMA_VERSION", "RayTraceProxy", "make_ray_trace",
           "is_ray_trace", "ray_traces_of"]

RAY_SCHEMA_VERSION = 1


def is_ray_trace(obj):
    proxy = getattr(obj, "Proxy", None)
    return getattr(proxy, "Type", None) == "Lapidary::RayTrace"


def ray_traces_of(study):
    """Every RayTrace object belonging to ``study``, document order."""
    return [o for o in study.Document.Objects
            if is_ray_trace(o) and getattr(o, "Study", None) is study]


class RayTraceProxy:
    """Proxy for the RayTrace feature."""

    Type = "Lapidary::RayTrace"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Study"):
            obj.addProperty("App::PropertyLink", "Study", "Ray Trace",
                            "The optics study this trace belongs to "
                            "(supplies material, depth and energy limits)")
        if not hasattr(obj, "PickPoint"):
            obj.addProperty("App::PropertyVector", "PickPoint", "Ray Trace",
                            "Point the face-up primary ray passes through "
                            "(editing it re-traces)")
        if not hasattr(obj, "WavelengthNm"):
            obj.addProperty("App::PropertyFloat", "WavelengthNm",
                            "Ray Trace",
                            "Wavelength this trace refracts at (nm)")
            obj.WavelengthNm = _materials.WAVELENGTH_D
        if not hasattr(obj, "SchemaVersion"):
            obj.addProperty("App::PropertyInteger", "SchemaVersion",
                            "Ray Trace", "Property schema version")
            obj.SchemaVersion = RAY_SCHEMA_VERSION
            obj.setPropertyStatus("SchemaVersion", "Hidden")

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def execute(self, obj):
        """Re-trace: same physics as the batch tracer, one primary ray."""
        import Part

        from freecad.lapidary.optics.study_feature import study_material

        study = obj.Study
        gem = None if study is None else gem_feature.find_gem(study)
        if gem is None:
            obj.Shape = Part.Shape()
            return
        try:
            poly = extract_polytope(gem)
        except PolytopeError as err:
            FreeCAD.Console.PrintWarning(
                "Lapidary: %s cannot trace: %s\n" % (obj.Label, err))
            obj.Shape = Part.Shape()
            return
        n_gem = study_material(study).n(obj.WavelengthNm)
        segments = _rays.ray_tree(
            poly, n_gem, tuple(obj.PickPoint),
            max_depth=study.MaxDepth, min_energy=study.MinEnergy)
        edges = []
        for segment in segments:
            start = FreeCAD.Vector(*segment.start)
            end = FreeCAD.Vector(*segment.end)
            if (end - start).Length > 1e-9:
                edges.append(Part.makeLine(start, end))
        obj.Shape = Part.makeCompound(edges) if edges else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _attach_view_provider(obj):
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        from freecad.lapidary.optics.viewproviders import (
            ViewProviderRayTrace)
        ViewProviderRayTrace(obj.ViewObject)


def make_ray_trace(study, point, wavelength_nm=None):
    """Create a RayTrace under ``study`` through ``point`` and return it.

    The object is claimed by the study's ViewProvider in the tree; it is
    not part of the Gem's modeling pipeline.
    """
    doc = study.Document
    obj = doc.addObject("Part::FeaturePython", "RayTrace")
    RayTraceProxy(obj)
    obj.Study = study
    obj.PickPoint = FreeCAD.Vector(*point) if not hasattr(point, "x") \
        else FreeCAD.Vector(point)
    if wavelength_nm is not None:
        obj.WavelengthNm = float(wavelength_nm)
    obj.Label = "Ray %.0f nm" % obj.WavelengthNm
    _attach_view_provider(obj)
    return obj
