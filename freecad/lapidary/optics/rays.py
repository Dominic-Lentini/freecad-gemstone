# SPDX-License-Identifier: LGPL-2.1-or-later
"""Single-ray branch tree for the interactive path visual
(DESIGN_OPTICS.md section 8, ``Lapidary_TraceRay``).

Traces ONE primary ray and records every segment for drawing: the
incident approach, each internal leg (carrying the continuing branch's
energy), and a short terminal arrow for every escaping branch. On a
convex stone the branch "tree" is exactly the internal chain plus its
terminal escape twigs (an escaped branch never re-enters), so the walk is
a simple loop over the same physics as the batch tracer.

Headless module: pure numpy over the polytope walk plus the tracer's
Fresnel helpers; the pivy drawing lives in optics/commands.py and fails
soft without a 3D view.
"""

from dataclasses import dataclass

import numpy as np

from freecad.lapidary.optics.tracer import (
    DEFAULT_MAX_DEPTH, DEFAULT_MIN_ENERGY, fresnel_unpolarized, reflect)

__all__ = ["RaySegment", "ray_tree", "wavelength_color",
           "WAVELENGTH_COLORS", "KIND_INCIDENT", "KIND_INTERNAL",
           "KIND_ESCAPE"]

#: Nominal display colors per wavelength sample (nm) — presentation
#: only, shared by the RayTrace document objects and any overlay.
WAVELENGTH_COLORS = {
    435.8: (0.55, 0.25, 0.95),   # violet
    486.1: (0.20, 0.45, 1.00),   # F line, blue
    589.3: (1.00, 0.78, 0.15),   # D line, amber
    656.3: (1.00, 0.25, 0.15),   # C line, red
    706.5: (0.72, 0.08, 0.08),   # deep red
}


def wavelength_color(nm):
    """The display color for a wavelength: its sample color, or the
    nearest sample's for anything off-grid."""
    return WAVELENGTH_COLORS[min(WAVELENGTH_COLORS,
                                 key=lambda w: abs(w - float(nm)))]


KIND_INCIDENT = "incident"     # approach outside the stone
KIND_INTERNAL = "internal"     # continuing branch inside the stone
KIND_ESCAPE = "escape"         # terminal escaping branch (drawn short)


@dataclass
class RaySegment:
    """One drawable polyline leg of the branch tree."""

    start: tuple
    end: tuple
    energy: float          # the branch's energy fraction of the primary ray
    kind: str              # KIND_*
    depth: int             # 0 = entry event


def ray_tree(poly, n_gem, point, direction=(0.0, 0.0, -1.0),
             max_depth=DEFAULT_MAX_DEPTH, min_energy=DEFAULT_MIN_ENERGY,
             escape_length=None):
    """Trace the primary ray through ``point`` along ``direction``.

    ``point`` is any point on the ray (typically a picked surface point);
    the ray is re-anchored outside the stone. Returns a list of
    :class:`RaySegment`; empty when the ray misses. Escape segments are
    drawn ``escape_length`` long (default: 40 % of the bounding radius).
    """
    r = poly.bounding_radius()
    if escape_length is None:
        escape_length = 0.4 * r
    eps = 1e-7 * r
    v = np.asarray(direction, dtype=np.float64)
    v = v / np.linalg.norm(v)
    origin = np.asarray(point, dtype=np.float64) - v * (3.0 * r)

    segments = []
    o = origin[None, :]
    vv = v[None, :]
    hit, t_in, face_in = poly.entry_hits(o, vv)
    if not bool(hit[0]):
        return segments
    p_hit = o + t_in[:, None] * vv
    n = poly.normals[face_in]
    segments.append(RaySegment(tuple(origin), tuple(p_hit[0]), 1.0,
                               KIND_INCIDENT, 0))

    cos_i = -np.sum(vv * n, axis=1)
    R0, cos_t, _tir = fresnel_unpolarized(1.0, n_gem, cos_i)
    refl = reflect(vv, n)[0]
    segments.append(RaySegment(
        tuple(p_hit[0]), tuple(p_hit[0] + refl * escape_length),
        float(R0[0]), KIND_ESCAPE, 0))

    mu = 1.0 / n_gem
    v_in = mu * vv + ((mu * cos_i - cos_t)[:, None]) * n
    v_in /= np.linalg.norm(v_in, axis=1, keepdims=True)
    e = float(1.0 - R0[0])
    o = p_hit - eps * n
    v_cur = v_in
    depth = 1
    while e >= min_energy and depth < max_depth:
        t_out, face = poly.exit_hits(o, v_cur)
        p_next = o + t_out[:, None] * v_cur
        n = poly.normals[face]
        segments.append(RaySegment(tuple(o[0]), tuple(p_next[0]), e,
                                   KIND_INTERNAL, depth))
        cos_i = np.sum(v_cur * n, axis=1)
        Rf, cos_t, tir = fresnel_unpolarized(n_gem, 1.0, cos_i)
        if not bool(tir[0]):
            out_dir = (n_gem * v_cur
                       - ((n_gem * cos_i - cos_t)[:, None]) * n)
            out_dir /= np.linalg.norm(out_dir, axis=1, keepdims=True)
            segments.append(RaySegment(
                tuple(p_next[0]),
                tuple(p_next[0] + out_dir[0] * escape_length),
                e * float(1.0 - Rf[0]), KIND_ESCAPE, depth))
        e *= float(Rf[0])
        v_cur = reflect(v_cur, n)
        v_cur /= np.linalg.norm(v_cur, axis=1, keepdims=True)
        o = p_next - eps * n
        depth += 1
    return segments
