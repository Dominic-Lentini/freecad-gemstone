# SPDX-License-Identifier: LGPL-2.1-or-later
"""The gem as a convex polytope (DESIGN_OPTICS.md section 3).

Every stock habit is convex and every facet cut intersects with a half-space,
so the finished gem is always a convex polytope ``{ x : n_f . x <= d_f }``
over its face planes. The optics engine exploits this exactness and must not
fall back to general ray/B-Rep intersection.

This module is pure numpy and importable without FreeCAD: the ray walk and
the :class:`Polytope` container never touch FreeCAD. Only
:func:`extract_polytope` (which reads a Gem document object) imports FreeCAD,
lazily. No GUI imports anywhere.

Convex ray walk (exact, no acceleration structures):

- from *outside*: the standard convex slab test. Per face,
  ``t_f = (d_f - n_f.o) / (n_f.v)``; entry is ``max t_f`` over faces with
  ``n_f.v < 0``, the exit bound is ``min t_f`` over faces with ``n_f.v > 0``;
  the ray hits iff ``t_in <= t_out`` and ``t_out > 0``. Entry face = argmax.
- from *inside*: exit face is simply the argmin of positive ``t_f`` over
  faces with ``n_f.v > 0``. O(F) per bounce, no point-in-polygon tests.

Numerical care (nudging ray origins off faces between bounces) is the
tracer's job, not this module's; the walk itself is exact arithmetic.
"""

import math

import numpy as np

__all__ = [
    "PolytopeError",
    "Polytope",
    "extract_polytope",
    "NO_TIER",
]

#: tier_id value for faces owned by no tier (remaining stock / unknown).
NO_TIER = -1

#: A direction component |n.v| below this is treated as ray-parallel-to-face.
PARALLEL_TOL = 1e-12

#: Two planes are merged as coplanar duplicates when their normals agree to
#: within this on the dot product and their distances to within
#: MERGE_DISTANCE_TOL (in model units, mm).
MERGE_NORMAL_TOL = 1e-9
MERGE_DISTANCE_TOL = 1e-6

#: Planarity / convexity validation tolerance (mm).
GEOMETRY_TOL = 1e-6


class PolytopeError(ValueError):
    """Raised when a shape cannot be traced as a convex polytope.

    The message is user-facing and must always say *what to do about it*
    (DESIGN_OPTICS.md section 3: refuse with an actionable message, never
    mis-trace).
    """


