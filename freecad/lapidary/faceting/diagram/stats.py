# SPDX-License-Identifier: LGPL-2.1-or-later
"""The diagram's text blocks: Facet Data, Size Data, Design Data (DESIGN.md
section 8, "tier table ... stone stats ... design metadata block").

Pure Python — it only reads attributes off the Gem, so it imports neither
FreeCAD nor Qt and can be exercised with a stub object.

The three blocks and their exact contents copy a real GemCad printout; see
``DIAGRAM_NOTES.md``. Two details worth keeping:

* Size Data is quoted as **ratios of W**, not percentages, and includes
  ``V/W^3`` and ``P/C`` — so the numbers line up with published diagrams.
  ``reports.compute_report`` already produces every input.
* The crown counts are written GemCad-style as ``32+1``: facets plus the
  table, tiers plus the table tier.
"""

from freecad.lapidary.faceting.diagram.model import TextBlock

__all__ = ["heading_lines", "facet_data_block", "size_data_block",
           "design_data_block", "text_blocks", "count_facets"]


def _plus_table(count, table_count):
    """GemCad's ``32+1`` notation: the table is quoted separately."""
    if not table_count:
        return "%d" % count
    return "%d+%d" % (count, table_count)


def heading_lines(gem):
    """Sub-title lines under the design name.

    An imported design keeps GemCad's own heading block verbatim
    (``AscHeaders``, whose first line is the design name and therefore the
    diagram title); a hand-built one falls back to the author.
    """
    headers = [line for line in (getattr(gem, "AscHeaders", None) or [])
               if line.strip()]
    if headers:
        return list(headers[1:])
    author = getattr(gem, "Author", "")
    return ["by %s" % author] if author else []


def count_facets(facets_by_side, rows_by_key):
    """Facet and tier counts per geometric group, table split out.

    ``facets_by_side`` maps CROWN/PAVILION/GIRDLE to the projected facet
    lists; ``rows_by_key`` maps a tier key to its :class:`TierRow`. The table
    is identified as a facet whose owning tier cuts at 0 deg.
    """
    from freecad.lapidary.faceting.diagram.model import (
        CROWN, GIRDLE, PAVILION)

    def is_table(facet):
        row = rows_by_key.get(facet.tier_key)
        return row is not None and abs(row.angle) < 1e-9

    crown = facets_by_side.get(CROWN, [])
    table_facets = [f for f in crown if is_table(f)]
    table_keys = {f.tier_key for f in table_facets}

    def tier_count(side, exclude_table):
        keys = {f.tier_key for f in facets_by_side.get(side, [])
                if f.tier_key}
        if exclude_table:
            keys -= table_keys
        else:
            keys &= table_keys
        return len(keys)

    return {
        "crown_facets": len(crown) - len(table_facets),
        "table_facets": len(table_facets),
        "pavilion_facets": len(facets_by_side.get(PAVILION, [])),
        "girdle_facets": len(facets_by_side.get(GIRDLE, [])),
        "total_facets": (len(crown) + len(facets_by_side.get(PAVILION, []))
                         + len(facets_by_side.get(GIRDLE, []))),
        "crown_tiers": tier_count(CROWN, exclude_table=True),
        "table_tiers": tier_count(CROWN, exclude_table=False),
        "pavilion_tiers": tier_count(PAVILION, exclude_table=True),
        "girdle_tiers": tier_count(GIRDLE, exclude_table=True),
    }


def facet_data_block(counts):
    total_tiers = (counts["crown_tiers"] + counts["table_tiers"]
                   + counts["pavilion_tiers"] + counts["girdle_tiers"])
    return TextBlock("Facet Data", [
        ("Pavilion facets", "%d" % counts["pavilion_facets"]),
        ("Girdle facets", "%d" % counts["girdle_facets"]),
        ("Crown facets", _plus_table(counts["crown_facets"],
                                     counts["table_facets"])),
        ("Total facets", "%d" % counts["total_facets"]),
        ("Pavilion tiers", "%d" % counts["pavilion_tiers"]),
        ("Girdle tiers", "%d" % counts["girdle_tiers"]),
        ("Crown tiers", _plus_table(counts["crown_tiers"],
                                    counts["table_tiers"])),
        ("Total tiers", "%d" % total_tiers),
    ])


def _ratio(value, width):
    if value is None or not width:
        return "-"
    return "%.3f" % (value / width)


def size_data_block(report):
    """L/W, H/W, V/W^3, P/W, C/W, P/C — the printout's Size Data block."""
    width = report.get("width") or 0.0
    crown = report.get("crown_height")
    pavilion = report.get("pavilion_depth")
    rows = [
        ("L/W", _ratio(report.get("length"), width)),
        ("H/W", _ratio(report.get("total_depth"), width)),
        ("V/W^3", "-" if not width else "%.3f" % (
            report.get("volume", 0.0) / width ** 3)),
        ("T/W", _ratio(report.get("table_width"), width)),
        ("P/W", _ratio(pavilion, width)),
        ("C/W", _ratio(crown, width)),
        ("P/C", "-" if not crown or pavilion is None
         else "%.3f" % (pavilion / crown)),
        ("Girdle/W", _ratio(report.get("girdle_thickness"), width)),
    ]
    return TextBlock("Size Data", rows)


def design_data_block(gem):
    folds = getattr(gem, "AscSymmetryFolds", None)
    symmetry = "-" if not folds else (
        "%d-fold, mirror" % folds
        if (getattr(gem, "AscSymmetryMirror", "y") or "y") == "y"
        else "%d-fold" % folds)
    rows = [
        ("Angles for R.I.", "%.2f" % getattr(gem, "IntendedRI", 0.0)
         if getattr(gem, "IntendedRI", 0.0) else "-"),
        ("Symmetry", symmetry),
        ("Index gear", "%d" % getattr(gem, "IndexGear", 0)),
        ("Handedness", str(getattr(gem, "Handedness", "-"))),
    ]
    source = getattr(gem, "SourceFile", "")
    if source:
        rows.append(("Source", str(source)))
    return TextBlock("Design Data", rows)


def text_blocks(gem, report, counts):
    """The three printout blocks, in GemCad's order."""
    return [facet_data_block(counts),
            size_data_block(report),
            design_data_block(gem)]
