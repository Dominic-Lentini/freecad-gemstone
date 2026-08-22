# SPDX-License-Identifier: LGPL-2.1-or-later
"""The FacetTier feature (DESIGN.md sections 2.1 and 3).

One tier = one (angle, distance, index-list) group of half-space cuts applied
to the previous solid in the Gem's pipeline. Property schema v1 per DESIGN.md
section 3, stamped with ``SchemaVersion`` for migration.

Failure handling (DESIGN.md section 3, normative; miss reporting relaxed
post-0.1.0):

* A cut plane that misses the solid entirely is NOT an error and NOT a
  warning: the tier produces no change for that index and the fact is
  recorded quietly in ``TierState`` (``"OK (n of m cuts missed)"``) for the
  task panel's status line. No console message and no tree marker — misses
  are routine during live preview and the messages drowned everything else.
* A cut that annihilates the solid (or a non-positive distance) blocks the
  tier's recompute with a *recoverable* error: the tier's shape is set to the
  upstream shape (so the upstream geometry stays displayed) and the recompute
  raises, marking the feature Invalid in the tree. Fixing the offending
  property clears the error on the next recompute.

Depth reference (schema v3): ``CutDepth`` is measured inward from the
reference boundary of the tier's **base solid** — the circumscribed cylinder
of what is actually left of the stone when this tier cuts, not of the
original stock. Depth 0 grazes the current solid, so the cut plane starts
where there is still material instead of travelling through space the
earlier tiers already removed. The reference stays rotationally symmetric
about Z (longest remaining radius, z extent), so it is independent of the
index.

Face-ownership tagging (needed by the Phase 3 diagram): OpenCascade booleans
do not preserve user tags on faces, but every facet this workbench creates is
an *exact analytic plane* whose (normal, distance) pair the tier itself
computed. So each tier records the exact planes of the cuts it actually
performed in two hidden output properties, ``CutNormals`` and
``CutDistances``, refreshed on every recompute. A face of the final B-Rep is
then attributed to the *most-downstream* tier whose recorded plane matches
the face's plane within tolerance (a later tier that re-cuts an identical
plane owns the face, because its cut re-created it); faces matching no tier
belong to the Stock. See :mod:`freecad.lapidary.faceting.ownership` and
docs/dev-notes.md.

Importable headless; the ViewProvider is attached only when a GUI is up.
"""

import math

import FreeCAD

from freecad.lapidary.core import gemmath, halfspace
from freecad.lapidary.faceting import gem_feature

__all__ = ["TIER_SCHEMA_VERSION", "TierProxy", "make_tier",
           "effective_gear", "effective_planes", "reference_distance",
           "effective_normals", "depth_through_point", "meetpoint_depths"]

#: Schema history:
#: 1 — DESIGN.md section 3 initial schema (Distance is the user parameter).
#: 2 — CutDepth added as the user-facing depth parameter, measured inward
#:     from the stock's reference boundary; Distance became a computed,
#:     read-only output (still the canonical stored plane parameter used by
#:     ownership, reports and .ASC export).
#: 3 — CutDepth is now measured from the reference boundary of the tier's
#:     *base solid* (what is left of the stone), not the original stock, so
#:     a zero depth always grazes remaining material. Migration keeps the
#:     stored plane Distance fixed and rederives CutDepth against the new
#:     reference.
TIER_SCHEMA_VERSION = 3

#: Relative volume tolerances for the two DESIGN.md section 3 failure modes.
NOOP_REL_TOL = 1e-9          # removed less than this fraction -> no-op cut
ANNIHILATION_REL_TOL = 1e-9  # remaining less than this fraction -> annihilated


def effective_gear(obj):
    """The tier's effective index gear: its own IndexGear, or the Gem's when
    IndexGear is 0 (= inherit, DESIGN.md section 3 schema)."""
    if obj.IndexGear > 0:
        return obj.IndexGear
    gem = gem_feature.find_gem(obj)
    if gem is not None:
        return gem.IndexGear
    return 96


def _stock_reference(obj):
    """The reference boundary of the gem's *starting* shape: the maximum
    radius about the Z axis (independent of index) and the stock's z extent.

    Returns (max_radius, z_max, z_min). Falls back to building the stock
    from its habit properties when its Shape has not been computed yet.
    """
    gem = gem_feature.find_gem(obj)
    stock = None
    if gem is not None:
        features = gem_feature.pipeline_features(gem)
        if features and gem_feature.is_stock(features[0]):
            stock = features[0]
    if stock is None:
        raise RuntimeError(
            "%s is not inside a Gem with a Stock; the cut depth needs the "
            "starting shape's boundary as its reference" % obj.Label)
    shape = stock.Shape
    if shape.isNull() or not shape.Vertexes:
        from freecad.lapidary.core import registry
        habit = registry.get_habit(stock.Habit)
        shape = habit.build(**{name: getattr(stock, name).Value
                               for name, _label, _default in habit.params})
    max_radius = max(math.hypot(v.Point.x, v.Point.y)
                     for v in shape.Vertexes)
    bb = shape.BoundBox
    return max_radius, bb.ZMax, bb.ZMin


