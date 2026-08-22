# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plain-data model of a faceting diagram (DESIGN.md section 8).

This module is **pure Python**: no FreeCAD, no Part, no Qt. It defines the
handover format between the two halves of the diagram pipeline —
:mod:`~freecad.lapidary.faceting.diagram.projection`, which reads a Gem's
B-Rep and fills these structures, and
:mod:`~freecad.lapidary.faceting.diagram.svg`, which turns them into SVG.
Keeping the seam here is what lets the whole rendering half be exercised by
plain pytest without FreeCAD installed.

All view geometry is expressed in **view space**: ``u`` to the right, ``v``
**up**, in millimetres, with the gem's origin at ``(0, 0)``. The SVG writer
owns the (single) flip to y-down device coordinates. The mapping used for the
two round views is, per ``DIAGRAM_NOTES.md``::

    u = +y_world        # tooth 0 at the bottom of the view,
    v = -x_world        # index numbers increasing counter-clockwise

which is the *same* projection for crown and pavilion — GemCad's pavilion
("Bottom") view is mirrored, and a mirrored view from -Z is identical to the
view from +Z. See DIAGRAM_NOTES.md for the printout evidence.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "CROWN", "PAVILION", "GIRDLE",
    "LabelStyle", "Facet", "Segment", "Label", "IndexRing", "View",
    "TierRow", "TextBlock", "Diagram",
    "polygon_area", "polygon_centroid", "bounds_of",
]

#: Geometric side of a facet, from the sign of its normal's z component.
#: Note this is a *geometric* classification, not the tier's WorkingSide: a
#: 90 deg tier is a girdle tier whichever side its .ASC angle sign claims
#: (GemCad's Facet Data block counts it that way too — DIAGRAM_NOTES.md).
CROWN = "Crown"
PAVILION = "Pavilion"
GIRDLE = "Girdle"


class LabelStyle(Enum):
    """How much a tier's in-view label says.

    ``NAME`` is the default and reproduces GemCad's printout exactly: the
    tier's short name only (``C1``, ``P2``, ``T``). DESIGN.md section 8 asks
    for "tier labels with angle/index annotations", and that is carried by the
    tier table, whose rows are keyed by these same short names — putting the
    angle inside the facet as well makes the small break facets of a real
    design illegible, which would defeat the same section's overriding
    requirement to match GemCad's presentation.

    ``NAME_ANGLE`` is available for designs with room for it; it sets the
    angle on a second line under the name.
    """

    NAME = "name"
    NAME_ANGLE = "name+angle"


@dataclass
class Facet:
    """One projected facet polygon, in view space."""

    points: list                 # [(u, v), ...] closed implicitly
    side: str = CROWN            # CROWN / PAVILION / GIRDLE
    tier_key: str = ""           # matches TierRow.key ("" = owned by the stock)
    index: int = None            # gear tooth this facet was cut at, if known


@dataclass
class Segment:
    """A straight line in view space."""

    a: tuple
    b: tuple


@dataclass
class Label:
    """A text label placed in view space.

    ``text`` may contain newlines; the SVG writer stacks the lines. ``role``
    ``girdle`` means "push me radially outward clear of the outline" — GemCad
    labels girdle facets outside the stone (DIAGRAM_NOTES.md), and only the
    renderer knows the page scale needed to do that by a fixed margin.
    """

    text: str
    u: float
    v: float
    anchor: str = "middle"       # SVG text-anchor
    role: str = "tier"           # tier / girdle / note

    @property
    def lines(self):
        return self.text.split("\n") if self.text else []


@dataclass
class IndexRing:
    """The index-gear tick ring drawn around a round view.

    ``ticks`` are (index, screen-angle-in-degrees) for every tooth;
    ``labels`` the subset that gets a printed number. ``id_index`` is the tooth
    whose number GemCad prints in angle brackets (tooth N, equivalently 0).
    """

    gear: int
    radius: float
    ticks: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    id_index: int = 0


