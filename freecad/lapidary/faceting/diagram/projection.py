# SPDX-License-Identifier: LGPL-2.1-or-later
"""Project a Gem's final B-Rep into the plain-data diagram model (DESIGN.md
section 8).

This is the only half of the diagram pipeline that touches FreeCAD. It reads
the finished solid, attributes each planar face to its tier *and gear tooth*
through the Phase 1 ownership mechanism
(:func:`~freecad.lapidary.faceting.ownership.classify_faces_with_index`), and
emits :mod:`~freecad.lapidary.faceting.diagram.model` structures. It imports
no GUI module and runs headless.

Presentation conventions (all verified against real GemCad printouts — see
``DIAGRAM_NOTES.md`` next to this file):

* Both round views use one projection, ``u = +y``, ``v = -x``, which puts
  tooth 0 at the bottom with index numbers increasing counter-clockwise. That
  single mapping *is* GemCad's mirrored pavilion presentation: mirroring a
  view from -Z gives back the view from +Z.
* Hidden lines are handled by back-face culling on the sign of the facet
  normal's z: the crown view draws only crown facets, the pavilion view only
  pavilion facets, both fully opaque. Girdle facets (theta = 90 deg) project
  to segments and are drawn as the stone's outline.
* The elevation is the opposite: a full see-through wireframe.
"""

import math

import Part

from freecad.lapidary.core import gemmath
from freecad.lapidary.faceting import gem_feature, ownership, reports
from freecad.lapidary.faceting.diagram import model
from freecad.lapidary.faceting.diagram.model import (
    CROWN, GIRDLE, PAVILION, Diagram, Facet, IndexRing, Label, Segment, View)

__all__ = ["build_diagram", "face_polygon", "CROWN_VIEW", "PAVILION_VIEW",
           "ELEVATION_VIEW"]

CROWN_VIEW = "crown"
PAVILION_VIEW = "pavilion"
ELEVATION_VIEW = "elevation"

#: A facet counts as a girdle facet when its normal is horizontal to within
#: this tolerance. Facet normals are exact (DESIGN.md section 2.1), so a
#: 90 deg tier lands at |n_z| ~ 1e-16 and nothing else comes close.
GIRDLE_NORMAL_TOL = 1e-9

#: Round-view projection: u to the right, v up (DIAGRAM_NOTES.md).
ROUND_BASIS = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
#: Elevation ("End" view in GemCad's names): gem axis up, horizontal axis
#: shared with the round views so the panels line up.
ELEVATION_BASIS = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

#: Inner radius of the index tick ring, as a multiple of the stone's
#: projected radius: just clear of the outline. Everything further out (tick
#: length, number radius, the outward nudge on girdle labels) is measured in
#: *page* millimetres by the SVG writer, so those margins stay constant
#: whatever the stone's size.
RING_RADIUS_FACTOR = 1.02


# ---------------------------------------------------------------------------
# Geometry extraction
# ---------------------------------------------------------------------------

