# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independent scalar reference tracer (DESIGN_OPTICS.md section 10).

A deliberately naive, per-ray recursive implementation of the physics in
DESIGN_OPTICS.md section 4 — written to be *obviously correct* rather than
fast, and sharing **no code** with ``freecad.lapidary.optics.tracer``
beyond material constants. Everything here is plain Python floats, tuples
and ``math``; no numpy. Independent implementations rarely share bugs, so
per-pixel agreement between this tracer and the vectorized engine is the
project's strongest correctness evidence (no third-party tool is treated
as reference truth).

Geometry input: a list of ``(normal, d)`` plane pairs (outward unit
normals; inside is ``n . x <= d``) plus parallel per-face metadata lists.
Tests build these from a Polytope's arrays — data conversion, not shared
logic.

Lighting input: a plain callable ``L(direction_tuple) -> float`` evaluated
in the view frame, plus an optional head-cone test callable.
"""

import math

#: Mirror of the vectorized tracer's defaults (constants, not code).
MAX_DEPTH = 32
MIN_ENERGY = 1e-3


# ---------------------------------------------------------------------------
# Scalar vector helpers
# ---------------------------------------------------------------------------

def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add_scaled(p, t, v):
    return (p[0] + t * v[0], p[1] + t * v[1], p[2] + t * v[2])


def _scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


def _normalize(v):
    m = math.sqrt(_dot(v, v))
    return (v[0] / m, v[1] / m, v[2] / m)


def _reflect(v, n):
    s = 2.0 * _dot(v, n)
    return (v[0] - s * n[0], v[1] - s * n[1], v[2] - s * n[2])


# ---------------------------------------------------------------------------
# Physics, written out longhand
# ---------------------------------------------------------------------------

def _fresnel(n1, n2, cos_i):
    """Unpolarized reflectance and transmission cosine; (R, cos_t or None).

    Returns R = 1 and cos_t = None under total internal reflection.
    """
    sin_i2 = 1.0 - cos_i * cos_i
    sin_t2 = (n1 / n2) * (n1 / n2) * sin_i2
    if sin_t2 >= 1.0:
        return 1.0, None
    cos_t = math.sqrt(1.0 - sin_t2)
    rs = ((n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)) ** 2
    rp = ((n1 * cos_t - n2 * cos_i) / (n1 * cos_t + n2 * cos_i)) ** 2
    return 0.5 * (rs + rp), cos_t


# ---------------------------------------------------------------------------
# Naive ray/polytope intersection (linear scans, no vectorization)
# ---------------------------------------------------------------------------

def _entry(planes, origin, direction):
    """(t_in, face) of the entry crossing, or (None, None) on a miss."""
    t_in, face_in, t_out = None, None, None
    for i, (n, d) in enumerate(planes):
        nv = _dot(n, direction)
        num = d - _dot(n, origin)
        if abs(nv) < 1e-12:
            if num < 0.0:      # parallel and outside this slab: no entry
                return None, None
            continue
        t = num / nv
        if nv < 0.0:
            if t_in is None or t > t_in:
                t_in, face_in = t, i
        else:
            if t_out is None or t < t_out:
                t_out = t
    if t_in is None or t_out is None:
        return None, None
    if t_in <= t_out and t_out > 0.0 and t_in > 0.0:
        return t_in, face_in
    return None, None


def _exit(planes, origin, direction):
    """(t_out, face) of the exit crossing for an inside origin."""
    t_best, face_best = None, None
    for i, (n, d) in enumerate(planes):
        nv = _dot(n, direction)
        if nv <= 1e-12:
            continue
        t = (d - _dot(n, origin)) / nv
        if t_best is None or t < t_best:
            t_best, face_best = t, i
    return t_best, face_best


# ---------------------------------------------------------------------------
# The recursive tracer
# ---------------------------------------------------------------------------

class PixelResult:
    """Accumulated outcome of one primary ray."""

    def __init__(self, num_tiers):
        self.hit = False
        self.brightness = 0.0
        self.delivered = 0.0     # escaped upward (view frame)
        self.leaked = 0.0        # escaped downward
        self.pruned = 0.0
        self.head = 0.0
        #: sum(branch energy * internal path length) over escaping
        #: branches, and the longest escaping branch's path.
        self.path_energy = 0.0
        self.max_path = 0.0
        self.tier_return = [0.0] * (num_tiers + 1)
        self.tier_leak = [0.0] * (num_tiers + 1)


def trace_pixel(planes, is_pavilion, face_tier, num_tiers, n_gem,
                origin, direction, L, to_view=None, head_test=None,
                max_depth=MAX_DEPTH, min_energy=MIN_ENERGY, eps=None):
    """Trace one primary ray; returns a :class:`PixelResult`.

    ``planes``: [(normal, d)] with tuple normals; ``is_pavilion`` /
    ``face_tier``: per-face metadata lists; ``L``: view-frame lighting
    callable; ``to_view``: optional stone->view direction transform (a
    callable taking and returning a 3-tuple; identity when None);
    ``head_test``: optional view-frame head-cone predicate.
    """
    if eps is None:
        eps = 1e-7 * max(abs(d) for _n, d in planes)
    if to_view is None:
        to_view = lambda v: v          # noqa: E731 - identity, view = stone
    result = PixelResult(num_tiers)

    def deposit(energy, exit_dir_stone, first_pav, path_length):
        dv = to_view(exit_dir_stone)
        result.brightness += energy * L(dv)
        result.path_energy += energy * path_length
        if path_length > result.max_path:
            result.max_path = path_length
        tier = first_pav if first_pav is not None else num_tiers
        if dv[2] > 0.0:
            result.delivered += energy
            result.tier_return[tier] += energy
            if head_test is not None and head_test(dv):
                result.head += energy
        else:
            result.leaked += energy
            result.tier_leak[tier] += energy

    def walk(origin, direction, energy, depth, first_pav, path_length):
        """Recur on the internally-reflected branch until pruned."""
        if energy < min_energy or depth >= max_depth:
            result.pruned += energy
            return
        t, face = _exit(planes, origin, direction)
        n, _d = planes[face]
        hit_point = _add_scaled(origin, t, direction)
        path_length = path_length + t      # unit direction: t is distance
        if first_pav is None and is_pavilion[face]:
            first_pav = face_tier[face]
        cos_i = _dot(direction, n)
        R, cos_t = _fresnel(n_gem, 1.0, cos_i)
        if cos_t is not None:
            # Refracted branch escapes (convex stone: terminal).
            mu = n_gem / 1.0
            k = mu * cos_i - cos_t
            out_dir = _normalize(_sub(_scale(direction, mu), _scale(n, k)))
            deposit(energy * (1.0 - R), out_dir, first_pav, path_length)
        walk(_sub(hit_point, _scale(n, eps)),
             _normalize(_reflect(direction, n)),
             energy * R, depth + 1, first_pav, path_length)

    t_in, face = _entry(planes, origin, direction)
    if t_in is None:
        return result
    result.hit = True
    n, _d = planes[face]
    hit_point = _add_scaled(origin, t_in, direction)
    first_pav = face_tier[face] if is_pavilion[face] else None
    cos_i = -_dot(direction, n)
    R0, cos_t = _fresnel(1.0, n_gem, cos_i)
    # First-surface reflection: terminal, never inside -> path length 0.
    deposit(R0, _normalize(_reflect(direction, n)), first_pav, 0.0)
    # Refracted branch enters the stone.
    mu = 1.0 / n_gem
    k = mu * cos_i - cos_t
    in_dir = _normalize(_add_scaled(_scale(direction, mu), k, n))
    walk(_sub(hit_point, _scale(n, eps)), in_dir, 1.0 - R0, 1, first_pav,
         0.0)
    return result


def trace_grid(planes, is_pavilion, face_tier, num_tiers, n_gem, resolution,
               extent, L, tilt_deg=0.0, tilt_azimuth_deg=0.0,
               head_test=None, max_depth=MAX_DEPTH, min_energy=MIN_ENERGY,
               start_height=None, eps=None):
    """Trace a full view grid; returns a resolution x resolution list of
    lists of :class:`PixelResult` (indexed [iy][ix], matching the
    vectorized tracer's map layout).

    The tilt rotation is written out independently here:
    ``M = Rz(az) Ry(tilt) Rz(-az)`` maps view vectors to the stone frame;
    its transpose maps stone-frame escape directions back.
    """
    t = math.radians(tilt_deg)
    a = math.radians(tilt_azimuth_deg)
    ct, st, ca, sa = math.cos(t), math.sin(t), math.cos(a), math.sin(a)

    def mat_mul(m, v):
        return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
                m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
                m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])

    ry = ((ct, 0.0, st), (0.0, 1.0, 0.0), (-st, 0.0, ct))
    rz = ((ca, -sa, 0.0), (sa, ca, 0.0), (0.0, 0.0, 1.0))
    rzt = ((ca, sa, 0.0), (-sa, ca, 0.0), (0.0, 0.0, 1.0))
    m = tuple(tuple(sum(rz[i][k] * sum(ry[k][j2] * rzt[j2][j]
                                       for j2 in range(3))
                        for k in range(3)) for j in range(3))
              for i in range(3))
    m_t = tuple(tuple(m[j][i] for j in range(3)) for i in range(3))

    def to_view(v):
        return mat_mul(m_t, v)

    if start_height is None:
        start_height = 3.0 * extent
    down = mat_mul(m, (0.0, 0.0, -1.0))
    rows = []
    for iy in range(resolution):
        row = []
        y = (iy + 0.5) / resolution * (2.0 * extent) - extent
        for ix in range(resolution):
            x = (ix + 0.5) / resolution * (2.0 * extent) - extent
            origin = mat_mul(m, (x, y, start_height))
            row.append(trace_pixel(
                planes, is_pavilion, face_tier, num_tiers, n_gem,
                origin, down, L, to_view=to_view, head_test=head_test,
                max_depth=max_depth, min_energy=min_energy, eps=eps))
        rows.append(row)
    return rows