@dataclass
class View:
    """One panel of the diagram."""

    key: str                     # "crown" / "pavilion" / "elevation"
    title: str = ""
    facets: list = field(default_factory=list)
    outline: list = field(default_factory=list)    # [Segment] girdle silhouette
    wireframe: list = field(default_factory=list)  # [Segment] elevation only
    labels: list = field(default_factory=list)
    ring: IndexRing = None

    def bounds(self):
        """(umin, vmin, umax, vmax) over everything drawn, ring included."""
        points = []
        for facet in self.facets:
            points.extend(facet.points)
        for segment in list(self.outline) + list(self.wireframe):
            points.append(segment.a)
            points.append(segment.b)
        for label in self.labels:
            points.append((label.u, label.v))
        if self.ring is not None:
            r = self.ring.radius
            points.extend([(-r, -r), (r, r)])
        return bounds_of(points)


@dataclass
class TierRow:
    """One row of the cutting instructions / tier table."""

    key: str
    name: str
    side: str                    # geometric group: CROWN / PAVILION / GIRDLE
    working_side: str            # the tier's WorkingSide property
    angle: float
    distance: float
    depth: float
    indices: list
    indices_text: str
    gear: int
    index_offset: float = 0.0
    facet_count: int = 0
    suppressed: bool = False


@dataclass
class TextBlock:
    """A titled block of label/value rows for the diagram's text column."""

    title: str
    rows: list = field(default_factory=list)   # [(label, value), ...]


@dataclass
class Diagram:
    """Everything needed to draw one faceting diagram."""

    title: str = ""
    subtitle: list = field(default_factory=list)   # heading lines under title
    views: list = field(default_factory=list)
    blocks: list = field(default_factory=list)     # [TextBlock]
    tiers: list = field(default_factory=list)      # [TierRow], pipeline order
    footnotes: list = field(default_factory=list)
    label_style: LabelStyle = LabelStyle.NAME

    def view(self, key):
        for view in self.views:
            if view.key == key:
                return view
        return None


# ---------------------------------------------------------------------------
# Small pure-geometry helpers (used by projection and by the SVG writer)
# ---------------------------------------------------------------------------

def polygon_area(points):
    """Signed area of a polygon (positive when counter-clockwise)."""
    total = 0.0
    count = len(points)
    for i in range(count):
        u0, v0 = points[i]
        u1, v1 = points[(i + 1) % count]
        total += u0 * v1 - u1 * v0
    return total / 2.0


def polygon_centroid(points):
    """Area centroid of a polygon, falling back to the vertex average for
    degenerate (zero-area) input."""
    area = polygon_area(points)
    if abs(area) < 1e-12:
        if not points:
            return (0.0, 0.0)
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))
    cu = cv = 0.0
    count = len(points)
    for i in range(count):
        u0, v0 = points[i]
        u1, v1 = points[(i + 1) % count]
        cross = u0 * v1 - u1 * v0
        cu += (u0 + u1) * cross
        cv += (v0 + v1) * cross
    return (cu / (6.0 * area), cv / (6.0 * area))


def bounds_of(points):
    """(umin, vmin, umax, vmax) of a point list; a unit box when empty."""
    if not points:
        return (-1.0, -1.0, 1.0, 1.0)
    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    return (min(us), min(vs), max(us), max(vs))


def ring_angle_deg(azimuth_deg):
    """Screen angle of a facet azimuth in a round view.

    The round views rotate the world by -90 deg so that tooth 0 lands at the
    bottom of the view (DIAGRAM_NOTES.md); measured counter-clockwise from
    screen-right, a facet at world azimuth ``phi`` is drawn at ``phi - 90``.
    """
    return azimuth_deg - 90.0


def ring_point(radius, angle_deg):
    """View-space point at ``angle_deg`` (counter-clockwise from +u)."""
    radians = math.radians(angle_deg)
    return (radius * math.cos(radians), radius * math.sin(radians))