def _reference_support(obj):
    """(max_radius, z_max, z_min) of the tier's reference solid: its base
    feature's computed shape when available (schema v3 — what is actually
    left of the stone), else the gem's starting stock as a fallback for
    tiers whose base has not been computed yet."""
    base = getattr(obj, "BaseFeature", None)
    if base is not None and not base.Shape.isNull() and base.Shape.Vertexes:
        shape = base.Shape
        max_radius = max(math.hypot(v.Point.x, v.Point.y)
                         for v in shape.Vertexes)
        bb = shape.BoundBox
        return max_radius, bb.ZMax, bb.ZMin
    return _stock_reference(obj)


def reference_distance(obj):
    """Plane distance of a zero-depth cut: the support of the base solid's
    circumscribed reference cylinder in the facet-normal direction.

    A cut with depth 0 just grazes what is left of the stone; CutDepth moves
    the plane inward from there, mirroring how a facet is physically cut
    (from the current surface inward). Independent of the index by
    construction (the reference is rotationally symmetric about Z).
    """
    max_radius, z_max, z_min = _reference_support(obj)
    theta = math.radians(obj.Angle.Value)
    n_z = gemmath.side_sign(obj.WorkingSide) * math.cos(theta)
    return (max_radius * math.sin(theta)
            + max(n_z * z_max, n_z * z_min))


def effective_normals(obj):
    """The unit facet normals this tier defines, one per index in its list
    (an empty list means one single axial facet)."""
    gear = effective_gear(obj)
    handedness = gem_feature.gem_handedness(gem_feature.find_gem(obj))
    indices = list(obj.Indices) or [0]
    return [gemmath.facet_normal(obj.Angle.Value, gear, index,
                                 obj.WorkingSide, obj.IndexOffset, handedness)
            for index in indices]


def depth_through_point(obj, point):
    """The CutDepth that puts one of this tier's facet planes through
    ``point`` (an ``FreeCAD.Vector`` or (x, y, z) triple).

    For a multi-index tier the facet chosen is the one whose plane reaches
    the point first as the cut deepens — the facet *facing* the point
    (largest ``n·p``) — which is the facet a user means when they click a
    vertex or edge on the stone. All facets of a tier share one depth, so
    that plane passes exactly through the point and the others sit at the
    same depth by symmetry.
    """
    px, py, pz = (point.x, point.y, point.z) if hasattr(point, "x") else point
    support = max(nx * px + ny * py + nz * pz
                  for nx, ny, nz in effective_normals(obj))
    return reference_distance(obj) - support


def _boundary_polylines(shape):
    """The solid's boundary edges as polylines (curved edges discretized).

    Every extremum this module needs lives on an edge: the stone is convex
    (an intersection of half-spaces with a convex stock), its only curved
    faces are cylinders about the gem axis, and both the support function
    and the pairwise max–min of :func:`meetpoint_depths` restricted to a
    planar or axis-cylindrical face attain their maximum on the face's
    boundary. So discretized edges are an exact-enough sample of the whole
    boundary.
    """
    import Part

    deflection = (shape.BoundBox.DiagonalLength or 1.0) / 400.0
    polylines = []
    for edge in shape.Edges:
        if isinstance(edge.Curve, Part.Line):
            polylines.append([edge.Vertexes[0].Point,
                              edge.Vertexes[-1].Point])
        else:
            count = max(8, int(math.ceil(edge.Length / deflection)) + 1)
            try:
                polylines.append(list(edge.discretize(Number=count)))
            except Exception:
                # Degenerate edges (a cone/culet apex seam, a zero-length
                # remnant) cannot be discretized: fall back to whatever
                # vertices they carry rather than losing the whole walk.
                points = [v.Point for v in edge.Vertexes]
                if points:
                    polylines.append(points)
    return polylines


def _pair_edge_crossings(polylines, n1, n2):
    """Plane distances at which the *shared edge* of two facet planes (cut
    at one common distance, as a tier is) crosses an existing boundary
    edge of the solid.

    As the pair deepens, its shared edge — the line ``n1·x = n2·x = d`` —
    sweeps through the stone; a discrete meet point forms each time it
    crosses an existing edge (the classic "cut the breaks until they meet
    the mains' arête"). On a boundary segment the function
    ``g(t) = (n1 - n2)·x(t)`` is linear, so the crossing is the sign
    change of ``g``; the meet's distance is ``n1·x`` there. Segments lying
    *in* the bisector plane (g ~ 0 throughout, e.g. an arête exactly
    between the two facets) have their meets at their endpoints, which the
    vertex family already covers.
    """
    dn = (n1[0] - n2[0], n1[1] - n2[1], n1[2] - n2[2])
    crossings = []
    for points in polylines:
        for a, b in zip(points, points[1:]):
            ga = dn[0] * a.x + dn[1] * a.y + dn[2] * a.z
            gb = dn[0] * b.x + dn[1] * b.y + dn[2] * b.z
            if ga == gb or ga * gb > 0.0:
                continue
            if abs(ga) < 1e-12 and abs(gb) < 1e-12:
                continue                  # segment inside the bisector
            t = ga / (ga - gb)
            x = (a.x + t * (b.x - a.x), a.y + t * (b.y - a.y),
                 a.z + t * (b.z - a.z))
            crossings.append(n1[0] * x[0] + n1[1] * x[1] + n1[2] * x[2])
    return crossings


