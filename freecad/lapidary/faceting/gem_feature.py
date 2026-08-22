# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Gem container object (DESIGN.md section 3).

A Gem is an ``App::DocumentObjectGroupPython`` holding an ordered pipeline::

    Gem
     |- Stock            (FeaturePython: habit type + dimensions, mass-centered)
     |- FacetTier 001    (FeaturePython)
     |- FacetTier 002
     `- ...              (ordered; each consumes the previous solid -- "tip"
                          semantics like PartDesign)

The order of ``Gem.Group`` is the single source of truth for pipeline order.
Whenever the group changes (tier added, deleted, or drag-reordered in the
tree), :func:`resequence` rewires every tier's hidden ``BaseFeature`` link to
its predecessor. Because ``BaseFeature`` is a real App::PropertyLink, the
dependency graph gives correct recompute ordering and touch propagation
(editing any tier recomputes it and everything downstream) for free.

This module is importable headless (FreeCADCmd); it never imports GUI
modules. The Gem keeps FreeCAD's default group ViewProvider so tree
drag-and-drop reordering works with stock behavior.
"""

import FreeCAD

from freecad.lapidary.core.gemmath import DEFAULT_HANDEDNESS

__all__ = [
    "GEM_SCHEMA_VERSION",
    "GemProxy",
    "make_gem",
    "is_gem",
    "is_stock",
    "is_tier",
    "find_gem",
    "pipeline_features",
    "tip_feature",
    "final_shape",
    "resequence",
    "gem_handedness",
    "update_measurements",
]

GEM_SCHEMA_VERSION = 1

#: Handedness enumeration values -> the ``dir`` flag of DESIGN.md section 2.1.
#: "Counterclockwise" (viewed from the crown) is dir = +1, the GemCad default
#: as resolved in Phase 2 (asc_io/FORMAT_NOTES.md); a negative .ASC gear
#: means "Clockwise" (dir = -1).
HANDEDNESS_VALUES = ["Clockwise", "Counterclockwise"]
_HANDEDNESS_TO_DIR = {"Clockwise": -1, "Counterclockwise": +1}

DISPLAY_UNITS = ["mm", "cm", "in"]

SIDES = ["Crown", "Pavilion"]


def _proxy_type(obj):
    proxy = getattr(obj, "Proxy", None)
    return getattr(proxy, "Type", None)


def is_gem(obj):
    return _proxy_type(obj) == "Lapidary::Gem"


def is_stock(obj):
    return _proxy_type(obj) == "Lapidary::Stock"


def is_tier(obj):
    return _proxy_type(obj) == "Lapidary::FacetTier"


def find_gem(obj):
    """The Gem group containing ``obj``, or None."""
    getter = getattr(obj, "getParentGroup", None)
    parent = getter() if getter is not None else None
    if parent is not None and is_gem(parent):
        return parent
    # Fallback: scan the in-list (covers documents where getParentGroup is
    # unavailable or the group extension resolves differently).
    for candidate in obj.InList:
        if is_gem(candidate) and obj in candidate.Group:
            return candidate
    return None


def pipeline_features(gem):
    """The ordered modeling pipeline: the Stock (if any) followed by every
    FacetTier, in Group order."""
    stock = [o for o in gem.Group if is_stock(o)]
    tiers = [o for o in gem.Group if is_tier(o)]
    return stock[:1] + tiers


def tip_feature(gem):
    """The last feature of the pipeline (the gem's current result), or None."""
    features = pipeline_features(gem)
    return features[-1] if features else None


def final_shape(gem):
    """The finished B-Rep of the gem (the tip feature's shape), or None."""
    tip = tip_feature(gem)
    if tip is None:
        return None
    shape = tip.Shape
    return None if shape.isNull() else shape


def gem_handedness(gem):
    """The ``dir`` handedness flag (+-1) for a Gem (DESIGN.md section 2.1)."""
    if gem is None:
        return DEFAULT_HANDEDNESS
    return _HANDEDNESS_TO_DIR.get(getattr(gem, "Handedness", None),
                                  DEFAULT_HANDEDNESS)


def resequence(gem, sync_visibility=True):
    """Rewire every tier's BaseFeature to its predecessor in Group order.

    Assigning a changed link touches the tier, so the next document recompute
    rebuilds exactly the affected tail of the pipeline.

    With ``sync_visibility`` (the default) the standard tip semantics are
    also restored: only the pipeline tip is shown — for live Group changes
    (tier added, deleted, drag-reordered) *and* on document restore, the
    same way a PartDesign Body loads with only its tip visible. (Restore
    used to preserve saved visibility, which left every intermediate step
    shown when a document had been saved that way.)
    """
    features = pipeline_features(gem)
    previous = None
    for feature in features:
        if is_tier(feature):
            if feature.BaseFeature is not previous:
                feature.BaseFeature = previous
        previous = feature
    if sync_visibility and features:
        tip = features[-1]
        for feature in features:
            if hasattr(feature, "Visibility"):
                visible = feature is tip
                if feature.Visibility != visible:
                    feature.Visibility = visible


#: Gem measurement property <- reports.compute_report key.
MEASUREMENT_KEYS = {
    "LengthWidthRatio": "lw_ratio",
    "WidthMM": "width",
    "LengthMM": "length",
    "TotalDepthPct": "depth_pct",
    "CrownHeightPct": "crown_pct",
    "PavilionDepthPct": "pavilion_pct",
    "GirdleThicknessPct": "girdle_pct",
    "TablePct": "table_pct",
    "GirdleTopMM": "girdle_top",
    "GirdleBottomMM": "girdle_bottom",
    "VolumeMM3": "volume",
    "FacetCount": "facet_count",
}


def update_measurements(gem):
    """Refresh the Gem's measurement properties from its finished B-Rep.

    Called from the Gem's execute, so the figures a designer cuts against
    (girdle thickness, crown height, pavilion depth, table %) are always
    current in the tree instead of waiting behind Lapidary_Report. The
    hidden TipFeature link makes the Gem depend on the pipeline tip, so
    the document recomputes the tip *before* this runs.

    Metrics a stone does not have yet (no girdle band, no table) read 0.
    Never raises: a measurement failure must not block a recompute.
    """
    from freecad.lapidary.faceting import reports

    tip = tip_feature(gem)
    if tip is not None and getattr(gem, "TipFeature", None) is not tip:
        gem.TipFeature = tip
    try:
        report = reports.gem_report(gem)
    except Exception:
        report = None
    for name, key in MEASUREMENT_KEYS.items():
        if not hasattr(gem, name):
            continue
        value = None if report is None else report.get(key)
        if name == "FacetCount":
            wanted = int(value or 0)
        else:
            wanted = float(value or 0.0)
        if getattr(gem, name) != wanted:
            setattr(gem, name, wanted)


class GemProxy:
    """Proxy for the Gem group object."""

    Type = "Lapidary::Gem"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "IndexGear"):
            obj.addProperty("App::PropertyInteger", "IndexGear", "Gem",
                            "Index gear teeth count, inherited by tiers "
                            "(tiers may override)")
            obj.IndexGear = 96
        if not hasattr(obj, "Handedness"):
            obj.addProperty("App::PropertyEnumeration", "Handedness", "Gem",
                            "Direction in which index numbers increase, "
                            "viewed from the crown (+Z)")
            obj.Handedness = HANDEDNESS_VALUES
            obj.Handedness = HANDEDNESS_VALUES[
                0 if DEFAULT_HANDEDNESS == -1 else 1]
        if not hasattr(obj, "ActiveSide"):
            obj.addProperty("App::PropertyEnumeration", "ActiveSide", "Gem",
                            "Default working side for newly created tiers "
                            "(follows the side of the last committed tier)")
            obj.ActiveSide = SIDES
            obj.ActiveSide = "Pavilion"
        # -- Measurements: filled automatically on every recompute -------
        # Cheap enough to keep current (a bounding box, a face scan), and
        # far more useful live in the tree than behind a button: these are
        # the numbers a designer cuts against - girdle thickness, crown
        # height, pavilion depth. Lapidary_Report still prints the full
        # formatted sheet.
        for name, group, doc in (
                ("LengthWidthRatio", "Measurements",
                 "L/W ratio of the finished stone"),
                ("WidthMM", "Measurements", "Girdle width W (mm)"),
                ("LengthMM", "Measurements", "Girdle length L (mm)"),
                ("TotalDepthPct", "Measurements",
                 "Total depth as a percentage of the width"),
                ("CrownHeightPct", "Measurements",
                 "Crown height above the girdle, % of the width"),
                ("PavilionDepthPct", "Measurements",
                 "Pavilion depth below the girdle, % of the width"),
                ("GirdleThicknessPct", "Measurements",
                 "Girdle band thickness, % of the width"),
                ("TablePct", "Measurements",
                 "Table width as a percentage of the width"),
                ("GirdleTopMM", "Measurements",
                 "Top of the girdle band (z, mm)"),
                ("GirdleBottomMM", "Measurements",
                 "Bottom of the girdle band (z, mm)"),
                ("VolumeMM3", "Measurements", "Finished volume (mm^3)")):
            if not hasattr(obj, name):
                obj.addProperty("App::PropertyFloat", name, group, doc)
            obj.setEditorMode(name, 1)          # read-only, computed
        if not hasattr(obj, "FacetCount"):
            obj.addProperty("App::PropertyInteger", "FacetCount",
                            "Measurements",
                            "Number of distinct facet planes")
        obj.setEditorMode("FacetCount", 1)
        if not hasattr(obj, "TipFeature"):
            obj.addProperty("App::PropertyLink", "TipFeature", "Gem",
                            "Pipeline tip the measurements are taken from")
            obj.setPropertyStatus("TipFeature", "Hidden")
        if not hasattr(obj, "DesignName"):
            obj.addProperty("App::PropertyString", "DesignName", "Metadata",
                            "Design name")
        if not hasattr(obj, "Author"):
            obj.addProperty("App::PropertyString", "Author", "Metadata",
                            "Design author")
        if not hasattr(obj, "IntendedRI"):
            obj.addProperty("App::PropertyFloat", "IntendedRI", "Metadata",
                            "Refractive index the design's angles target "
                            "(material metadata slot per DESIGN.md section 6)")
            obj.IntendedRI = 1.54
        if not hasattr(obj, "SourceFile"):
            obj.addProperty("App::PropertyString", "SourceFile", "Metadata",
                            "Source design file (e.g. imported .ASC)")
        if not hasattr(obj, "DisplayUnits"):
            obj.addProperty("App::PropertyEnumeration", "DisplayUnits",
                            "Metadata", "Preferred display units")
            obj.DisplayUnits = DISPLAY_UNITS
            obj.DisplayUnits = "mm"
        if not hasattr(obj, "SchemaVersion"):
            obj.addProperty("App::PropertyInteger", "SchemaVersion", "Gem",
                            "Property schema version (for migration)")
            obj.SchemaVersion = GEM_SCHEMA_VERSION
            obj.setPropertyStatus("SchemaVersion", "Hidden")

    def onChanged(self, obj, prop):
        if prop == "Group" and not getattr(obj.Document, "Restoring", False):
            resequence(obj)

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        # PartDesign-body load behavior: only the pipeline tip visible.
        resequence(obj, sync_visibility=True)

    def execute(self, obj):
        # The Gem group itself carries no shape; the tip feature does.
        # What it does own is the measurement set, refreshed here so the
        # tree always shows current figures.
        update_measurements(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_gem(doc, label="Gem", index_gear=96, handedness=DEFAULT_HANDEDNESS):
    """Create a new Gem container in ``doc``."""
    obj = doc.addObject("App::DocumentObjectGroupPython", "Gem")
    GemProxy(obj)
    obj.Label = label
    obj.IndexGear = int(index_gear)
    obj.Handedness = HANDEDNESS_VALUES[0 if int(handedness) == -1 else 1]
    # Keep the default group ViewProvider: it already provides tree
    # drag-and-drop reordering and child claiming.
    return obj