class Polytope:
    """A convex polytope as face planes ``n_f . x <= d_f`` plus per-face
    tier attribution.

    Attributes (all read-only by convention):

    - ``normals``: (F, 3) float64, outward unit normals;
    - ``dists``:   (F,)  float64, plane offsets (``n_f . x = d_f`` on face);
    - ``tier_ids``: (F,) int, index into ``tier_labels`` / ``tier_sides``,
      or :data:`NO_TIER`;
    - ``tier_labels``: tuple of str, one per tier;
    - ``tier_sides``: tuple of str, "Crown" / "Pavilion" / "" per tier;
    - ``areas``: (F,) float64 face areas, or None when not extracted from a
      B-Rep (stats/visuals only — the tracer never needs them);
    - ``polygons``: list of (k, 3) vertex loops per face, or None (same).
    """

    def __init__(self, normals, dists, tier_ids=None, tier_labels=(),
                 tier_sides=(), areas=None, polygons=None):
        normals = np.asarray(normals, dtype=np.float64)
        dists = np.asarray(dists, dtype=np.float64)
        if normals.ndim != 2 or normals.shape[1] != 3:
            raise ValueError("normals must be (F, 3), got %r" % (normals.shape,))
        if dists.shape != (normals.shape[0],):
            raise ValueError("dists must be (F,), got %r" % (dists.shape,))
        lengths = np.linalg.norm(normals, axis=1)
        if not np.allclose(lengths, 1.0, atol=1e-9):
            raise ValueError("normals must be unit length")
        self.normals = normals
        self.dists = dists
        if tier_ids is None:
            tier_ids = np.full(len(dists), NO_TIER, dtype=np.intp)
        self.tier_ids = np.asarray(tier_ids, dtype=np.intp)
        if self.tier_ids.shape != (len(dists),):
            raise ValueError("tier_ids must be (F,)")
        self.tier_labels = tuple(tier_labels)
        self.tier_sides = tuple(tier_sides)
        self.areas = None if areas is None else np.asarray(areas, np.float64)
        self.polygons = polygons
        self._vertices = None

    @property
    def num_faces(self):
        return len(self.dists)

    # -- geometry queries ---------------------------------------------------

    def vertices(self):
        """The polytope's vertex set, (V, 3), by half-space enumeration.

        Every triple of planes is solved and the solutions inside all
        half-spaces (within tolerance) are kept and deduplicated. O(F^3) —
        fine at gem face counts (F ~ 60–200), and used only for extents,
        fixture validation, and stats, never inside the trace loop.
        """
        if self._vertices is None:
            self._vertices = _enumerate_vertices(self.normals, self.dists)
        return self._vertices

    def bounding_radius(self):
        """Radius of the smallest origin-centered sphere containing the
        polytope."""
        verts = self.vertices()
        if len(verts) == 0:
            raise PolytopeError(
                "The face planes bound no volume — the polytope is empty. "
                "Check that the gem still has solid geometry.")
        return float(np.max(np.linalg.norm(verts, axis=1)))

    def contains(self, points, tol=GEOMETRY_TOL):
        """Boolean mask: point satisfies every half-space within ``tol``."""
        points = np.atleast_2d(np.asarray(points, np.float64))
        return np.all(points @ self.normals.T - self.dists <= tol, axis=1)

    # -- convex ray walk ----------------------------------------------------

    def entry_hits(self, origins, dirs):
        """Slab test for rays starting *outside* the polytope.

        Returns ``(hit, t_in, face_in)``: hit mask (N,), entry parameter
        (N,) and entry face index (N,) (valid only where ``hit``).
        """
        origins = np.atleast_2d(np.asarray(origins, np.float64))
        dirs = np.atleast_2d(np.asarray(dirs, np.float64))
        nv = dirs @ self.normals.T                       # (N, F)
        num = self.dists[None, :] - origins @ self.normals.T
        with np.errstate(divide="ignore", invalid="ignore"):
            t = num / nv
        entering = nv < -PARALLEL_TOL
        leaving = nv > PARALLEL_TOL
        t_in = np.max(np.where(entering, t, -np.inf), axis=1)
        face_in = np.argmax(np.where(entering, t, -np.inf), axis=1)
        t_out = np.min(np.where(leaving, t, np.inf), axis=1)
        # A ray parallel to a face and on its outside can never enter.
        parallel_outside = np.any(
            (np.abs(nv) <= PARALLEL_TOL) & (num < 0.0), axis=1)
        hit = (t_in <= t_out) & (t_out > 0.0) & (t_in > 0.0) & ~parallel_outside
        # Rays that never "enter" any face (t_in = -inf) miss by definition.
        hit &= np.isfinite(t_in)
        return hit, t_in, face_in

    def exit_hits(self, origins, dirs):
        """Exit face for rays starting *inside* the polytope.

        Returns ``(t_out, face_out)``, both (N,): the argmin of positive
        ``t_f`` over faces with ``n_f . v > 0``. Callers must ensure the
        origins are (nudged) inside; then a leaving face always exists for
        a bounded polytope and ``t_out > 0``.
        """
        origins = np.atleast_2d(np.asarray(origins, np.float64))
        dirs = np.atleast_2d(np.asarray(dirs, np.float64))
        nv = dirs @ self.normals.T
        num = self.dists[None, :] - origins @ self.normals.T
        with np.errstate(divide="ignore", invalid="ignore"):
            t = num / nv
        leaving = nv > PARALLEL_TOL
        t = np.where(leaving, t, np.inf)
        face_out = np.argmin(t, axis=1)
        t_out = t[np.arange(len(t)), face_out]
        return t_out, face_out