def _edge_points(edge, deflection):
    """Points along an edge, dense enough for a curved one, two for a line."""
    if isinstance(edge.Curve, Part.Line):
        return [edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
    count = max(2, int(math.ceil(edge.Length / deflection)) + 1)
    return list(edge.discretize(Number=count))


def face_polygon(face, deflection=0.05):
    """The face's outer boundary as an ordered list of 3D points.

    Edges are chained by *proximity* rather than by trusting each edge's own
    orientation flag, which is what makes this work for both the analytic
    planar facets and any curved remnant of the rough. ``OrderedEdges``
    returns the edges in traversal order but each edge keeps its own vertex
    direction, and — the subtle part — that includes the **first** edge: if
    its stored direction runs backwards, chaining the rest onto its tail
    silently produces a self-crossing polygon with the wrong centroid and
    half the area. So the first edge is oriented against the second before
    anything is chained onto it.
    """
    chunks = [chunk for chunk in
              (_edge_points(edge, deflection)
               for edge in face.OuterWire.OrderedEdges) if chunk]
    if not chunks:
        return []

    if len(chunks) > 1:
        head, following = chunks[0], chunks[1]
        joints = (following[0], following[-1])
        start_gap = min((head[0] - p).Length for p in joints)
        end_gap = min((head[-1] - p).Length for p in joints)
        if start_gap < end_gap:
            chunks[0] = list(reversed(head))

    points = list(chunks[0])
    for chunk in chunks[1:]:
        last = points[-1]
        if (chunk[-1] - last).Length < (chunk[0] - last).Length:
            chunk = list(reversed(chunk))
        points.extend(chunk[1:])  # drop the duplicated shared vertex

    # Drop the closing vertex if the wire came back to its start.
    if len(points) > 1 and (points[-1] - points[0]).Length < 1e-9:
        points.pop()
    return points


def _project(point, basis):
    """World point -> view-space (u, v)."""
    basis_u, basis_v = basis
    return (point.x * basis_u[0] + point.y * basis_u[1] + point.z * basis_u[2],
            point.x * basis_v[0] + point.y * basis_v[1] + point.z * basis_v[2])


def _project_all(points, basis):
    return [_project(p, basis) for p in points]


def _face_side(face):
    """Geometric side of a face: CROWN / PAVILION / GIRDLE.

    Non-planar faces (a remnant of a cylindrical rough) are girdle-band
    geometry by construction — their axis is the gem axis — so they join the
    outline.
    """
    plane = ownership.face_plane(face)
    if plane is None:
        return GIRDLE
    normal = plane[0]
    if normal.z > GIRDLE_NORMAL_TOL:
        return CROWN
    if normal.z < -GIRDLE_NORMAL_TOL:
        return PAVILION
    return GIRDLE


def _dedupe_segments(segments, tol=1e-7):
    """Drop duplicate wireframe segments (every edge is shared by two faces)."""
    seen = set()
    unique = []
    quantum = 1.0 / tol
    for segment in segments:
        a = (round(segment.a[0] * quantum), round(segment.a[1] * quantum))
        b = (round(segment.b[0] * quantum), round(segment.b[1] * quantum))
        key = (a, b) if a <= b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        unique.append(segment)
    return unique


def _polygon_segments(points):
    return [Segment(points[i], points[(i + 1) % len(points)])
            for i in range(len(points))]


# ---------------------------------------------------------------------------
# Tier bookkeeping
# ---------------------------------------------------------------------------

def _tier_side(row):
    """Geometric group of a tier row: a 90 deg tier is a *girdle* tier
    whichever working side it nominally carries (DIAGRAM_NOTES.md)."""
    if abs(row["angle"] - 90.0) < 1e-9:
        return GIRDLE
    return CROWN if row["side"] == "Crown" else PAVILION


def _tier_rows(gem):
    """Diagram tier rows, keyed by the tier object's document name."""
    rows = []
    keys = {}
    tiers = [f for f in gem_feature.pipeline_features(gem)
             if gem_feature.is_tier(f)]
    for tier, row in zip(tiers, reports.cutting_sheet_rows(gem)):
        keys[tier.Name] = row
        rows.append(model.TierRow(
            key=tier.Name,
            name=row["name"],
            side=_tier_side(row),
            working_side=row["side"],
            angle=row["angle"],
            distance=row["distance"],
            depth=row["depth"],
            indices=list(row["indices"]),
            indices_text=row["indices_text"],
            gear=row["gear"],
            index_offset=row["index_offset"],
            facet_count=row["facet_count"],
            suppressed=row["suppressed"],
        ))
    return rows


def short_name(name):
    """The tier's in-view label: its first word.

    GemCad's own names are already short (``C1``, ``P2``, ``G1``), and so are
    the ``n``-token names of imported .ASC designs. Hand-built tiers tend to
    carry descriptive names like ``"C1 breaks"``, which do not fit inside a
    break facet — the descriptive form still appears in the tier table.
    """
    return name.split()[0] if name else ""


def _label_text(row, style):
    name = short_name(row.name)
    if style is model.LabelStyle.NAME or not name:
        return name
    return "%s\n%.2f°" % (name, row.angle)


def _pick_label_facet(facets, gear):
    """The facet GemCad would label: the one with the smallest index, counting
    tooth N as tooth 0 (manual p. 35; the SRB printout labels its ``96-12-24``
    tier at the bottom of the view, i.e. at tooth 96 == 0)."""
    candidates = [f for f in facets if f.index is not None]
    if not candidates:
        return facets[0] if facets else None
    return min(candidates, key=lambda f: f.index % gear if gear else f.index)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _index_ring(gem, gear, radius):
    """Tick ring for a round view: a tick per tooth, numbers every gear/16.

    GemCad prints numbers only; DESIGN.md section 8 asks for a tick ring, so
    both are emitted and the SVG writer draws the ticks lightly.
    """
    if gear < 1:
        return None
    handedness = gem_feature.gem_handedness(gem)
    step = max(1, int(round(gear / 16.0)))
    ticks, labels = [], []
    for index in range(1, gear + 1):
        angle = model.ring_angle_deg(
            gemmath.azimuth_deg(gear, index, 0.0, handedness))
        ticks.append((index, angle))
        if index % step == 0 or index == gear:
            # Tooth N is the ID position; GemCad prints it in angle brackets.
            text = "<%d>" % gear if index == gear else "%d" % index
            labels.append((index, angle, text))
    return IndexRing(gear=gear, radius=radius, ticks=ticks, labels=labels,
                     id_index=gear)


def _round_view(key, title, side, faces_by_side, outline_segments, rows_by_key,
                gem, gear, style):
    view = View(key=key, title=title)
    view.facets = list(faces_by_side.get(side, []))
    view.outline = outline_segments

    radius = 0.0
    for point in ([p for facet in view.facets for p in facet.points]
                  + [p for s in outline_segments for p in (s.a, s.b)]):
        radius = max(radius, math.hypot(point[0], point[1]))
    if radius <= 0.0:
        radius = 1.0

    # One label per tier drawn in this view, in its smallest-index facet.
    by_tier = {}
    for facet in view.facets:
        by_tier.setdefault(facet.tier_key, []).append(facet)
    for tier_key, facets in by_tier.items():
        row = rows_by_key.get(tier_key)
        if row is None or not row.name:
            continue
        chosen = _pick_label_facet(facets, row.gear)
        if chosen is None:
            continue
        u, v = model.polygon_centroid(chosen.points)
        view.labels.append(Label(_label_text(row, style), u, v, role="tier"))

    view.ring = _index_ring(gem, gear, radius * RING_RADIUS_FACTOR)
    return view


def _girdle_labels(girdle_facets, rows_by_key, radius, style):
    """Girdle-tier labels, anchored on the ring radius at their facet's
    azimuth. The renderer nudges them further out by a fixed page margin, so
    they end up outside the outline as GemCad prints them (manual p. 12)."""
    labels = []
    by_tier = {}
    for facet in girdle_facets:
        by_tier.setdefault(facet.tier_key, []).append(facet)
    for tier_key, facets in by_tier.items():
        row = rows_by_key.get(tier_key)
        if row is None or not row.name:
            continue
        chosen = _pick_label_facet(facets, row.gear)
        if chosen is None or not chosen.points:
            continue
        u, v = model.polygon_centroid(chosen.points)
        length = math.hypot(u, v)
        if length < 1e-9:
            continue
        scale = radius / length
        labels.append(Label(_label_text(row, style), u * scale, v * scale,
                            role="girdle"))
    return labels


def _elevation_view(shape, deflection):
    """GemCad's "End" view: a full see-through wireframe, gem axis up."""
    view = View(key=ELEVATION_VIEW, title="Side elevation")
    segments = []
    for face in shape.Faces:
        points = _project_all(face_polygon(face, deflection), ELEVATION_BASIS)
        if len(points) >= 2:
            segments.extend(_polygon_segments(points))
    view.wireframe = _dedupe_segments(segments)
    return view


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_diagram(gem, include_elevation=True,
                  label_style=model.LabelStyle.NAME):
    """Build the :class:`~...diagram.model.Diagram` for a Gem.

    Returns None when the gem has no finished solid yet.
    """
    from freecad.lapidary.faceting.diagram import stats

    shape = gem_feature.final_shape(gem)
    if shape is None:
        return None

    diagonal = shape.BoundBox.DiagonalLength or 1.0
    deflection = diagonal / 400.0

    rows = _tier_rows(gem)
    rows_by_key = {row.key: row for row in rows}

    faces_by_side = {CROWN: [], PAVILION: [], GIRDLE: []}
    owners = ownership.classify_faces_with_index(gem)
    for face, (owner, index) in zip(shape.Faces, owners):
        side = _face_side(face)
        tier_key = owner.Name if gem_feature.is_tier(owner) else ""
        points = _project_all(face_polygon(face, deflection), ROUND_BASIS)
        if len(points) < 2:
            continue
        faces_by_side[side].append(
            Facet(points=points, side=side, tier_key=tier_key, index=index))

    # Girdle facets project to segments in a round view: they *are* the
    # stone's outline, so they are drawn as the outline path rather than as
    # degenerate polygons (DIAGRAM_NOTES.md).
    outline = _dedupe_segments(
        [segment for facet in faces_by_side[GIRDLE]
         for segment in _polygon_segments(facet.points)])

    gear = gem.IndexGear
    crown = _round_view(CROWN_VIEW, "Crown", CROWN, faces_by_side, outline,
                        rows_by_key, gem, gear, label_style)
    pavilion = _round_view(PAVILION_VIEW, "Pavilion", PAVILION, faces_by_side,
                           outline, rows_by_key, gem, gear, label_style)
    pavilion.labels.extend(_girdle_labels(
        faces_by_side[GIRDLE], rows_by_key,
        pavilion.ring.radius if pavilion.ring else 1.0, label_style))

    views = [crown, pavilion]
    if include_elevation:
        views.append(_elevation_view(shape, deflection))

    report = reports.compute_report(shape)
    counts = stats.count_facets(faces_by_side, rows_by_key)
    diagram = Diagram(
        title=gem.DesignName or gem.Label,
        subtitle=stats.heading_lines(gem),
        views=views,
        blocks=stats.text_blocks(gem, report, counts),
        tiers=rows,
        footnotes=list(getattr(gem, "AscFootnotes", []) or []),
        label_style=label_style,
    )
    return diagram
