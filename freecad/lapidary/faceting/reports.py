# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stone measurements and cutting-sheet generation (DESIGN.md section 4,
items 6-7). GUI-free: everything here runs headless under FreeCADCmd; the
Lapidary_Report / Lapidary_CuttingSheet commands are thin GUI wrappers.

Measurement conventions (documented because published diagrams vary):

* ``W`` (width) is the smaller of the stone's two horizontal bounding-box
  extents, ``L`` the larger; all percentages are relative to W, matching the
  GemCad printout convention of quoting P/W, C/W, H/W.
* The girdle band is the set of faces parallel to the gem axis: planar faces
  with a horizontal normal (theta = 90 deg cuts) plus any cylindrical face
  whose axis is the gem axis (remaining rough on a cylinder stock). Girdle
  top/bottom are that band's z-extremes.
* The table is the topmost planar face whose normal is exactly +Z; its width
  is measured as the larger axis-aligned extent of the face (for the classic
  octagonal table this is the corner-to-corner width across the octagon).
* ``facet_count`` counts distinct facet *planes* among planar faces, so a
  facet that later cuts happen to split into coplanar pieces still counts
  once; ``face_count`` is the raw topological count.

The cutting sheet can optionally embed the Phase 3 faceting diagram; that is
the only place this module reaches into ``faceting.diagram``, and it does so
with a local import so the report path never pays for it.
"""

import math

import Part

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.faceting.indexspec import format_indices
from freecad.lapidary.faceting.ownership import face_plane

__all__ = ["compute_report", "gem_report", "report_text",
           "cutting_sheet_rows", "cutting_sheet_html"]

_AXIS_TOL = 1e-9


def _is_axis_cylinder(face):
    surface = face.Surface
    if not isinstance(surface, Part.Cylinder):
        return False
    axis = surface.Axis
    return abs(abs(axis.z) / axis.Length - 1.0) < _AXIS_TOL


def compute_report(shape):
    """Compute stone metrics from a finished B-Rep (DESIGN.md section 4
    item 7). Returns a dict; girdle-derived metrics are None when the stone
    has no girdle band (knife-edge girdle)."""
    bb = shape.BoundBox
    length = max(bb.XLength, bb.YLength)
    width = min(bb.XLength, bb.YLength)
    total_depth = bb.ZLength

    planar = []  # (face, normal, d)
    for face in shape.Faces:
        plane = face_plane(face)
        if plane is not None:
            planar.append((face, plane[0], plane[1]))

    # Distinct facet planes (see module docstring).
    plane_keys = set()
    for _face, normal, d in planar:
        plane_keys.add((round(normal.x, 7), round(normal.y, 7),
                        round(normal.z, 7), round(d, 6)))

    # Girdle band: theta = 90 deg facets plus axial cylinder remnants.
    girdle_faces = [face for face, normal, _d in planar
                    if abs(normal.z) < _AXIS_TOL]
    girdle_faces += [face for face in shape.Faces if _is_axis_cylinder(face)]
    if girdle_faces:
        girdle_top = max(face.BoundBox.ZMax for face in girdle_faces)
        girdle_bottom = min(face.BoundBox.ZMin for face in girdle_faces)
    else:
        girdle_top = girdle_bottom = None

    # Table: topmost planar face with normal exactly +Z.
    table_faces = [(face, d) for face, normal, d in planar
                   if normal.z > 1.0 - _AXIS_TOL]
    table_width = None
    if table_faces:
        top_d = max(d for _face, d in table_faces)
        top = [face for face, d in table_faces if abs(d - top_d) < 1e-9]
        xmin = min(face.BoundBox.XMin for face in top)
        xmax = max(face.BoundBox.XMax for face in top)
        ymin = min(face.BoundBox.YMin for face in top)
        ymax = max(face.BoundBox.YMax for face in top)
        table_width = max(xmax - xmin, ymax - ymin)

    def pct(value):
        return None if value is None else 100.0 * value / width

    report = {
        "length": length,
        "width": width,
        "lw_ratio": length / width,
        "total_depth": total_depth,
        "depth_pct": pct(total_depth),
        "table_width": table_width,
        "table_pct": pct(table_width),
        "girdle_top": girdle_top,
        "girdle_bottom": girdle_bottom,
        "girdle_thickness": None,
        "girdle_pct": None,
        "crown_height": None,
        "crown_pct": None,
        "pavilion_depth": None,
        "pavilion_pct": None,
        "facet_count": len(plane_keys),
        "planar_face_count": len(planar),
        "face_count": len(shape.Faces),
        "volume": shape.Volume,
    }
    if girdle_top is not None:
        report["girdle_thickness"] = girdle_top - girdle_bottom
        report["girdle_pct"] = pct(report["girdle_thickness"])
        report["crown_height"] = bb.ZMax - girdle_top
        report["crown_pct"] = pct(report["crown_height"])
        report["pavilion_depth"] = girdle_bottom - bb.ZMin
        report["pavilion_pct"] = pct(report["pavilion_depth"])
    return report


def gem_report(gem):
    """Compute the report for a Gem's final B-Rep (None if it has none)."""
    shape = gem_feature.final_shape(gem)
    if shape is None:
        return None
    return compute_report(shape)


