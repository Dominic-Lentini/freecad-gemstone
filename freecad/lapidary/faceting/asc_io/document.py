# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mapping between parsed .ASC designs and the Gem/FacetTier pipeline
(DESIGN.md sections 3 and 7). Imports FreeCAD (App side only) — GUI-free,
runs headless under FreeCADCmd.

Import: one Gem + Stock cylinder + one FacetTier per normalized tier spec,
distances mapped 1 ASC unit = 1 mm (the format has no canonical unit; only
ratios matter — see FORMAT_NOTES.md). File-level metadata that has no
first-class Gem property (symmetry line, verbatim heading/footnote lines,
per-tier cutting instructions) is stored in hidden dynamic properties so
export can round-trip it.

Export: the inverse. Tiers must all use the Gem's index gear (the format has
a single gear per file); suppressed tiers are skipped with a warning.
"""

import math

import FreeCAD

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.faceting.asc_io.parser import (
    AscDesign, AscFacet, AscTier, design_tier_specs)
from freecad.lapidary.faceting.gem_feature import make_gem
from freecad.lapidary.faceting.stock_feature import make_stock
from freecad.lapidary.faceting.tier_feature import effective_gear, make_tier

__all__ = ["AscExportError", "design_to_gem", "gem_to_design"]

#: Stock cylinder radius (= half height) as a multiple of the largest plane
#: distance. The foot point of every cut plane lies at most max-distance from
#: the origin, hence strictly inside the rough, so no valid cut can miss.
_STOCK_FACTOR = 2.2


class AscExportError(ValueError):
    """Raised when a Gem cannot be represented in the .ASC format."""


def _set_hidden(obj, prop_type, name, group, doc_text, value):
    if not hasattr(obj, name):
        obj.addProperty(prop_type, name, group, doc_text)
        obj.setPropertyStatus(name, "Hidden")
    setattr(obj, name, value)


def design_to_gem(doc, design, label=None, source_file=""):
    """Create a Gem + Stock + tier pipeline from a parsed design.

    The caller is responsible for ``doc.recompute()``.
    """
    specs = design_tier_specs(design)

    design_name = design.headers[0].strip() if design.headers else ""
    gem = make_gem(doc, label=label or design_name or "ImportedGem",
                   index_gear=abs(design.gear),
                   handedness=1 if design.gear > 0 else -1)
    gem.DesignName = design_name
    if design.refractive_index is not None:
        gem.IntendedRI = design.refractive_index
    gem.SourceFile = source_file
    if len(design.headers) > 1 and design.headers[1].strip().lower().startswith("by "):
        gem.Author = design.headers[1].strip()[3:].strip()

    _set_hidden(gem, "App::PropertyInteger", "AscSymmetryFolds", "ASC",
                "Symmetry fold count from the .ASC y line (round-trip)",
                design.symmetry_folds)
    _set_hidden(gem, "App::PropertyString", "AscSymmetryMirror", "ASC",
                "Mirror flag token from the .ASC y line (round-trip)",
                design.symmetry_mirror or "y")
    _set_hidden(gem, "App::PropertyStringList", "AscHeaders", "ASC",
                "Verbatim H lines from the imported .ASC (round-trip)",
                list(design.headers))
    _set_hidden(gem, "App::PropertyStringList", "AscFootnotes", "ASC",
                "Verbatim F lines from the imported .ASC (round-trip)",
                list(design.footnotes))

    max_distance = max((spec.distance for spec in specs), default=5.0)
    size = 2.0 * _STOCK_FACTOR * max_distance
    make_stock(gem, "Cylinder", {"Diameter": size, "Height": size})

    for number, spec in enumerate(specs, start=1):
        tier = make_tier(
            gem, spec.angle, spec.distance, spec.indices, side=spec.side,
            tier_name=spec.name, index_offset=spec.index_offset,
            label=spec.name or "Tier%02d" % number)
        if spec.instructions:
            _set_hidden(tier, "App::PropertyStringList", "AscInstructions",
                        "ASC", "Cutting-instruction texts from the imported "
                        ".ASC (round-trip)", list(spec.instructions))
    return gem


def gem_to_design(gem):
    """Serialize a Gem's pipeline into an :class:`AscDesign`."""
    handedness = gem_feature.gem_handedness(gem)
    design = AscDesign()
    design.gear = int(gem.IndexGear) * (1 if handedness > 0 else -1)
    design.gear_offset = 0.0
    design.symmetry_folds = int(getattr(gem, "AscSymmetryFolds", 1))
    design.symmetry_mirror = getattr(gem, "AscSymmetryMirror", "y") or "y"
    ri = float(gem.IntendedRI)
    design.refractive_index = ri if ri > 0 else None

    headers = [h for h in getattr(gem, "AscHeaders", [])]
    if not headers:
        if gem.DesignName or gem.Label:
            headers.append(gem.DesignName or gem.Label)
        if gem.Author:
            headers.append("by %s" % gem.Author)
    design.headers = headers
    design.footnotes = [f for f in getattr(gem, "AscFootnotes", [])]

    for feature in gem_feature.pipeline_features(gem):
        if not gem_feature.is_tier(feature):
            continue
        if feature.Suppressed:
            FreeCAD.Console.PrintWarning(
                "ASC export: skipping suppressed tier %s\n" % feature.Label)
            continue
        if effective_gear(feature) != gem.IndexGear:
            raise AscExportError(
                "tier %s uses index gear %d but the .ASC format allows one "
                "gear per file (gem gear: %d)"
                % (feature.Label, effective_gear(feature), gem.IndexGear))

        angle = float(feature.Angle.Value)
        if feature.WorkingSide == "Pavilion":
            angle = -angle if angle != 0.0 else -0.0
        tier = AscTier(angle=angle, distance=float(feature.Distance.Value))

        indices = sorted(feature.Indices) or [int(gem.IndexGear)]
        offset = float(feature.IndexOffset)
        name = feature.TierName
        for position, index in enumerate(indices):
            value = index + offset
            # Keep values in GemCad's printed range: tooth N + fraction wraps
            # past the gear count back onto the low teeth.
            if value > gem.IndexGear + 1e-9:
                value = math.fmod(value, gem.IndexGear)
            tier.facets.append(
                AscFacet(value, name if position == 0 and name else ""))
        tier.instructions = list(getattr(feature, "AscInstructions", []))
        design.tiers.append(tier)
    return design
