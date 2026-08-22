# SPDX-License-Identifier: LGPL-2.1-or-later
"""Projection of a real B-Rep into the 2D faceting diagram (DESIGN.md
section 8, Phase 3). Requires FreeCAD; the pure rendering half is covered
without it by ``test_diagram_render.py``.

The golden model is the Standard Round Brilliant scripted by
``test_pipeline``, and the assertions below are taken from the *published*
GemCad printout of that design (facettieren.ch — the same printout
``test_pipeline`` derives its angles from). Its Facet Data block reads
24 pavilion / 16 girdle / 32+1 crown = 73 facets in 2 / 1 / 3+1 = 7 tiers,
and its Size Data block L/W 1.000, H/W 0.607, P/W 0.427, C/W 0.150.

Presentation assertions (index ring, mirrored pavilion view, label placement)
encode the conventions verified against that printout and the GemCad manual;
the evidence is written up in ``faceting/diagram/DIAGRAM_NOTES.md``.

The *visual* half of the Phase 3 definition of done cannot be asserted here;
``tools/generate_diagrams.py`` renders every fixture design for that
comparison.
"""

import math

import pytest

from freecad.lapidary.faceting.diagram import model
from freecad.lapidary.faceting.diagram.model import CROWN, GIRDLE, PAVILION

# ---------------------------------------------------------------------------
# Projection of the golden Standard Round Brilliant (needs FreeCAD)
# ---------------------------------------------------------------------------

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.faceting import gem_feature, ownership  # noqa: E402
from freecad.lapidary.faceting.diagram import projection  # noqa: E402
from freecad.lapidary.faceting.stock_feature import make_stock  # noqa: E402
from freecad.lapidary.faceting.tier_feature import make_tier  # noqa: E402

from test_pipeline import (  # noqa: E402
    EXPECTED_FACETS, GEAR, IDX8_MAINS, SRB_TIERS, build_srb)

#: Published Facet Data of the SRB printout, by geometric group.
PUBLISHED_CROWN_FACETS = 32       # C1 16 + C2 8 + C3 8
PUBLISHED_TABLE_FACETS = 1
PUBLISHED_PAVILION_FACETS = 24    # P1 16 + P2 8
PUBLISHED_GIRDLE_FACETS = 16      # G1


@pytest.fixture(scope="module")
def srb_diagram():
    doc = FreeCAD.newDocument("srb_diagram")
    try:
        gem, _stock, _tiers = build_srb(doc)
        yield gem, projection.build_diagram(gem)
    finally:
        FreeCAD.closeDocument(doc.Name)


class TestFacePolygon:
    def test_projected_area_matches_every_face(self, srb_diagram):
        """The strongest available check on the boundary extraction: an
        orthographic projection scales a planar face's area by |n . w|
        exactly, so any mis-ordered wire (which yields a self-crossing
        polygon) shows up immediately."""
        gem, _diagram = srb_diagram
        shape = gem_feature.final_shape(gem)
        for index, face in enumerate(shape.Faces):
            points = projection._project_all(
                projection.face_polygon(face), projection.ROUND_BASIS)
            normal, _d = ownership.face_plane(face)
            assert abs(model.polygon_area(points)) == pytest.approx(
                face.Area * abs(normal.z), abs=1e-7), "face %d" % index

    def test_polygon_has_one_point_per_corner(self, srb_diagram):
        gem, _diagram = srb_diagram
        shape = gem_feature.final_shape(gem)
        for face in shape.Faces:
            points = projection.face_polygon(face)
            assert len(points) == len(face.Vertexes)
            # No repeated point: a repeat is the signature of a broken chain.
            for i, point in enumerate(points):
                for other in points[i + 1:]:
                    assert (point - other).Length > 1e-9


