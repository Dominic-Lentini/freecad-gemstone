# SPDX-License-Identifier: LGPL-2.1-or-later
"""Diagram model, stats blocks and SVG writer — **without FreeCAD**.

DESIGN.md section 8 requires the diagram's SVG generation to be "pure-Python
(no GUI deps) so it's testable headless". This module is the proof: it
exercises the whole rendering half against hand-built data and never imports
FreeCAD, so it runs under a plain ``pip install pytest``. The projection half,
which does need FreeCAD and a real B-Rep, lives in ``test_diagram.py``.
"""

import pytest

from freecad.lapidary.faceting.diagram import model, stats, svg
from freecad.lapidary.faceting.diagram.model import (
    CROWN, PAVILION, Diagram, Facet, IndexRing, Label, Segment, TextBlock,
    TierRow, View)


def _square(cx=0.0, cy=0.0, r=1.0):
    return [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r),
            (cx - r, cy + r)]


def _demo_diagram():
    crown = View(key="crown", title="Crown")
    crown.facets = [Facet(points=_square(), side=CROWN, tier_key="T",
                          index=0)]
    crown.outline = [Segment((-2.0, -2.0), (2.0, -2.0))]
    crown.labels = [Label("T", 0.0, 0.0)]
    crown.ring = IndexRing(gear=96, radius=2.5,
                           ticks=[(96, -90.0), (24, 0.0)],
                           labels=[(96, -90.0, "<96>"), (24, 0.0, "24")])
    pavilion = View(key="pavilion", title="Pavilion")
    pavilion.facets = [Facet(points=_square(0.0, 0.0, 1.5), side=PAVILION,
                             tier_key="P1", index=3)]
    pavilion.labels = [Label("G1", 0.0, -2.5, role="girdle")]
    return Diagram(
        title="Demo Stone",
        subtitle=["by Nobody"],
        views=[crown, pavilion],
        blocks=[TextBlock("Size Data", [("L/W", "1.000")])],
        tiers=[
            TierRow(key="P1", name="P1 breaks", side=PAVILION,
                    working_side="Pavilion", angle=42.0, distance=3.0,
                    depth=1.0, indices=[3, 9], indices_text="03-09",
                    gear=96, facet_count=2),
            TierRow(key="T", name="Table", side=CROWN, working_side="Crown",
                    angle=0.0, distance=2.0, depth=1.0, indices=[],
                    indices_text="Table", gear=96, facet_count=1),
        ],
        footnotes=["Dop on the round end."],
    )


class TestGeometryHelpers:
    def test_polygon_area_and_centroid(self):
        square = _square(r=2.0)
        assert model.polygon_area(square) == pytest.approx(16.0)
        assert model.polygon_centroid(square) == pytest.approx((0.0, 0.0))
        # Clockwise input gives a negative area but the same centroid.
        assert model.polygon_area(list(reversed(square))) == pytest.approx(
            -16.0)
        assert model.polygon_centroid(
            list(reversed(square))) == pytest.approx((0.0, 0.0))

    def test_degenerate_polygon_centroid_falls_back(self):
        line = [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0)]
        assert model.polygon_centroid(line) == pytest.approx((2.0, 0.0))
        assert model.polygon_centroid([]) == (0.0, 0.0)

    def test_bounds_of(self):
        assert model.bounds_of([(1.0, 2.0), (-3.0, 5.0)]) == (
            -3.0, 2.0, 1.0, 5.0)
        assert model.bounds_of([]) == (-1.0, -1.0, 1.0, 1.0)

    def test_ring_angle_puts_tooth_zero_at_the_bottom(self):
        # The whole GemCad index convention in one assertion: azimuth 0 (the
        # facet normal along +x) is drawn pointing straight down, and a
        # quarter turn counter-clockwise in the model is a quarter turn
        # counter-clockwise on screen.
        assert model.ring_angle_deg(0.0) == -90.0
        assert model.ring_point(1.0, model.ring_angle_deg(0.0)) == \
            pytest.approx((0.0, -1.0), abs=1e-12)
        assert model.ring_point(1.0, model.ring_angle_deg(90.0)) == \
            pytest.approx((1.0, 0.0), abs=1e-12)

    def test_view_bounds_include_the_index_ring(self):
        view = _demo_diagram().view("crown")
        umin, vmin, umax, vmax = view.bounds()
        assert (umin, vmin, umax, vmax) == (-2.5, -2.5, 2.5, 2.5)

    def test_label_lines(self):
        assert Label("C1\n40.68°", 0.0, 0.0).lines == ["C1", "40.68°"]
        assert Label("", 0.0, 0.0).lines == []


