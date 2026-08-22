# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render a :class:`~freecad.lapidary.faceting.diagram.model.Diagram` as SVG
(DESIGN.md section 8).

**Pure Python**: no FreeCAD, no Part, no Qt — so the whole rendering half is
testable under plain pytest, and the dock widget's only job is to display the
string this module returns.

The page is laid out like a GemCad printout (``DIAGRAM_NOTES.md``): the design
name across the top, a text column down the left carrying the Facet/Size/
Design data blocks and the cutting instructions, and the drawing panels in a
grid on the right — crown and the elevation on the first row, pavilion below
the crown, which is GemCad's own quadrant arrangement minus its second
elevation.

Units are millimetres throughout: the ``viewBox`` is in mm and the root
``width``/``height`` carry the ``mm`` suffix, so the file prints at true size
and a PDF export needs no scaling.
"""

import math

from freecad.lapidary.faceting.diagram import model
from freecad.lapidary.faceting.diagram.model import CROWN, GIRDLE, PAVILION

__all__ = ["PageStyle", "render_svg", "page_size_mm", "A4_PORTRAIT",
           "LETTER_PORTRAIT"]


class PageStyle:
    """Page geometry and typography, all in millimetres."""

    def __init__(self, width=210.0, height=297.0, margin=10.0,
                 text_width=80.0, gutter=6.0, name="A4"):
        self.name = name
        self.width = width
        self.height = height
        self.margin = margin
        self.text_width = text_width
        self.gutter = gutter
        # Typography
        self.title_size = 6.5
        self.subtitle_size = 2.9
        self.block_title_size = 3.4
        self.row_size = 2.9
        self.group_size = 3.4
        self.tier_label_size = 2.5
        self.index_size = 2.5
        self.footnote_size = 2.5
        self.line_gap = 4.0
        # Strokes
        self.facet_stroke = 0.18
        self.outline_stroke = 0.38
        self.wire_stroke = 0.16
        self.tick_stroke = 0.08
        self.rule_stroke = 0.35
        # Index-ring margins, in page mm measured out from the ring's inner
        # radius: tick length, then the girdle labels, then the numbers.
        self.tick_length = 1.5
        self.girdle_label_offset = 3.0
        self.index_label_offset = 6.4
        # Drawing-panel padding, big enough for the index ring's numbers.
        self.view_pad = 11.0
        # Cutting-instructions column stops, measured from the column's left.
        self.tier_angle_x = 34.0
        self.tier_index_x = 36.5

    @property
    def view_x0(self):
        return self.margin + self.text_width + self.gutter

    @property
    def view_x1(self):
        return self.width - self.margin


A4_PORTRAIT = PageStyle(210.0, 297.0, name="A4")
LETTER_PORTRAIT = PageStyle(215.9, 279.4, name="Letter")

FONT = "Helvetica, Arial, 'DejaVu Sans', sans-serif"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _num(value):
    """Compact fixed-point number (SVG has no use for 17 significant digits)."""
    text = "%.4f" % value
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _text(x, y, content, size, anchor="start", weight="normal", fill="#000"):
    return ('<text x="%s" y="%s" font-size="%s" text-anchor="%s" '
            'font-weight="%s" fill="%s">%s</text>'
            % (_num(x), _num(y), _num(size), anchor, weight, fill,
               _escape(content)))


def _line(x1, y1, x2, y2, stroke, width):
    return ('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" '
            'stroke-width="%s"/>'
            % (_num(x1), _num(y1), _num(x2), _num(y2), stroke, _num(width)))


def _wrap(text, width_mm, font_size):
    """Greedy wrap on the dash separators of an index list.

    Character widths are estimated (0.52 em for this digit-heavy text); the
    SVG writer has no font metrics and does not need exact ones.
    """
    if not text:
        return []
    per_char = 0.52 * font_size
    limit = max(4, int(width_mm / per_char))
    if len(text) <= limit:
        return [text]
    lines, current = [], ""
    for token in text.split("-"):
        candidate = token if not current else current + "-" + token
        if len(candidate) > limit and current:
            lines.append(current + "-")
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# View transform
# ---------------------------------------------------------------------------

class _Cell:
    """Placement of one view: where its cell is and how view space maps in.

    View space has v pointing up; the page has y pointing down. This class is
    the single place that flip happens.
    """

    def __init__(self, view, x, y, size, scale):
        self.view = view
        self.scale = scale
        umin, vmin, umax, vmax = view.bounds()
        self.cx = x + size / 2.0
        self.cy = y + size / 2.0
        self.u0 = (umin + umax) / 2.0
        self.v0 = (vmin + vmax) / 2.0

    def point(self, uv):
        return (self.cx + (uv[0] - self.u0) * self.scale,
                self.cy - (uv[1] - self.v0) * self.scale)

    def path(self, points, close=True):
        parts = []
        for i, uv in enumerate(points):
            x, y = self.point(uv)
            parts.append("%s%s %s" % ("M" if i == 0 else "L", _num(x), _num(y)))
        if close:
            parts.append("Z")
        return " ".join(parts)


def _fit_scale(views, size, style):
    """One scale shared by every panel, so the views stay comparable."""
    available = size - 2.0 * style.view_pad
    scale = None
    for view in views:
        umin, vmin, umax, vmax = view.bounds()
        du = max(umax - umin, 1e-9)
        dv = max(vmax - vmin, 1e-9)
        candidate = min(available / du, available / dv)
        scale = candidate if scale is None else min(scale, candidate)
    return scale or 1.0


def _grid(views, style, top):
    """GemCad's panel arrangement: crown top-left, elevation top-right,
    pavilion below the crown."""
    slots = {"crown": (0, 0), "elevation": (1, 0), "pavilion": (0, 1)}
    keys = [view.key for view in views]
    columns = 2 if "elevation" in keys else 1
    rows = 2
    width = style.view_x1 - style.view_x0
    height = style.height - style.margin - top
    size = min(width / columns, height / rows)
    placed = []
    for view in views:
        column, row = slots.get(view.key, (0, 0))
        x = style.view_x0 + column * size
        y = top + row * size
        placed.append((view, x, y, size))
    return placed, size


# ---------------------------------------------------------------------------
# Panel drawing
# ---------------------------------------------------------------------------

def _draw_facets(cell, style, tier_tint=None):
    """Facet polygons; with the optional optics overlay (Phase 4b), a
    facet whose ``tier_key`` appears in ``tier_tint`` gets that fill
    instead of the plain white base. ``tier_tint=None`` (the default)
    must reproduce the base diagram byte-for-byte."""
    out = []
    tier_tint = tier_tint or {}
    for facet in cell.view.facets:
        if len(facet.points) < 3:
            continue
        fill = tier_tint.get(facet.tier_key, "#fff")
        out.append('<path d="%s" fill="%s" stroke="#000" '
                   'stroke-width="%s" stroke-linejoin="round"/>'
                   % (cell.path(facet.points), fill,
                      _num(style.facet_stroke)))
    return out


def _draw_segments(cell, segments, stroke, width):
    out = []
    for segment in segments:
        x1, y1 = cell.point(segment.a)
        x2, y2 = cell.point(segment.b)
        out.append(_line(x1, y1, x2, y2, stroke, width))
    return out


def _draw_ring(cell, style):
    """Index-gear ring: a light tick per tooth plus GemCad's printed numbers,
    with the ID tooth in angle brackets.

    Tick lengths and the number radius are fixed *page* distances outside the
    ring's inner radius, so they look the same on a 5 mm stone and a 25 mm
    one.
    """
    ring = cell.view.ring
    if ring is None:
        return []
    out = []
    inner = ring.radius
    labelled = {index for index, _angle, _text in ring.labels}
    for index, angle in ring.ticks:
        length = style.tick_length * (1.7 if index in labelled else 1.0)
        x1, y1 = cell.point(model.ring_point(inner, angle))
        x2, y2 = cell.point(model.ring_point(inner + length / cell.scale,
                                             angle))
        out.append(_line(x1, y1, x2, y2, "#777", style.tick_stroke))
    label_radius = inner + style.index_label_offset / cell.scale
    for _index, angle, text in ring.labels:
        x, y = cell.point(model.ring_point(label_radius, angle))
        # Nudge down by a third of the cap height so the number reads as
        # centred on its tick.
        out.append(_text(x, y + style.index_size * 0.35, text,
                         style.index_size, anchor="middle"))
    return out


def _draw_labels(cell, style):
    """Tier labels. Girdle labels are pushed radially clear of the outline by
    a fixed page margin (GemCad prints them outside the stone)."""
    out = []
    origin = cell.point((0.0, 0.0))
    for label in cell.view.labels:
        lines = label.lines
        if not lines:
            continue
        x, y = cell.point((label.u, label.v))
        if label.role == "girdle":
            dx, dy = x - origin[0], y - origin[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                push = style.girdle_label_offset / length
                x += dx * push
                y += dy * push
        size = style.tier_label_size
        # Vertically centre the whole stack on the anchor point.
        top = y - (len(lines) - 1) * size * 0.55 + size * 0.35
        for offset, line in enumerate(lines):
            out.append(_text(x, top + offset * size * 1.1, line, size,
                             anchor=label.anchor))
    return out


def _draw_view(cell, style, tier_tint=None):
    out = ['<g id="view-%s">' % _escape(cell.view.key)]
    if cell.view.wireframe:
        out.extend(_draw_segments(cell, cell.view.wireframe, "#000",
                                  style.wire_stroke))
    out.extend(_draw_facets(cell, style, tier_tint))
    if cell.view.outline:
        out.extend(_draw_segments(cell, cell.view.outline, "#000",
                                  style.outline_stroke))
    out.extend(_draw_ring(cell, style))
    out.extend(_draw_labels(cell, style))
    out.append("</g>")
    return out


# ---------------------------------------------------------------------------
# Text column
# ---------------------------------------------------------------------------

def _draw_block(block, x, y, width, style):
    """A titled data block: centred title, rule, then label/value rows."""
    out = [_text(x + width / 2.0, y, block.title, style.block_title_size,
                 anchor="middle", weight="bold")]
    y += 1.6
    out.append(_line(x, y, x + width, y, "#000", style.rule_stroke))
    y += style.line_gap
    for label, value in block.rows:
        out.append(_text(x + 2.0, y, label, style.row_size))
        out.append(_text(x + width - 2.0, y, value, style.row_size,
                         anchor="end"))
        y += style.line_gap
    return out, y + 2.0


def _draw_tier_group(title, rows, x, y, width, style):
    """One cutting-instructions group (Pavilion / Girdle / Crown)."""
    out = [_text(x, y, title, style.group_size, weight="bold")]
    y += style.line_gap
    name_x = x + 2.0
    angle_x = x + style.tier_angle_x
    index_x = x + style.tier_index_x
    index_width = width - style.tier_index_x
    for row in rows:
        fill = "#888" if row.suppressed else "#000"
        out.append(_text(name_x, y, row.name or "-", style.row_size,
                         fill=fill))
        out.append(_text(angle_x, y, "%.2f°" % row.angle, style.row_size,
                         anchor="end", fill=fill))
        lines = _wrap(row.indices_text or "Table", index_width, style.row_size)
        for offset, line in enumerate(lines):
            out.append(_text(index_x, y + offset * (style.line_gap - 0.4),
                             line, style.row_size, fill=fill))
        y += style.line_gap + (len(lines) - 1) * (style.line_gap - 0.4)
    return out, y + 2.0


def _text_column(diagram, style, top):
    """The whole left column; returns (svg parts, bottom y)."""
    x = style.margin
    width = style.text_width
    y = top
    out = []
    for block in diagram.blocks:
        parts, y = _draw_block(block, x, y, width, style)
        out.extend(parts)
        y += 3.0

    groups = [("Pavilion", PAVILION), ("Girdle", GIRDLE), ("Crown", CROWN)]
    for title, side in groups:
        rows = [row for row in diagram.tiers if row.side == side]
        if not rows:
            continue
        parts, y = _draw_tier_group(title, rows, x, y, width, style)
        out.extend(parts)
        y += 1.5

    for note in diagram.footnotes:
        for line in _wrap(note, width, style.footnote_size) or [note]:
            out.append(_text(x, y, line, style.footnote_size, fill="#333"))
            y += style.line_gap - 0.6
    return out, y


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _compose(diagram, style, tier_tint=None):
    """Lay the whole page out; returns (svg body parts, width, height) in mm."""
    body = []
    # Title and heading lines.
    body.append(_text(style.margin, style.margin + 6.0, diagram.title,
                      style.title_size, weight="bold"))
    y = style.margin + 8.4
    body.append(_line(style.margin, y, style.margin + style.text_width,
                      y, "#000", 0.6))
    y += 3.4
    for line in diagram.subtitle:
        body.append(_text(style.margin, y, line, style.subtitle_size))
        y += 3.4
    # The drawing panels start level with the text column, below the heading.
    top = max(26.0, y + 2.0)

    column, column_bottom = _text_column(diagram, style, top)

    placed, size = _grid(diagram.views, style, top)
    scale = _fit_scale([view for view, *_rest in placed], size, style)
    views_bottom = top
    for view, vx, vy, vsize in placed:
        cell = _Cell(view, vx, vy, vsize, scale)
        body.extend(_draw_view(cell, style, tier_tint))
        views_bottom = max(views_bottom, vy + vsize)
    body.extend(column)

    # A page that would overflow grows rather than clipping the tier table.
    height = max(style.height,
                 max(column_bottom, views_bottom) + style.margin)
    return body, style.width, height


def page_size_mm(diagram, style=None):
    """(width, height) in mm of the page :func:`render_svg` would produce.

    The PDF export needs this to set its page size, and must agree with the
    SVG exactly — hence one layout pass shared by both.
    """
    _body, width, height = _compose(diagram, style or A4_PORTRAIT)
    return width, height


def render_svg(diagram, style=None, tier_tint=None):
    """Render ``diagram`` to a standalone SVG document string.

    ``tier_tint`` (Phase 4b optics overlay): optional mapping of tier key
    (the tier document object's internal ``Name``, i.e. ``Facet.tier_key``)
    to an SVG fill color; matching facet polygons are tinted instead of
    white. Purely an extra fill per polygon — layout, strokes, labels and
    everything else stay identical, and ``None`` reproduces the base
    diagram exactly.
    """
    style = style or A4_PORTRAIT
    body, width, height = _compose(diagram, style, tier_tint)

    header = (
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        'width="%smm" height="%smm" viewBox="0 0 %s %s" '
        'font-family="%s">' % (_num(width), _num(height),
                               _num(width), _num(height), FONT))
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        header,
        "<title>%s</title>" % _escape(diagram.title or "Faceting diagram"),
        '<rect x="0" y="0" width="%s" height="%s" fill="#fff"/>'
        % (_num(width), _num(height)),
        "\n".join(body),
        "</svg>",
        "",
    ])