class TestDiagramStructure:
    def test_views_present(self, srb_diagram):
        _gem, diagram = srb_diagram
        assert [view.key for view in diagram.views] == [
            "crown", "pavilion", "elevation"]

    def test_polygon_counts_match_the_published_facet_counts(self, srb_diagram):
        """DESIGN.md section 8: the views' polygons come from the final
        B-Rep's planar faces, one per facet of the published design."""
        _gem, diagram = srb_diagram
        crown = diagram.view("crown")
        pavilion = diagram.view("pavilion")
        assert len(crown.facets) == (PUBLISHED_CROWN_FACETS
                                     + PUBLISHED_TABLE_FACETS)
        assert len(pavilion.facets) == PUBLISHED_PAVILION_FACETS
        # Girdle facets are the outline, not polygons, in a round view.
        assert all(facet.side == "Crown" for facet in crown.facets)
        assert all(facet.side == "Pavilion" for facet in pavilion.facets)
        counts = dict(diagram.blocks[0].rows)
        assert counts["Girdle facets"] == "%d" % PUBLISHED_GIRDLE_FACETS
        assert counts["Total facets"] == "%d" % EXPECTED_FACETS

    def test_every_facet_is_attributed_to_a_tier(self, srb_diagram):
        _gem, diagram = srb_diagram
        keys = {row.key for row in diagram.tiers}
        for view in (diagram.view("crown"), diagram.view("pavilion")):
            for facet in view.facets:
                assert facet.tier_key in keys      # nothing left to the stock
                assert facet.index is not None

    def test_tier_rows_group_the_girdle_geometrically(self, srb_diagram):
        """The girdle tier is cut as a Pavilion tier at 90 deg; GemCad counts
        it under Girdle, and so does the diagram (DIAGRAM_NOTES.md)."""
        _gem, diagram = srb_diagram
        rows = {row.name: row for row in diagram.tiers}
        assert len(rows) == len(SRB_TIERS)
        assert rows["G1 girdle"].working_side == "Pavilion"
        assert rows["G1 girdle"].side == GIRDLE
        assert rows["P1 breaks"].side == PAVILION
        assert rows["C1 breaks"].side == CROWN
        assert rows["Table"].side == CROWN

    def test_outline_comes_from_the_girdle_and_reaches_the_girdle_radius(
            self, srb_diagram):
        gem, diagram = srb_diagram
        shape = gem_feature.final_shape(gem)
        expected = max(math.hypot(v.Point.x, v.Point.y)
                       for v in shape.Vertexes)
        crown = diagram.view("crown")
        assert crown.outline
        radius = max(math.hypot(*point) for segment in crown.outline
                     for point in (segment.a, segment.b))
        assert radius == pytest.approx(expected, abs=1e-7)
        # Crown and pavilion share one outline: they are the same projection.
        assert diagram.view("pavilion").outline == crown.outline

    def test_elevation_is_a_full_wireframe(self, srb_diagram):
        _gem, diagram = srb_diagram
        elevation = diagram.view("elevation")
        assert not elevation.facets           # see-through, not filled
        assert len(elevation.wireframe) > 50
        umin, vmin, umax, vmax = elevation.bounds()
        # Crown up, culet down: the profile is taller than the girdle is thick.
        assert vmax > 0.0 > vmin
        assert (umax - umin) > (vmax - vmin)  # a brilliant is wider than deep

    def test_elevation_can_be_omitted(self, srb_diagram):
        gem, _diagram = srb_diagram
        lean = projection.build_diagram(gem, include_elevation=False)
        assert [view.key for view in lean.views] == ["crown", "pavilion"]


