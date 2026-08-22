# SPDX-License-Identifier: LGPL-2.1-or-later
"""2D diagram overlay: per-facet tint by tier light-return share
(DESIGN_OPTICS.md section 8, Phase 4b).

Turns a fresh study's stored per-tier attribution into the ``tier_tint``
mapping the diagram renderer accepts (``diagram.svg.render_svg``): tier
document Name -> SVG fill. The tint scale blends the diagram's white base
toward a warm gold with the tier's *light-return share*, normalized to
the best-returning tier, so the strongest tier reads fully gold and a
dead tier stays white. The overlay reuses the diagram renderer — it is an
optional fill layer, not a fork.

Headless-safe: no GUI imports; consumes only stored study properties.
"""

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.optics import study_feature

__all__ = ["share_color", "tier_tint_from_study", "tier_tint_for_gem"]

#: Full-share tint (warm gold); zero share stays the base white.
_TINT_RGB = (247, 196, 44)


def share_color(share, max_share):
    """SVG fill for a light-return ``share`` on a 0..``max_share`` scale."""
    u = 0.0 if max_share <= 0.0 else max(0.0, min(share / max_share, 1.0))
    rgb = tuple(round(255 + (c - 255) * u) for c in _TINT_RGB)
    return "#%02x%02x%02x" % rgb


def tier_tint_from_study(study):
    """``tier_tint`` mapping for a study's Gem, or {} when unusable.

    Requires a fresh (non-stale) study whose stored per-tier rows still
    line up with the Gem's tier list — anything else returns {} so the
    diagram silently falls back to its base rendering.
    """
    if study is None or getattr(study, "Stale", True):
        return {}
    gem = gem_feature.find_gem(study)
    if gem is None:
        return {}
    tiers = [f for f in gem_feature.pipeline_features(gem)
             if gem_feature.is_tier(f)]
    names = list(study.TierNames)
    returns = list(study.TierReturnPct)
    # Stored rows are the polytope's tiers in pipeline order plus the
    # trailing "(none)" bucket (see metrics.tier_table).
    if len(names) != len(tiers) + 1 or len(returns) != len(names):
        return {}
    shares = returns[:len(tiers)]
    max_share = max(shares) if shares else 0.0
    return {tier.Name: share_color(share, max_share)
            for tier, share in zip(tiers, shares)}


def tier_tint_for_gem(gem):
    """The overlay for a Gem's single fresh study, or {}."""
    if gem is None:
        return {}
    fresh = [s for s in study_feature.find_studies(gem)
             if not getattr(s, "Stale", True) and list(s.TierNames)]
    if len(fresh) != 1:
        return {}
    return tier_tint_from_study(fresh[0])