def _pair_meet_distance(polylines, n1, n2):
    """The largest plane distance at which the two facet planes (cut at a
    common distance, as a tier is) meet each other *on* the solid.

    For a convex solid this is ``max over the solid of min(n1·x, n2·x)`` —
    the first point the deepening pair of planes reaches together. That
    concave function attains its maximum on the boundary edges, so it is
    evaluated segment-by-segment over the boundary polylines: each segment
    contributes its endpoints plus the interior point where the two linear
    functions cross.
    """
    best = None
    for points in polylines:
        for a, b in zip(points, points[1:]):
            f1a = n1[0] * a.x + n1[1] * a.y + n1[2] * a.z
            f1b = n1[0] * b.x + n1[1] * b.y + n1[2] * b.z
            f2a = n2[0] * a.x + n2[1] * a.y + n2[2] * a.z
            f2b = n2[0] * b.x + n2[1] * b.y + n2[2] * b.z
            values = [min(f1a, f2a), min(f1b, f2b)]
            denominator = (f1b - f1a) - (f2b - f2a)
            if abs(denominator) > 1e-15:
                t = (f2a - f1a) / denominator
                if 0.0 < t < 1.0:
                    values.append(f1a + t * (f1b - f1a))
            candidate = max(values)
            if best is None or candidate > best:
                best = candidate
    return best


def meetpoint_depths(obj, tol=1e-6):
    """Sorted distinct candidate CutDepths at which this tier's cut forms a
    meet point on its base solid — shallowest first, so ``[0]`` is *the
    minimum cut depth required to form a meet*.

    Two families of meets are considered:

    * **Existing meet points**: vertices of the base solid where at least
      three faces meet, paired with the tier facet that reaches each first
      (see :func:`depth_through_point`). Modelling-artifact vertices — a
      cylinder's seam vertices, where only two faces touch — are *not*
      meet points and are excluded; on bare cylindrical stock they are the
      only vertices, and the surviving one used to masquerade as an absurd
      near-annihilating "meet".
    * **Meets the tier itself creates**: for each azimuth-adjacent pair of
      the tier's facets, (a) the depth at which the two planes first touch
      each other on the solid (:func:`_pair_meet_distance`) — the classic
      first meet when roughing mains onto bare *curved* stock — and (b)
      every depth at which the pair's shared edge crosses an existing
      boundary edge (:func:`_pair_edge_crossings`) — the classic "cut
      until the breaks meet the mains' arête". On polyhedral stock the
      first touch degenerates to a grazing corner (correctly dropped), and
      the edge crossings are the usable meets.

    Useless candidates are dropped: grazing depths (a plane through a
    facet's own support point touches without cutting) and depths at or
    past the gem axis (annihilation). Supports are evaluated over the
    discretized boundary, not just vertices, so curved rough is measured
    correctly. Returns [] when the tier has no computed base solid yet.
    """
    base = getattr(obj, "BaseFeature", None)
    if base is None or base.Shape.isNull() or not base.Shape.Vertexes:
        return []
    import Part

    shape = base.Shape
    reference = reference_distance(obj)
    normals = effective_normals(obj)
    polylines = _boundary_polylines(shape)
    boundary = [p for points in polylines for p in points]
    # Support of the base solid along each facet normal: a plane there only
    # grazes; a cut happens strictly inside it.
    supports = [max(nx * p.x + ny * p.y + nz * p.z for p in boundary)
                for nx, ny, nz in normals]

    def keep(distance, facet_indices):
        """Depth for ``distance``, or None for grazing/annihilating cuts."""
        if any(distance >= supports[i] - tol for i in facet_indices):
            return None
        depth = reference - distance
        if tol < depth < reference - tol:
            return round(depth, 6)
        return None

    depths = set()

    # Existing meet points: true junction vertices only.
    for vertex in shape.Vertexes:
        if len(shape.ancestorsOfType(vertex, Part.Face)) < 3:
            continue
        p = vertex.Point
        dots = [nx * p.x + ny * p.y + nz * p.z for nx, ny, nz in normals]
        best = max(range(len(normals)), key=lambda i: dots[i])
        depth = keep(dots[best], [best])
        if depth is not None:
            depths.add(depth)

    # Meets between azimuth-adjacent facets of this tier.
    count = len(normals)
    if count >= 2:
        order = sorted(range(count),
                       key=lambda i: math.atan2(normals[i][1], normals[i][0]))
        pairs = {tuple(sorted((order[k], order[(k + 1) % count])))
                 for k in range(count if count > 2 else 1)}
        for i, j in pairs:
            n1, n2 = normals[i], normals[j]
            cross = ((n1[1] * n2[2] - n1[2] * n2[1]) ** 2
                     + (n1[2] * n2[0] - n1[0] * n2[2]) ** 2
                     + (n1[0] * n2[1] - n1[1] * n2[0]) ** 2)
            if cross < 1e-18:
                continue                  # parallel planes never meet
            distance = _pair_meet_distance(polylines, n1, n2)
            if distance is not None:
                depth = keep(distance, [i, j])
                if depth is not None:
                    depths.add(depth)
            for distance in _pair_edge_crossings(polylines, n1, n2):
                depth = keep(distance, [i, j])
                if depth is not None:
                    depths.add(depth)

    # Cluster discretization-split duplicates (two pair families sampling
    # the same physical meet can land ~1e-5 apart on curved rough).
    merged = []
    for depth in sorted(depths):
        if not merged or depth - merged[-1] > 1e-3:
            merged.append(depth)
    return merged