class TestGemCadPresentation:
    """The conventions verified against real printouts (DIAGRAM_NOTES.md)."""

    def _label(self, view, text):
        matches = [label for label in view.labels if label.text == text]
        assert len(matches) == 1, "expected one %r label, got %d" % (
            text, len(matches))
        return matches[0]

    def test_tier_labels_use_short_names(self, srb_diagram):
        _gem, diagram = srb_diagram
        texts = {label.text for label in diagram.view("crown").labels}
        assert texts == {"C1", "C2", "C3", "Table"}

    def test_the_labelled_facet_is_the_smallest_index(self, srb_diagram):
        """GemCad labels the facet with the smallest index, counting tooth N
        as tooth 0 — which is why the printout's ``96-12-24-...`` bezel tier
        is labelled at the *bottom* of the view."""
        _gem, diagram = srb_diagram
        crown = diagram.view("crown")
        # C2 bezels are cut at 96-12-...-84; tooth 96 == 0 sits at the bottom.
        assert IDX8_MAINS[-1] == 96
        c2 = self._label(crown, "C2")
        assert c2.u == pytest.approx(0.0, abs=1e-6)   # on the vertical axis
        assert c2.v < 0.0                             # below centre
        # C1 breaks start at tooth 3, one notch counter-clockwise of the
        # bottom, which on screen is to the *right*.
        c1 = self._label(crown, "C1")
        assert c1.u > 0.0 and c1.v < 0.0

    def test_pavilion_view_is_mirrored_like_gemcads_bottom_view(
            self, srb_diagram):
        """The DESIGN.md section 8 question. GemCad's Bottom view is drawn as
        if seen through the stone from the crown, so a given index lands at
        the same screen position in both round views: the P2 mains tier
        (96-12-...) is labelled straight below centre and P1 (03-09-...) below
        and to the *right*, exactly as in the crown view. A true view from -Z
        would put P1 to the left."""
        _gem, diagram = srb_diagram
        pavilion = diagram.view("pavilion")
        p2 = self._label(pavilion, "P2")
        assert p2.u == pytest.approx(0.0, abs=1e-6)
        assert p2.v < 0.0
        p1 = self._label(pavilion, "P1")
        assert p1.u > 0.0 and p1.v < 0.0

    def test_girdle_tier_is_labelled_outside_the_pavilion_view(
            self, srb_diagram):
        """Manual, verbatim: "Girdle facets are labeled outside the outline of
        the stone in the bottom view"."""
        _gem, diagram = srb_diagram
        assert not [label for label in diagram.view("crown").labels
                    if label.role == "girdle"]
        girdle = self._label(diagram.view("pavilion"), "G1")
        assert girdle.role == "girdle"
        outline_radius = max(
            math.hypot(*point) for segment in diagram.view("pavilion").outline
            for point in (segment.a, segment.b))
        assert math.hypot(girdle.u, girdle.v) > outline_radius

    def test_index_ring_places_the_id_tooth_at_the_bottom(self, srb_diagram):
        _gem, diagram = srb_diagram
        ring = diagram.view("crown").ring
        assert ring.gear == GEAR
        assert ring.id_index == GEAR
        assert len(ring.ticks) == GEAR                  # one tick per tooth
        labels = {index: (angle, text) for index, angle, text in ring.labels}
        assert len(labels) == 16                        # every 6th on a 96
        assert labels[GEAR][1] == "<96>"                # angle-bracketed ID
        # Bottom, then counter-clockwise: right, top, left.
        for index, expected in [(GEAR, (0.0, -1.0)), (24, (1.0, 0.0)),
                                (48, (0.0, 1.0)), (72, (-1.0, 0.0))]:
            point = model.ring_point(1.0, labels[index][0])
            assert point == pytest.approx(expected, abs=1e-9), index

    def test_both_round_views_carry_a_ring(self, srb_diagram):
        _gem, diagram = srb_diagram
        assert diagram.view("crown").ring is not None
        assert diagram.view("pavilion").ring is not None
        assert diagram.view("elevation").ring is None

    def test_clockwise_handedness_reverses_the_ring(self):
        """A negative .ASC gear means indices run clockwise on screen."""
        doc = FreeCAD.newDocument("srb_cw")
        try:
            gem = gem_feature.make_gem(doc, label="CW", index_gear=96,
                                       handedness=-1)
            assert gem.Handedness == "Clockwise"
            make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
            make_tier(gem, 90.0, 4.0, [24, 48, 72, 96], side="Pavilion",
                      tier_name="G")
            make_tier(gem, 42.0, 3.0, [24, 48, 72, 96], side="Pavilion",
                      tier_name="P")
            make_tier(gem, 0.0, 2.0, [], side="Crown", tier_name="T")
            doc.recompute()
            ring = projection.build_diagram(gem).view("crown").ring
            angles = {index: angle for index, angle in ring.ticks}
            # Tooth 96 still at the bottom, but tooth 24 now on the *left*.
            assert model.ring_point(1.0, angles[96]) == pytest.approx(
                (0.0, -1.0), abs=1e-9)
            assert model.ring_point(1.0, angles[24]) == pytest.approx(
                (-1.0, 0.0), abs=1e-9)
        finally:
            FreeCAD.closeDocument(doc.Name)


