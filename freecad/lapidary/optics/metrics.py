# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headline optics numbers (DESIGN_OPTICS.md sections 4, 5, 10).

Definitions (binding; restated in report output so results are
interpretable on their own terms — no cross-tool comparability is claimed):

- **light return (brightness) %**: the mean, over primary rays that hit the
  stone, of the pixel value ``sum(branch_energy * L(exit_dir))``, times 100.
  With the default uniform-hemisphere lighting (L = 1 above the horizon)
  this is the mean fraction of each primary ray's energy that returns to
  the upward view hemisphere from the lighting environment.
- **leak %**: the mean, over hitting primary rays, of the energy fraction
  that exits the pavilion side (downward in the view frame), times 100.
- **per-tier table**: incident-energy shares attributed by the tier of the
  ray path's first pavilion interaction (see tracer docstring), split into
  returned (up) and leaked (down), as percentages of total incident energy
  on the stone.
- **tilt curve**: brightness % re-evaluated at a series of tilt angles
  (numbers only in Phase 4a; plots are 4b).
- **mean / max internal path length** (mm): the energy-weighted mean over
  escaping branches of the distance travelled inside the stone, and the
  longest escaping branch's path (DESIGN_OPTICS.md section 4 — feeds 4c
  Beer-Lambert body color; long-path designs bruise more in colored
  material).

Pure numpy; no FreeCAD imports.
"""

import numpy as np

from freecad.lapidary.optics import tracer as _tracer

__all__ = [
    "brightness_pct",
    "leak_pct",
    "pruned_pct",
    "mean_path_length",
    "tier_table",
    "tilt_curve",
    "summary_text",
]


def brightness_pct(result):
    """Light return %: mean pixel brightness over hitting rays * 100."""
    hits = result.hit_mask
    if not np.any(hits):
        return 0.0
    return 100.0 * float(np.mean(result.brightness[hits]))


def leak_pct(result):
    """Leak %: mean downward-escaping energy over hitting rays * 100."""
    hits = result.hit_mask
    if not np.any(hits):
        return 0.0
    return 100.0 * float(np.mean(result.leaked[hits]))


def pruned_pct(result):
    """Energy dropped by MinEnergy/MaxDepth, as % of incident energy."""
    hits = result.hit_mask
    if not np.any(hits):
        return 0.0
    return 100.0 * float(np.mean(result.pruned[hits]))


def mean_path_length(result):
    """Energy-weighted mean internal path length (mm) over escaping
    branches of all hitting rays (the first-surface reflection counts
    with length 0)."""
    hits = result.hit_mask
    escaped = float(np.sum(result.delivered[hits])
                    + np.sum(result.leaked[hits]))
    if escaped <= 0.0:
        return 0.0
    return float(np.sum(result.path_length_sum[hits])) / escaped


def tier_table(result):
    """Per-tier attribution rows.

    Each row: ``{"tier": label, "return_pct": r, "leak_pct": l}`` — the
    share of total incident energy (over hitting primary rays) that
    returned / leaked, attributed to the tier of the first pavilion
    interaction. The final "(none)" row is energy whose path never touched
    a pavilion facet. Rows plus pruned energy account for 100 %.
    """
    n_hit = result.num_hit
    if n_hit == 0:
        return []
    rows = []
    for label, ret, leak in zip(result.tier_labels, result.tier_return,
                                result.tier_leak):
        rows.append({
            "tier": label,
            "return_pct": 100.0 * float(ret) / n_hit,
            "leak_pct": 100.0 * float(leak) / n_hit,
        })
    return rows


def tilt_curve(poly, n_gem, lighting=None, tilt_max_deg=30.0, tilt_steps=7,
               tilt_azimuth_deg=0.0, **trace_kwargs):
    """Brightness % at evenly spaced tilts from 0 to ``tilt_max_deg``.

    Returns ``(tilts_deg, brightness_pcts)`` as two float arrays. Numbers
    only (Phase 4a); the 4b results dock plots them.
    """
    tilts = np.linspace(0.0, float(tilt_max_deg), int(tilt_steps))
    values = []
    for tilt in tilts:
        result = _tracer.trace(poly, n_gem, lighting, tilt_deg=float(tilt),
                               tilt_azimuth_deg=tilt_azimuth_deg,
                               **trace_kwargs)
        values.append(brightness_pct(result))
    return tilts, np.array(values)


def summary_text(result, material=None):
    """Human-readable study summary embedding the metric definitions
    (DESIGN_OPTICS.md section 10: every metric restated in report output)."""
    lines = []
    if material is not None:
        lines.append("Material: %s" % material.describe())
    lines += [
        "Lighting: %s" % result.lighting_description,
        "Grid %dx%d, tilt %.1f deg, n = %.4f, max depth %d, min energy %g"
        % (result.resolution, result.resolution, result.tilt_deg,
           result.n_gem, result.max_depth, result.min_energy),
        "",
        "Light return: %.1f %%  (mean over hitting rays of the energy "
        "returned from the lighting environment, weighted by L)"
        % brightness_pct(result),
        "Leakage: %.1f %%  (mean energy fraction exiting the pavilion side)"
        % leak_pct(result),
        "Pruned: %.2f %%  (dropped below MinEnergy / beyond MaxDepth)"
        % pruned_pct(result),
        "Internal path length: mean %.2f mm (energy-weighted over escaping "
        "branches), max %.2f mm"
        % (mean_path_length(result), result.max_path_length),
        "",
        "Per-tier attribution (by first pavilion interaction), % of "
        "incident energy:",
    ]
    for row in tier_table(result):
        if row["return_pct"] < 0.05 and row["leak_pct"] < 0.05:
            continue
        lines.append("  %-24s return %5.1f %%   leak %5.1f %%"
                     % (row["tier"], row["return_pct"], row["leak_pct"]))
    lines += [
        "",
        "Metrics are Lapidary-defined (DESIGN_OPTICS.md sections 4-5) and "
        "are not comparable with figures from other tools.",
        "Runtime: %.2f s" % result.runtime_s,
    ]
    return "\n".join(lines)