def _enumerate_vertices(normals, dists, tol=GEOMETRY_TOL):
    """All vertices of ``{ x : N x <= d }`` by solving plane triples."""
    from itertools import combinations

    F = len(dists)
    if F < 4:
        return np.empty((0, 3))
    triples = np.array(list(combinations(range(F), 3)), dtype=np.intp)
    A = normals[triples]                      # (T, 3, 3)
    b = dists[triples]                        # (T, 3)
    dets = np.abs(np.linalg.det(A))
    ok = dets > 1e-12
    pts = np.linalg.solve(A[ok], b[ok][..., None])[..., 0]
    inside = np.all(pts @ normals.T - dists <= tol, axis=1)
    pts = pts[inside]
    if len(pts) == 0:
        return np.empty((0, 3))
    # Deduplicate by rounding relative to the model scale.
    scale = max(1.0, float(np.max(np.abs(pts))))
    keys = np.round(pts / (scale * 1e-9)).astype(np.int64)
    _uniq, idx = np.unique(keys, axis=0, return_index=True)
    return pts[np.sort(idx)]


# ---------------------------------------------------------------------------
# Extraction from a Gem document object (the only FreeCAD-touching part)
# ---------------------------------------------------------------------------

def extract_polytope(gem, tol=GEOMETRY_TOL):
    """Extract the :class:`Polytope` of a Gem's final B-Rep, validated.

    Validation per DESIGN_OPTICS.md section 3 — refuse with an actionable
    message, never mis-trace:

    - closed solid, single shell;
    - every face an exact analytic plane (a curved girdle remnant of the
      rough fails here, pointing the user at a 90° girdle tier);
    - convexity: every vertex satisfies all half-space constraints;
    - near-duplicate plane merging (coplanar faces from adjacent cuts).

    Tier attribution reuses the Phase 1 ownership mechanism
    (``faceting.ownership.classify_faces``), which is exact for planes this
    workbench cut itself.
    """
    import Part  # deferred: keeps this module importable without FreeCAD

    from freecad.lapidary.faceting import gem_feature, ownership

    shape = gem_feature.final_shape(gem)
    label = getattr(gem, "Label", "the gem")
    if shape is None:
        raise PolytopeError(
            "%s has no solid geometry yet. Cut at least a stock and recompute "
            "the document before running an optics study." % label)
    if len(shape.Solids) != 1:
        raise PolytopeError(
            "%s is %d solids; the optics engine needs exactly one. Check for "
            "a cut that split the stone." % (label, len(shape.Solids)))
    solid = shape.Solids[0]
    if len(solid.Shells) != 1 or not solid.Shells[0].isClosed():
        raise PolytopeError(
            "%s is not a single closed shell. Recompute the document and "
            "check the tier list for errors before running optics." % label)

    features = gem_feature.pipeline_features(gem)
    tiers = [f for f in features if gem_feature.is_tier(f)]
    tier_labels = tuple(
        (getattr(t, "TierName", "") or t.Label) for t in tiers)
    tier_sides = tuple(getattr(t, "WorkingSide", "") for t in tiers)
    tier_index = {t: i for i, t in enumerate(tiers)}

    owners = ownership.classify_faces(gem)
    normals, dists, tier_ids, areas, polygons = [], [], [], [], []
    for face, owner in zip(solid.Faces, owners):
        plane = ownership.face_plane(face)
        if plane is None:
            raise PolytopeError(
                "%s still has a non-planar face (area %.3f mm² of type %s) — "
                "usually the curved surface of the rough that was never cut "
                "away. Add a 90° girdle tier (or extend the existing cuts) so "
                "the whole surface is faceted, then rerun."
                % (label, face.Area, type(face.Surface).__name__))
        normal, d = plane
        normals.append([normal.x, normal.y, normal.z])
        dists.append(d)
        tier_ids.append(tier_index.get(owner, NO_TIER))
        areas.append(face.Area)
        polygons.append(_face_loop(face))

    normals = np.asarray(normals)
    dists = np.asarray(dists)
    tier_ids = np.asarray(tier_ids, dtype=np.intp)
    areas = np.asarray(areas)

    normals, dists, tier_ids, areas, polygons = _merge_coplanar(
        normals, dists, tier_ids, areas, polygons)

    poly = Polytope(normals, dists, tier_ids, tier_labels, tier_sides,
                    areas=areas, polygons=polygons)

    # Convexity: every B-Rep vertex must satisfy every half-space. The
    # tolerance scales with the stone so large stones do not false-positive.
    verts = np.array([[v.X, v.Y, v.Z] for v in solid.Vertexes])
    scale = max(1.0, float(np.max(np.abs(verts))))
    excess = verts @ normals.T - dists
    worst = float(np.max(excess))
    if worst > tol * scale:
        bad = np.unravel_index(np.argmax(excess), excess.shape)
        raise PolytopeError(
            "%s is not convex: vertex %d lies %.2e mm outside the plane of "
            "face %d. The optics engine only traces convex faceted stones; "
            "check for a concave feature or a modeling error." %
            (label, int(bad[0]), worst, int(bad[1])))
    return poly