class TestSvgWriter:
    def test_renders_a_standalone_svg_document(self):
        out = svg.render_svg(_demo_diagram())
        assert out.startswith("<?xml")
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in out
        assert out.rstrip().endswith("</svg>")
        assert 'width="210mm"' in out
        # No external references: the file must stand alone.
        assert "http://" not in out.replace("http://www.w3.org/2000/svg", "")

    def test_renders_every_diagram_element(self):
        out = svg.render_svg(_demo_diagram())
        assert "Demo Stone" in out and "by Nobody" in out
        assert '<g id="view-crown">' in out and '<g id="view-pavilion">' in out
        assert "&lt;96&gt;" in out          # ID tooth, angle-bracketed
        assert "Size Data" in out and "L/W" in out
        assert ">Pavilion<" in out and ">Crown<" in out   # group headings
        assert "P1 breaks" in out and "03-09" in out
        assert "42.00°" in out
        assert "Dop on the round end." in out

    def test_escapes_text(self):
        diagram = _demo_diagram()
        diagram.title = 'Ampersand & "quoted" <tag>'
        out = svg.render_svg(diagram)
        assert "&amp;" in out and "&quot;" in out and "&lt;tag&gt;" in out
        assert "<tag>" not in out

    def test_page_grows_for_a_long_tier_list(self):
        short = svg.render_svg(_demo_diagram())
        long_diagram = _demo_diagram()
        long_diagram.tiers = long_diagram.tiers * 40
        tall = svg.render_svg(long_diagram)
        assert 'height="297mm"' in short
        assert 'height="297mm"' not in tall     # grew rather than clipping

    def test_letter_page_style(self):
        out = svg.render_svg(_demo_diagram(), style=svg.LETTER_PORTRAIT)
        assert 'width="215.9mm"' in out

    def test_index_list_wrapping(self):
        text = "-".join("%02d" % i for i in range(3, 96, 6))
        assert svg._wrap(text, 40.0, 2.9) != [text]         # wraps
        assert "".join(svg._wrap(text, 40.0, 2.9)) == text  # losslessly
        assert svg._wrap("03-09", 40.0, 2.9) == ["03-09"]
        assert svg._wrap("", 40.0, 2.9) == []


class TestStatsBlocks:
    """The text blocks, driven by a stub gem (still no FreeCAD)."""

    class _StubGem:
        AscHeaders = ["Design Name", "by Someone", "Journal, p1"]
        Author = "Ignored When Headers Exist"
        IntendedRI = 1.54
        IndexGear = 96
        Handedness = "Counterclockwise"
        AscSymmetryFolds = 8
        AscSymmetryMirror = "y"
        SourceFile = "thing.asc"

    def test_heading_lines_prefer_the_asc_header_block(self):
        assert stats.heading_lines(self._StubGem()) == [
            "by Someone", "Journal, p1"]

    def test_heading_lines_fall_back_to_the_author(self):
        class Plain:
            AscHeaders = []
            Author = "Dominic"
        assert stats.heading_lines(Plain()) == ["by Dominic"]

    def test_design_data_block(self):
        rows = dict(stats.design_data_block(self._StubGem()).rows)
        assert rows["Angles for R.I."] == "1.54"
        assert rows["Symmetry"] == "8-fold, mirror"
        assert rows["Index gear"] == "96"
        assert rows["Source"] == "thing.asc"

    def test_facet_data_uses_gemcads_plus_table_notation(self):
        counts = {"crown_facets": 32, "table_facets": 1, "pavilion_facets": 24,
                  "girdle_facets": 16, "total_facets": 73, "crown_tiers": 3,
                  "table_tiers": 1, "pavilion_tiers": 2, "girdle_tiers": 1}
        rows = dict(stats.facet_data_block(counts).rows)
        assert rows["Crown facets"] == "32+1"
        assert rows["Crown tiers"] == "3+1"
        assert rows["Total facets"] == "73"
        assert rows["Total tiers"] == "7"

    def test_facet_data_without_a_table(self):
        counts = {"crown_facets": 8, "table_facets": 0, "pavilion_facets": 8,
                  "girdle_facets": 8, "total_facets": 24, "crown_tiers": 1,
                  "table_tiers": 0, "pavilion_tiers": 1, "girdle_tiers": 1}
        rows = dict(stats.facet_data_block(counts).rows)
        assert rows["Crown facets"] == "8"
        assert rows["Crown tiers"] == "1"
        assert rows["Total tiers"] == "3"

    def test_size_data_is_quoted_as_ratios_of_w(self):
        report = {"width": 10.0, "length": 10.0, "total_depth": 6.07,
                  "volume": 208.0, "table_width": 5.46, "pavilion_depth": 4.27,
                  "crown_height": 1.50, "girdle_thickness": 0.30}
        rows = dict(stats.size_data_block(report).rows)
        assert rows["L/W"] == "1.000"
        assert rows["H/W"] == "0.607"
        assert rows["V/W^3"] == "0.208"
        assert rows["P/W"] == "0.427"
        assert rows["C/W"] == "0.150"
        assert rows["P/C"] == "2.847"

    def test_size_data_tolerates_a_knife_edge_girdle(self):
        report = {"width": 10.0, "length": 10.0, "total_depth": 6.0,
                  "volume": 100.0, "table_width": None, "pavilion_depth": None,
                  "crown_height": None, "girdle_thickness": None}
        rows = dict(stats.size_data_block(report).rows)
        assert rows["P/W"] == "-" and rows["P/C"] == "-"
        assert rows["T/W"] == "-"

    def test_count_facets_splits_the_table_out(self):
        rows_by_key = {
            "t": TierRow(key="t", name="T", side=CROWN,
                         working_side="Crown", angle=0.0, distance=1.0,
                         depth=1.0, indices=[], indices_text="Table",
                         gear=96),
            "c": TierRow(key="c", name="C1", side=CROWN,
                         working_side="Crown", angle=40.0, distance=1.0,
                         depth=1.0, indices=[3], indices_text="03", gear=96),
        }
        facets_by_side = {
            CROWN: [Facet(points=_square(), tier_key="t"),
                    Facet(points=_square(), tier_key="c"),
                    Facet(points=_square(), tier_key="c")],
            PAVILION: [], model.GIRDLE: [],
        }
        counts = stats.count_facets(facets_by_side, rows_by_key)
        assert counts["table_facets"] == 1
        assert counts["crown_facets"] == 2
        assert counts["crown_tiers"] == 1
        assert counts["table_tiers"] == 1
        assert counts["total_facets"] == 3
