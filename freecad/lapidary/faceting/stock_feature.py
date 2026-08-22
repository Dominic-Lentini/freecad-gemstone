# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Stock feature: starting solid of the pipeline (DESIGN.md sections 2-3).

A FeaturePython whose ``Habit`` enumeration selects a builder from the stock
habit registry. Dimension properties are created dynamically from the habit's
parameter schema (and removed when the habit changes), so the property editor
always shows exactly the dimensions that apply. The built solid is always
mass-centered at the document origin (the registry enforces this).

**Custom rough** (final-polish addition): the optional ``SourceObject`` link
overrides the habit — any document object carrying a single solid (a Part
primitive, a PartDesign Body, an imported STEP scan of real rough, ...)
becomes the stock. Its geometry is copied and *baked* re-centered so the
solid's volume centroid sits at the document origin (the same mass-centered
convention every habit follows; baked into the geometry, never via
Placement — see docs history for the placement-overwrite trap). The source
object itself is never modified.

Importable headless; the ViewProvider is only attached when a GUI is up.
"""

import FreeCAD

from freecad.lapidary.core import registry

__all__ = ["STOCK_SCHEMA_VERSION", "StockProxy", "make_stock"]

STOCK_SCHEMA_VERSION = 1

_DIMENSIONS_GROUP = "Dimensions"


class StockProxy:
    """Proxy for the Stock feature."""

    Type = "Lapidary::Stock"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Habit"):
            obj.addProperty("App::PropertyEnumeration", "Habit", "Stock",
                            "Rough stock habit (from the extensible registry)")
            obj.Habit = registry.habit_keys()
        if not hasattr(obj, "SourceObject"):
            obj.addProperty("App::PropertyLink", "SourceObject", "Stock",
                            "Use this object's solid as the rough instead "
                            "of a habit: its geometry is copied re-centered "
                            "so the volume centroid sits at the origin "
                            "(the source object is not modified)")
        if not hasattr(obj, "SchemaVersion"):
            obj.addProperty("App::PropertyInteger", "SchemaVersion", "Stock",
                            "Property schema version (for migration)")
            obj.SchemaVersion = STOCK_SCHEMA_VERSION
            obj.setPropertyStatus("SchemaVersion", "Hidden")
        self._sync_dimension_properties(obj)

    def _sync_dimension_properties(self, obj):
        """Make the dynamic dimension properties match the current habit."""
        habit = registry.get_habit(obj.Habit)
        wanted = {name: (label, default) for name, label, default in habit.params}
        for name in obj.PropertiesList:
            if (obj.getGroupOfProperty(name) == _DIMENSIONS_GROUP
                    and name not in wanted):
                obj.removeProperty(name)
        for name, label, default in habit.params:
            if not hasattr(obj, name):
                obj.addProperty("App::PropertyLength", name, _DIMENSIONS_GROUP,
                                label)
                setattr(obj, name, default)

    def onChanged(self, obj, prop):
        if prop == "Habit" and hasattr(obj, "Habit"):
            if not getattr(obj.Document, "Restoring", False):
                self._sync_dimension_properties(obj)

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def execute(self, obj):
        source = getattr(obj, "SourceObject", None)
        if source is not None:
            obj.Shape = _centered_source_solid(source)
            return
        habit = registry.get_habit(obj.Habit)
        dims = {name: getattr(obj, name).Value
                for name, _label, _default in habit.params}
        obj.Shape = habit.build(**dims)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _centered_source_solid(source):
    """The source object's solid, geometry-baked so its volume centroid is
    at the origin.

    The re-centering must be baked into the geometry (transformGeometry),
    never done via the shape's Placement: a shape assigned in execute()
    gets its placement overwritten by the feature's own Placement property
    afterwards, silently discarding any location-based positioning (the
    verified 1.1 trap that once put a stock at z 0..12 and made every
    pavilion cut miss). transformGeometry also does not compose the
    source's existing Placement, so that is applied explicitly first.
    """
    shape = getattr(source, "Shape", None)
    if shape is None or shape.isNull():
        raise RuntimeError(
            "%s has no shape to use as rough; pick a Part or Body with a "
            "solid" % source.Label)
    solids = shape.Solids
    if len(solids) != 1:
        raise RuntimeError(
            "%s carries %d solids; the rough must be exactly one solid"
            % (source.Label, len(solids)))
    solid = solids[0]
    # transformGeometry does NOT compose the shape's existing location, so
    # bake the placement first, then the centering shift (CenterOfMass is
    # reported location-applied, i.e. in global coordinates).
    shift = FreeCAD.Matrix()
    shift.move(solid.CenterOfMass.negative())
    matrix = shift.multiply(solid.Placement.toMatrix())
    moved = solid.transformGeometry(matrix)
    # transformGeometry returns a generic Part.Shape; unwrap the solid.
    return moved.Solids[0]


def _attach_view_provider(obj):
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        from freecad.lapidary.faceting.viewproviders import ViewProviderStock
        ViewProviderStock(obj.ViewObject)


def make_stock(gem, habit="Cylinder", dims=None, label="Stock", source=None):
    """Create the Stock feature inside ``gem`` (as the pipeline's first
    feature) and return it. ``dims`` maps dimension names to mm values;
    ``source`` (a document object with a single solid) overrides the habit
    and becomes the rough, re-centered on its volume centroid."""
    doc = gem.Document
    obj = doc.addObject("Part::FeaturePython", "Stock")
    StockProxy(obj)
    obj.Label = label
    obj.Habit = habit
    for name, value in (dims or {}).items():
        if not hasattr(obj, name):
            raise ValueError("habit %r has no dimension %r" % (habit, name))
        setattr(obj, name, float(value))
    if source is not None:
        obj.SourceObject = source
        if FreeCAD.GuiUp and getattr(source, "ViewObject", None) is not None:
            source.ViewObject.Visibility = False
    _attach_view_provider(obj)
    gem.addObject(obj)
    return obj