_REPORT_LINES = [
    ("L/W", "lw_ratio", "%.3f"),
    ("Width W", "width", "%.3f mm"),
    ("Length L", "length", "%.3f mm"),
    ("Total depth", "depth_pct", "%.1f %%"),
    ("Crown height", "crown_pct", "%.1f %%"),
    ("Pavilion depth", "pavilion_pct", "%.1f %%"),
    ("Girdle thickness", "girdle_pct", "%.1f %%"),
    ("Table", "table_pct", "%.1f %%"),
    ("Facet count", "facet_count", "%d"),
]


def report_text(report):
    """Human-readable multi-line summary of a report dict."""
    lines = []
    for label, key, fmt in _REPORT_LINES:
        value = report.get(key)
        text = "-" if value is None else fmt % value
        lines.append("%-18s %s" % (label + ":", text))
    return "\n".join(lines)


def optics_section_text(gem):
    """The stone report's optics section (DESIGN_OPTICS.md section 9,
    Phase 4b): the stored summary of the Gem's single *fresh* optics
    study, or "" when there is none — a stale study's numbers no longer
    describe this geometry and are deliberately withheld here.

    Lazy optics import: the faceting module must not depend on optics
    being importable to produce its geometric report.
    """
    if gem is None:
        return ""
    try:
        from freecad.lapidary.optics.study_feature import find_studies
    except ImportError:
        return ""
    fresh = [s for s in find_studies(gem)
             if not getattr(s, "Stale", True)
             and getattr(s, "ResultSummary", "")]
    if len(fresh) != 1:
        return ""
    return "Optics (%s)\n%s\n%s" % (
        fresh[0].Label, "-" * 40, fresh[0].ResultSummary)


def cutting_sheet_rows(gem):
    """Ordered cutting instructions, one dict per tier (DESIGN.md section 4
    item 6): sequence, name, side, angle, index list, gear, cheater,
    distance, suppressed flag."""
    rows = []
    sequence = 0
    for feature in gem_feature.pipeline_features(gem):
        if not gem_feature.is_tier(feature):
            continue
        sequence += 1
        from freecad.lapidary.faceting.tier_feature import effective_gear
        gear = effective_gear(feature)
        indices = list(feature.Indices)
        rows.append({
            "sequence": sequence,
            "name": feature.TierName or feature.Label,
            "side": feature.WorkingSide,
            "angle": feature.Angle.Value,
            "depth": feature.CutDepth.Value,
            "distance": feature.Distance.Value,
            "indices": indices,
            "indices_text": format_indices(indices, gear) or "Table",
            "gear": gear,
            "index_offset": feature.IndexOffset,
            "facet_count": len(indices) or 1,
            "suppressed": feature.Suppressed,
        })
    return rows