# ---------------------------------------------------------------------------
# Auto-depth helpers (the panel's Auto button; headless-testable)
# ---------------------------------------------------------------------------

def axis_flat_face(shape, side, tol=1e-6):
    """The z height of the planar face whose outward normal points straight
    along the working side's axis direction (Pavilion -> -Z, Crown -> +Z),
    or None when the solid has no such face (the side is already cut to a
    meet on the axis)."""
    import Part

    sign = gemmath.side_sign(side)
    for face in shape.Faces:
        if not isinstance(face.Surface, Part.Plane):
            continue
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        if normal.z * sign > 1.0 - tol:
            return face.CenterOfMass.z
    return None


def auto_axis_depth(obj):
    """The Auto button's no-selection case: when the base solid still has a
    flat face square to the gem axis on the working side, the lowest cut
    depth at which every facet of this tier meets at the axis point
    ``(0, 0, z_face)`` — i.e. the depth that consumes that flat face
    completely, closing the tier to a point/keel on the axis. (The face
    center is the last point standing as the planes deepen, so the plane
    through it is exactly that minimum.) Returns None when there is no
    such face — or when this tier *cannot* close one: a 90-degree tier's
    vertical planes have n_z = 0, so the "plane through (0, 0, z)"
    degenerates to the annihilation plane on the axis (observed in the
    GUI: Auto on a girdle tier dialled the full reference depth). Any
    computed depth at or past the reference is refused the same way."""
    base = getattr(obj, "BaseFeature", None)
    if base is None or base.Shape.isNull():
        return None
    if abs(math.cos(math.radians(obj.Angle.Value))) < 1e-9:
        return None                    # vertical planes never close a face
    z = axis_flat_face(base.Shape, obj.WorkingSide)
    if z is None:
        return None
    depth = depth_through_point(obj, (0.0, 0.0, z))
    if depth >= reference_distance(obj) - 1e-9:
        return None                    # would annihilate, not close
    return depth