def _face_loop(face):
    """The outer boundary polygon of a planar B-Rep face, (k, 3)."""
    wire = face.OuterWire
    pts = [np.array([v.X, v.Y, v.Z]) for v in wire.OrderedVertexes]
    return np.array(pts) if pts else np.empty((0, 3))


def _merge_coplanar(normals, dists, tier_ids, areas, polygons):
    """Merge near-duplicate planes (coplanar faces from adjacent cuts).

    The merged plane keeps the attribution of its largest-area member;
    areas sum; the polygons of all members are kept (visuals only).
    """
    order = np.argsort(dists, kind="stable")
    used = np.zeros(len(dists), dtype=bool)
    out_n, out_d, out_t, out_a, out_p = [], [], [], [], []
    for i in order:
        if used[i]:
            continue
        same = (~used
                & (normals @ normals[i] > 1.0 - MERGE_NORMAL_TOL)
                & (np.abs(dists - dists[i]) < MERGE_DISTANCE_TOL))
        idx = np.nonzero(same)[0]
        used[idx] = True
        main = idx[np.argmax(areas[idx])]
        out_n.append(normals[main])
        out_d.append(dists[main])
        out_t.append(tier_ids[main])
        out_a.append(float(np.sum(areas[idx])))
        merged_polys = [polygons[j] for j in idx]
        out_p.append(merged_polys[0] if len(merged_polys) == 1 else merged_polys)
    return (np.asarray(out_n), np.asarray(out_d),
            np.asarray(out_t, dtype=np.intp), np.asarray(out_a), out_p)


# ---------------------------------------------------------------------------
# Fixture helpers (pure numpy; used by tests and docs examples)
# ---------------------------------------------------------------------------

def cube(half=1.0):
    """An axis-aligned cube [-half, half]^3. Face order: +X -X +Y -Y +Z -Z."""
    n = np.array([[1, 0, 0], [-1, 0, 0],
                  [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], dtype=np.float64)
    d = np.full(6, float(half))
    return Polytope(n, d)


def box(hx, hy, hz):
    """An axis-aligned box with half-extents. Face order as :func:`cube`."""
    n = np.array([[1, 0, 0], [-1, 0, 0],
                  [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], dtype=np.float64)
    d = np.array([hx, hx, hy, hy, hz, hz], dtype=np.float64)
    return Polytope(n, d)


def octahedron(circum=1.0):
    """A regular octahedron with vertices at distance ``circum`` on the axes.

    Faces are the 8 sign combinations of ``(±x ±y ±z)/sqrt(3) . x = c/sqrt(3)``.
    """
    s = 1.0 / math.sqrt(3.0)
    signs = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
    n = np.array(signs, dtype=np.float64) * s
    d = np.full(8, float(circum) * s)
    return Polytope(n, d)