_SHEET_CSS = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 2em; }
h1 { font-size: 1.5em; border-bottom: 2px solid #000; }
table { border-collapse: collapse; margin-top: 1em; }
th, td { border: 1px solid #444; padding: 0.3em 0.7em; text-align: left; }
th { background: #eee; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.meta, .stats { margin: 0.5em 0; }
.suppressed { color: #999; text-decoration: line-through; }
.diagram { margin: 1em 0; page-break-inside: avoid; }
.diagram svg { max-width: 100%; height: auto; }
"""


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _diagram_svg_fragment(gem):
    """The faceting diagram as an inline SVG fragment, or None.

    Inlined rather than linked so the cutting sheet stays a single portable
    file. The XML declaration is stripped: it is only legal at the very start
    of a document, and an HTML document already started.
    """
    from freecad.lapidary.faceting import diagram as diagram_pkg

    svg = diagram_pkg.gem_diagram_svg(gem)
    if svg is None:
        return None
    start = svg.find("<svg")
    return svg[start:] if start >= 0 else svg


def cutting_sheet_html(gem, report=None, include_diagram=False):
    """A printable HTML cutting sheet, GemCad-printout style: design
    metadata, ordered tier table, and (optionally) the stone report and the
    2D faceting diagram (DESIGN.md section 8), inlined as SVG."""
    title = gem.DesignName or gem.Label
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
             "<title>%s - cutting sheet</title>" % _escape(title),
             "<style>%s</style></head><body>" % _SHEET_CSS,
             "<h1>%s</h1>" % _escape(title)]

    meta = []
    if gem.Author:
        meta.append("Author: %s" % _escape(gem.Author))
    meta.append("Index gear: %d" % gem.IndexGear)
    meta.append("Handedness: %s" % _escape(gem.Handedness))
    if gem.IntendedRI:
        meta.append("Angles for R.I. %.2f" % gem.IntendedRI)
    if gem.SourceFile:
        meta.append("Source: %s" % _escape(gem.SourceFile))
    parts.append("<div class='meta'>%s</div>" % " &middot; ".join(meta))

    parts.append("<table><tr><th>#</th><th>Tier</th><th>Side</th>"
                 "<th>Angle</th><th>Indices</th><th>Facets</th>"
                 "<th>Cut depth</th><th>Plane distance</th>"
                 "<th>Cheater</th></tr>")
    for row in cutting_sheet_rows(gem):
        css = " class='suppressed'" if row["suppressed"] else ""
        cheater = ("%+g" % row["index_offset"]) if row["index_offset"] else ""
        parts.append(
            "<tr%s><td class='num'>%d</td><td>%s</td><td>%s</td>"
            "<td class='num'>%.2f&deg;</td><td>%s</td><td class='num'>%d</td>"
            "<td class='num'>%.3f mm</td><td class='num'>%.3f mm</td>"
            "<td class='num'>%s</td></tr>"
            % (css, row["sequence"], _escape(row["name"]),
               _escape(row["side"]), row["angle"],
               _escape(row["indices_text"]), row["facet_count"],
               row["depth"], row["distance"], cheater))
    parts.append("</table>")

    if report is not None:
        parts.append("<div class='stats'><h2>Stone report</h2><pre>%s</pre></div>"
                     % _escape(report_text(report)))

    if include_diagram:
        fragment = _diagram_svg_fragment(gem)
        if fragment is None:
            parts.append("<p class='diagram'><em>No solid geometry to "
                         "diagram yet.</em></p>")
        else:
            parts.append("<div class='diagram'><h2>Faceting diagram</h2>%s"
                         "</div>" % fragment)

    parts.append("</body></html>")
    return "\n".join(parts)