def depth_to_remove_edge(obj, edge):
    """The lowest cut depth that removes the selected ``edge`` entirely:
    the deepest of the depths that put the facet plane through the edge's
    points (curved edges are discretized). At exactly this depth the plane
    grazes the edge's most-sheltered point; the whole edge recedes."""
    import Part

    if isinstance(edge.Curve, Part.Line):
        points = [edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
    else:
        points = edge.discretize(Number=max(
            16, int(math.ceil(edge.Length)) + 1))
    return max(depth_through_point(obj, p) for p in points)


def align_indices_to_index(obj, target_index):
    """Rotate the tier's whole index pattern, in the gem's handedness
    direction, by the fewest teeth that land one of its facets exactly on
    ``target_index``. Returns the rotated list ([] stays []).

    Used to keep an existing pattern when Auto matches a picked face or
    vertex/edge azimuth — the pattern is *carried*, not replaced, the same
    way rotate-pattern and radial symmetry never lose the user's clicks.
    """
    from freecad.lapidary.faceting.indexspec import rotate_indices

    indices = list(obj.Indices)
    if not indices:
        return indices
    gear = effective_gear(obj)
    target = target_index % gear
    # Fewest forward teeth (in the handedness counting direction) from any
    # current index to the target tooth.
    teeth = min((target - i) % gear for i in indices)
    return rotate_indices(indices, gear, teeth)


def align_indices_to_azimuth(obj, azimuth_deg):
    """Rotate the tier's whole index pattern, in the gem's handedness
    direction, by the fewest teeth that put one of its facets at the gear
    tooth nearest ``azimuth_deg`` (the polar angle of a selected vertex or
    edge). Returns the rotated list ([] stays [])."""
    indices = list(obj.Indices)
    if not indices:
        return indices
    gear = effective_gear(obj)
    handedness = gem_feature.gem_handedness(gem_feature.find_gem(obj))
    # The tooth whose azimuth is nearest the target (§2.1: azimuth =
    # dir * 360 * i / N, so i = dir * azimuth * N / 360).
    target = int(round(handedness * (azimuth_deg % 360.0) * gear
                       / 360.0)) % gear
    return align_indices_to_index(obj, target)


def face_tier_parameters(face, gear, handedness, tol=1e-9):
    """Recover (side, angle_deg, index, distance) from a planar B-Rep face,
    for the Auto button's pick-a-face case: the tier parameters that would
    re-cut exactly this facet.

    ``index`` is the gear tooth nearest the face normal's azimuth (exact
    for facets this workbench cut without a cheater offset). A 90-degree
    girdle facet has no side of its own; "Pavilion" is returned for it by
    the n_z <= 0 convention. Raises ValueError for non-planar faces.
    """
    import Part

    if not isinstance(face.Surface, Part.Plane):
        raise ValueError("only planar faces carry tier parameters")
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    side = "Crown" if normal.z > tol else "Pavilion"
    angle = math.degrees(math.acos(max(-1.0, min(1.0, abs(normal.z)))))
    if math.hypot(normal.x, normal.y) < tol:
        index = 0                       # axial facet: index irrelevant
    else:
        azimuth = math.degrees(math.atan2(normal.y, normal.x)) % 360.0
        index = int(round(handedness * azimuth * gear / 360.0)) % gear
        index = gear if index == 0 else index
    distance = normal.dot(face.CenterOfMass)
    return side, angle, index, distance


def is_girdle_face(face, tol=1e-6):
    """True for the faces the girdle-auto flow accepts: a planar face
    parallel to the gem axis (|n_z| ~ 0), or a cylindrical face whose
    axis IS the gem axis (the raw rough's wall). Both are "a plane
    parallel to the z axis" in the cutter's sense — they belong to the
    girdle band, not to either side."""
    import Part

    if isinstance(face.Surface, Part.Plane):
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        return abs(normal.z) < tol
    if isinstance(face.Surface, Part.Cylinder):
        axis = face.Surface.Axis
        return abs(abs(axis.z) - axis.Length) < tol
    return False


def girdle_line_height(obj, radius, distance=None):
    """The z at which this tier's facet plane crosses the girdle radius —
    where the facet lands on the girdle line — or None for a 90-degree
    tier, whose vertical plane never crosses it at a single height.

    In the vertical section at the facet's own azimuth, a point at radial
    distance ``radius`` on the plane ``n·x = d`` satisfies
    ``sin(theta)*radius + s*cos(theta)*z = d`` with ``s = +1`` crown /
    ``-1`` pavilion, so::

        z = (d - radius * sin(theta)) / (s * cos(theta))

    This reads as a *height*: a pavilion tier's value is how far below the
    girdle plane the facet meets the girdle line, a crown tier's how far
    above. The stored ``Distance`` property is untouched — it remains the
    DESIGN.md section 2.1 plane distance that .ASC interchange, ownership
    matching and the reports all speak.
    """
    theta = math.radians(obj.Angle.Value)
    cos_t = math.cos(theta)
    if abs(cos_t) < 1e-12:
        return None                    # vertical plane: no single height
    if distance is None:
        distance = obj.Distance.Value
    sign = gemmath.side_sign(obj.WorkingSide)
    return (distance - radius * math.sin(theta)) / (sign * cos_t)


def distance_for_girdle_height(obj, radius, height):
    """The plane distance that puts this tier's facet at ``height`` on the
    girdle line — the inverse of :func:`girdle_line_height`.

    Returns None for a 90-degree tier (any height gives the same vertical
    plane, so the panel keeps editing the radial distance there).
    """
    theta = math.radians(obj.Angle.Value)
    cos_t = math.cos(theta)
    if abs(cos_t) < 1e-12:
        return None
    sign = gemmath.side_sign(obj.WorkingSide)
    return radius * math.sin(theta) + sign * cos_t * float(height)


def girdle_metrics(shape, rho_tol=None):
    """``(radius, z_low, z_high)`` of the solid's widest band about the
    gem axis — its girdle — or None when there is nothing to measure.

    **Why this is not the z = 0 plane.** The origin is where the *stock*
    was centred when it was created, and it deliberately stays put as
    tiers are cut: facet planes are origin-referenced (``n·x = d``), and
    moving the solid would break the plane math, .ASC interchange and
    the dop-transfer mirror. The consequence is that after a few cuts
    z = 0 has no particular relation to the stone in front of the user,
    so "is this element on the crown or the pavilion?" must be answered
    against the geometry as it actually is. The gemological definition
    is the measurable one: the girdle is where the stone is widest.

    The band is the z-extent of the boundary points whose distance from
    the gem axis is within ``rho_tol`` of the maximum. It has real
    thickness (a girdle band, or a whole raw cylinder wall — where it
    spans the stone, the rough simply has no crown/pavilion
    differentiation yet and callers should stay permissive). Measured
    over the discretized boundary, so curved rough is handled.

    ``radius`` is the girdle's own radius, i.e. half the girdle width:
    the natural size for anything that must be drawn "as wide as the
    stone" (the panel's out-of-bounds cut plane).
    """
    polylines = _boundary_polylines(shape)
    points = [p for line in polylines for p in line]
    if not points:
        return None
    rhos = [math.hypot(p.x, p.y) for p in points]
    rho_max = max(rhos)
    if rho_max <= 0.0:
        return None
    if rho_tol is None:
        # Tight: discretize() puts sample points exactly on the curve,
        # so the rim's rho values are exact. The slack only absorbs
        # float noise across a faceted girdle's corner vertices.
        rho_tol = max(1e-7, 1e-4 * rho_max)
    band = [p.z for p, rho in zip(points, rhos) if rho >= rho_max - rho_tol]
    return rho_max, min(band), max(band)


def girdle_band(shape, rho_tol=None):
    """``(z_low, z_high)`` of the girdle band — :func:`girdle_metrics`
    without the radius. See that function for the full rationale."""
    metrics = girdle_metrics(shape, rho_tol)
    return None if metrics is None else metrics[1:]


def first_pattern_indices(gem, exclude=None):
    """The index array of the gem's first tier that has a non-empty
    pattern (skipping ``exclude``, the tier being edited): the pattern a
    girdle naturally follows. [] when no earlier tier has one."""
    for feature in gem_feature.pipeline_features(gem):
        if feature is exclude or not gem_feature.is_tier(feature):
            continue
        indices = list(feature.Indices)
        if indices:
            return indices
    return []


def girdle_pattern_indices(obj):
    """The index pattern a girdle-auto cut follows: the first earlier
    tier's pattern when one exists (the mains), else this tier's own
    current indices — the only sensible source on bare stock, where the
    girdle is the first tier cut."""
    gem = gem_feature.find_gem(obj)
    earlier = first_pattern_indices(gem, exclude=obj) if gem else []
    return earlier or list(obj.Indices)


def flip_gem(gem):
    """Mirror the whole stone through the girdle plane: dop transfer as a
    geometry fix.

    For every tier the WorkingSide toggles — exactly the n_z sign flip of
    the facet-plane math — while the tier's *plane distance* is preserved
    via the same deferred-distance mechanism ``make_tier(distance=...)``
    uses, so each mirrored plane is exact even where the reference
    boundary differs between the sides mid-pipeline. This is the rescue
    for "cut a pavilion tier set while Crown was selected": the stone is
    effectively upside down, and flipping the z axis puts it right.
    Returns the number of tiers flipped; the caller recomputes.
    """
    tiers = [f for f in gem_feature.pipeline_features(gem)
             if gem_feature.is_tier(f)]
    for tier in tiers:
        distance = tier.Distance.Value
        tier.WorkingSide = ("Crown" if tier.WorkingSide == "Pavilion"
                            else "Pavilion")
        # Preserve the exact plane distance across the side flip: the
        # first execute after this derives CutDepth against the reference
        # actually in force for the mirrored pipeline.
        tier.Proxy._pending_distance = distance
        tier.touch()
    gem.ActiveSide = ("Crown" if gem.ActiveSide == "Pavilion"
                      else "Pavilion")
    return len(tiers)


def effective_planes(obj):
    """The analytic facet planes ((nx, ny, nz), d) this tier defines, one per
    index in its list (an empty list means one single axial facet)."""
    gear = effective_gear(obj)
    handedness = gem_feature.gem_handedness(gem_feature.find_gem(obj))
    angle = obj.Angle.Value
    distance = obj.Distance.Value
    indices = list(obj.Indices) or [0]
    return [(gemmath.facet_normal(angle, gear, index, obj.WorkingSide,
                                  obj.IndexOffset, handedness), distance)
            for index in indices]


class TierProxy:
    """Proxy for the FacetTier feature."""

    Type = "Lapidary::FacetTier"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        # -- DESIGN.md section 3 property schema v1 --------------------------
        if not hasattr(obj, "Angle"):
            obj.addProperty("App::PropertyAngle", "Angle", "Facet Tier",
                            "Cutting angle: 0 deg = table (perpendicular to "
                            "the gem axis), 90 deg = girdle (parallel)")
        if not hasattr(obj, "CutDepth"):
            obj.addProperty("App::PropertyDistance", "CutDepth", "Facet Tier",
                            "Cut depth, measured inward from the boundary of "
                            "the solid this tier cuts (its longest remaining "
                            "radius about the gem axis); 0 just grazes what "
                            "is left of the stone")
        if not hasattr(obj, "Distance"):
            obj.addProperty("App::PropertyDistance", "Distance", "Facet Tier",
                            "Perpendicular distance from the origin to the "
                            "facet plane, along the facet normal. "
                            "Interchangeable with CutDepth: editing either "
                            "rederives the other (Distance = reference - "
                            "CutDepth)")
        obj.setEditorMode("Distance", 0)  # editable since schema v3
        if not hasattr(obj, "Indices"):
            obj.addProperty("App::PropertyIntegerList", "Indices",
                            "Facet Tier",
                            "Index-gear tooth numbers; empty = one single "
                            "axial facet (the table)")
        if not hasattr(obj, "WorkingSide"):
            obj.addProperty("App::PropertyEnumeration", "WorkingSide",
                            "Facet Tier", "Crown or Pavilion "
                            "(dop transfer = the sign of the normal's z)")
            obj.WorkingSide = gem_feature.SIDES
        if not hasattr(obj, "IndexGear"):
            obj.addProperty("App::PropertyInteger", "IndexGear", "Facet Tier",
                            "Index gear for this tier; 0 = inherit from Gem")
            obj.IndexGear = 0
        if not hasattr(obj, "IndexOffset"):
            obj.addProperty("App::PropertyFloat", "IndexOffset", "Facet Tier",
                            "Cheater: signed fractional index offset")
        if not hasattr(obj, "TierName"):
            obj.addProperty("App::PropertyString", "TierName", "Facet Tier",
                            "Tier name, e.g. 'P1 mains', 'Girdle', 'Table'")
        if not hasattr(obj, "SchemaVersion"):
            obj.addProperty("App::PropertyInteger", "SchemaVersion",
                            "Facet Tier",
                            "Property schema version (for migration)")
            obj.SchemaVersion = TIER_SCHEMA_VERSION
            obj.setPropertyStatus("SchemaVersion", "Hidden")
        # -- pipeline wiring and state ---------------------------------------
        if not hasattr(obj, "BaseFeature"):
            obj.addProperty("App::PropertyLink", "BaseFeature", "Pipeline",
                            "Previous solid in the pipeline (managed by the "
                            "Gem; reordering the tree rewires this)")
            obj.setEditorMode("BaseFeature", 1)  # read-only in the editor
        if not hasattr(obj, "Suppressed"):
            obj.addProperty("App::PropertyBool", "Suppressed", "Pipeline",
                            "Suppress this feature: pass the previous solid "
                            "through unchanged (distinct from view "
                            "visibility)")
        if not hasattr(obj, "TierState"):
            obj.addProperty("App::PropertyString", "TierState", "Pipeline",
                            "Result of the last recompute (OK / Warning / "
                            "Error)")
            obj.setEditorMode("TierState", 1)
        # -- face-ownership record (see module docstring) --------------------
        if not hasattr(obj, "CutNormals"):
            obj.addProperty("App::PropertyVectorList", "CutNormals",
                            "Pipeline", "Exact plane normals of the cuts "
                            "actually performed (face-ownership record)")
            obj.setPropertyStatus("CutNormals", "Hidden")
        if not hasattr(obj, "CutDistances"):
            obj.addProperty("App::PropertyFloatList", "CutDistances",
                            "Pipeline", "Exact plane distances of the cuts "
                            "actually performed (face-ownership record)")
            obj.setPropertyStatus("CutDistances", "Hidden")

    def onDocumentRestored(self, obj):
        # Schema migrations. v1 -> v2/v3: CutDepth did not exist; v2 -> v3:
        # CutDepth existed but was measured from the *stock's* boundary. In
        # both cases the invariant is the stored plane Distance — rederiving
        # CutDepth against the reference now in force (the base solid's
        # boundary, whose restored shape is available here) keeps every facet
        # plane exactly where the document saved it.
        self._add_properties(obj)
        if getattr(obj, "SchemaVersion", 1) < TIER_SCHEMA_VERSION:
            try:
                obj.CutDepth = reference_distance(obj) - obj.Distance.Value
            except Exception as err:
                FreeCAD.Console.PrintWarning(
                    "%s: could not rederive CutDepth from Distance (%s); "
                    "leaving it as saved\n" % (obj.Label, err))
            obj.SchemaVersion = TIER_SCHEMA_VERSION
        obj.setEditorMode("Distance", 0)  # editable since schema v3

    # -- interchangeable depth/distance input --------------------------------

    def onChanged(self, obj, prop):
        """Editing Distance rederives CutDepth (and vice versa via execute).

        CutDepth stays the canonical *driving* parameter — a Distance edit is
        converted immediately, so the next recompute reproduces exactly the
        distance the user typed (same reference both times). The ``_syncing``
        flag stops the loop when execute writes Distance itself, and edits
        during document restore are ignored (restore is not user input).
        """
        if prop != "Distance" or getattr(self, "_syncing", False):
            return
        if hasattr(obj, "State") and "Restore" in obj.State:
            return
        if not hasattr(obj, "CutDepth"):
            return                     # property set arriving out of order
        try:
            depth = reference_distance(obj) - obj.Distance.Value
        except Exception:
            return                     # no gem/base yet (e.g. mid-creation)
        if abs(depth - obj.CutDepth.Value) > 1e-12:
            obj.CutDepth = depth       # touches the feature -> recompute

    # -- recompute ----------------------------------------------------------

    def _fail(self, obj, base_shape, message):
        """Recoverable error state: keep the upstream shape displayed, then
        block this tier's recompute by raising."""
        obj.Shape = base_shape
        obj.CutNormals = []
        obj.CutDistances = []
        obj.TierState = "Error: " + message
        raise RuntimeError("%s: %s" % (obj.Label, message))

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise RuntimeError(
                "%s has no base feature; is it inside a Gem, after a Stock?"
                % obj.Label)
        base_shape = base.Shape
        if base_shape.isNull() or not base_shape.Solids:
            raise RuntimeError("%s: base feature %s has no solid"
                               % (obj.Label, base.Label))

        if obj.Suppressed:
            obj.Shape = base_shape
            obj.CutNormals = []
            obj.CutDistances = []
            obj.TierState = "Suppressed"
            return

        try:
            reference = reference_distance(obj)
        except RuntimeError as err:
            self._fail(obj, base_shape, str(err))
        pending = getattr(self, "_pending_distance", None)
        if pending is not None:
            # make_tier(distance=...) requested an exact plane distance
            # before the base solid existed; honour it against the reference
            # that is actually in force now, then behave like a normal
            # depth-driven tier.
            self._pending_distance = None
            obj.CutDepth = reference - float(pending)
        distance = reference - obj.CutDepth.Value
        if distance <= 0.0:
            self._fail(obj, base_shape,
                       "cut depth %g reaches past the gem axis (reference "
                       "boundary %g); the plane would annihilate the stone"
                       % (obj.CutDepth.Value, reference))
        self._syncing = True           # our own write, not a user edit
        try:
            obj.Distance = distance
        finally:
            self._syncing = False

        gear = effective_gear(obj)
        handedness = gem_feature.gem_handedness(gem_feature.find_gem(obj))
        indices = list(obj.Indices) or [0]

        base_volume = base_shape.Volume
        bbox = base_shape.BoundBox
        shape = base_shape
        normals = []
        distances = []
        missed = []
        noop_threshold = NOOP_REL_TOL * base_volume
        for index in indices:
            normal = gemmath.facet_normal(
                obj.Angle.Value, gear, index, obj.WorkingSide,
                obj.IndexOffset, handedness)
            box = halfspace.cutting_box(normal, distance, bbox)
            result = shape.cut(box)
            removed = shape.Volume - result.Volume
            if removed <= noop_threshold or not result.Solids:
                # Either the plane genuinely misses the solid, or OpenCascade
                # cut failed *silently*, returning its input (observed on
                # real designs; see docs/dev-notes.md). Arbitrate with the
                # mathematically identical common()-based formulation before
                # classifying it as a no-op.
                alt = halfspace.retain_halfspace(shape, normal, distance)
                alt_removed = shape.Volume - alt.Volume
                if alt.Solids and alt_removed > max(removed, noop_threshold):
                    result = alt
                    removed = alt_removed
            if not result.Solids or result.Volume < ANNIHILATION_REL_TOL * base_volume:
                self._fail(obj, base_shape,
                           "cut at index %s annihilates the solid "
                           "(angle %.4g deg, distance %.4g)"
                           % (index, obj.Angle.Value, distance))
            if removed <= noop_threshold:
                # No-op cut: plane misses the solid. Not an error and not a
                # warning (misses are routine during live preview); the fact
                # is recorded quietly in TierState for the panel's status
                # line, with no console message and no tree marker.
                missed.append(index)
            else:
                shape = result
            normals.append(FreeCAD.Vector(*normal))
            distances.append(distance)

        obj.Shape = shape
        obj.CutNormals = normals
        obj.CutDistances = distances
        if missed:
            obj.TierState = "OK (%d of %d cuts missed the solid)" % (
                len(missed), len(indices))
        else:
            obj.TierState = "OK"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _attach_view_provider(obj):
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        from freecad.lapidary.faceting.viewproviders import (
            ViewProviderFacetTier)
        ViewProviderFacetTier(obj.ViewObject)


def make_tier(gem, angle, distance=None, indices=(), side=None, tier_name="",
              index_gear=0, index_offset=0.0, label=None, depth=None):
    """Append a FacetTier to ``gem``'s pipeline and return it.

    The plane position is given either as ``distance`` (canonical plane
    distance from the origin, DESIGN.md section 2.1 — used by scripts and
    the .ASC importer) or as ``depth`` (the user-facing cut depth, measured
    inward from the base solid's reference boundary, schema v3). Give
    exactly one.

    A requested ``distance`` is honoured *exactly* even though the depth
    reference depends on the base solid, which may not be computed yet when
    tiers are created in a batch (the .ASC importer adds every tier before
    the first recompute): the distance is parked on the proxy and converted
    to a CutDepth on the tier's first execute, against the reference then in
    force. Until that recompute the tier's CutDepth reads 0.

    ``side`` defaults to the Gem's ActiveSide (which follows the side of the
    last tier committed through the FacetTier panel). The Gem's group-change
    handler wires BaseFeature.
    """
    if (distance is None) == (depth is None):
        raise ValueError("give exactly one of distance= or depth=")
    doc = gem.Document
    obj = doc.addObject("Part::FeaturePython", "FacetTier")
    TierProxy(obj)
    obj.Angle = float(angle)
    obj.Indices = [int(i) for i in indices]
    obj.WorkingSide = side if side is not None else gem.ActiveSide
    obj.IndexGear = int(index_gear)
    obj.IndexOffset = float(index_offset)
    obj.TierName = tier_name
    obj.Label = label or (tier_name or "FacetTier")
    _attach_view_provider(obj)
    # addObject fires Gem.onChanged("Group") -> resequence, which wires
    # BaseFeature and restores tip-only visibility (standard tip semantics;
    # feature suppression is the separate Suppressed property).
    gem.addObject(obj)
    if depth is None:
        # Exact plane distance requested: defer the depth derivation to the
        # first execute, when the base solid (and so the true reference) is
        # known — see the docstring.
        obj.Proxy._pending_distance = float(distance)
        obj.CutDepth = 0.0
        obj.touch()
    else:
        obj.CutDepth = float(depth)
    return obj