class TestReportBlocks:
    def test_size_data_matches_the_published_dimension_table(self, srb_diagram):
        _gem, diagram = srb_diagram
        rows = dict(diagram.blocks[1].rows)
        assert rows["L/W"] == "1.000"
        assert rows["H/W"] == "0.607"
        assert rows["P/W"] == "0.427"
        assert rows["C/W"] == "0.150"
        assert rows["Girdle/W"] == "0.030"

    def test_facet_data_matches_the_published_counts(self, srb_diagram):
        _gem, diagram = srb_diagram
        rows = dict(diagram.blocks[0].rows)
        assert rows["Pavilion facets"] == "24"
        assert rows["Girdle facets"] == "16"
        assert rows["Crown facets"] == "32+1"
        assert rows["Total facets"] == "73"
        assert rows["Pavilion tiers"] == "2"
        assert rows["Girdle tiers"] == "1"
        assert rows["Crown tiers"] == "3+1"
        assert rows["Total tiers"] == "7"

    def test_title_and_gear_metadata(self, srb_diagram):
        _gem, diagram = srb_diagram
        assert diagram.title == "Standard Round Brilliant"
        assert dict(diagram.blocks[2].rows)["Index gear"] == "96"


class TestEndToEnd:
    def test_gem_diagram_svg(self, srb_diagram):
        from freecad.lapidary.faceting import diagram as package
        gem, _diagram = srb_diagram
        out = package.gem_diagram_svg(gem)
        assert out.startswith("<?xml")
        assert "Standard Round Brilliant" in out
        for name in ("G1 girdle", "P1 breaks", "C3 stars"):
            assert name in out                  # tier table rows
        assert "&lt;96&gt;" in out              # index ring
        assert "Facet Data" in out and "Size Data" in out
        assert '<g id="view-elevation">' in out

    def test_angle_label_style(self, srb_diagram):
        from freecad.lapidary.faceting import diagram as package
        gem, _diagram = srb_diagram
        out = package.gem_diagram_svg(
            gem, label_style=package.LabelStyle.NAME_ANGLE)
        assert "40.68°" in out

    def test_cutting_sheet_can_embed_the_diagram(self, srb_diagram):
        """DESIGN.md section 4 item 6 + section 8: the sheet optionally
        carries the diagram, inlined so the file stays self-contained."""
        from freecad.lapidary.faceting import reports
        gem, _diagram = srb_diagram
        plain = reports.cutting_sheet_html(gem, reports.gem_report(gem))
        assert "<svg" not in plain

        embedded = reports.cutting_sheet_html(
            gem, reports.gem_report(gem), include_diagram=True)
        assert "Faceting diagram" in embedded
        assert embedded.count("<svg") == 1
        # Inlined, not linked, and no stray XML declaration mid-document.
        assert "<?xml" not in embedded
        assert "&lt;96&gt;" in embedded          # the index ring came along
        assert embedded.index("<svg") > embedded.index("<table")
        assert embedded.rstrip().endswith("</body></html>")

    def test_cutting_sheet_diagram_survives_a_gem_without_geometry(self):
        from freecad.lapidary.faceting import reports
        doc = FreeCAD.newDocument("sheet_empty")
        try:
            gem = gem_feature.make_gem(doc, label="Empty")
            html = reports.cutting_sheet_html(gem, include_diagram=True)
            assert "No solid geometry to diagram yet" in html
        finally:
            FreeCAD.closeDocument(doc.Name)

    def test_gem_without_geometry_yields_no_diagram(self):
        from freecad.lapidary.faceting import diagram as package
        doc = FreeCAD.newDocument("empty_gem")
        try:
            gem = gem_feature.make_gem(doc, label="Empty")
            assert package.build_diagram(gem) is None
            assert package.gem_diagram_svg(gem) is None
        finally:
            FreeCAD.closeDocument(doc.Name)
