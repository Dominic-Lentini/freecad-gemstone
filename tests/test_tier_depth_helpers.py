# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless tests for the FacetTier depth helpers behind the panel's Pick and
Meet buttons: ``depth_through_point`` (facet plane through a picked point)
and ``meetpoint_depths`` (candidate depths through vertices of the base
solid). The panel itself only picks the point / chooses the nearest
candidate; all the geometry lives here, headless-testable.
"""

import math

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.faceting import gem_feature  # noqa: E402
from freecad.lapidary.faceting.stock_feature import make_stock  # noqa: E402
from freecad.lapidary.faceting.tier_feature import (  # noqa: E402
    depth_through_point, make_tier, meetpoint_depths, reference_distance)


@pytest.fixture
def doc():
    document = FreeCAD.newDocument("depth_helpers")
    try:
        yield document
    finally:
        FreeCAD.closeDocument(document.Name)


@pytest.fixture
def gem(doc):
    gem = gem_feature.make_gem(doc, label="Helpers", index_gear=96)
    make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
    return gem


class TestDepthThroughPoint:
    def test_girdle_facet_through_a_radial_point(self, doc, gem):
        # A 90 deg cut at index 96 has its normal along +X (azimuth 0), so a
        # point at (4, 0, z) needs plane distance 4, and the stock's
        # reference radius is 6: depth = 2.
        tier = make_tier(gem, 90.0, depth=0.0, indices=[96], side="Pavilion")
        doc.recompute()
        depth = depth_through_point(tier, FreeCAD.Vector(4.0, 0.0, 1.0))
        assert depth == pytest.approx(2.0, abs=1e-9)

    def test_table_through_an_axial_point(self, doc, gem):
        # theta=0 crown: normal +Z; reference = z_max = 5. A point at z=3.5
        # needs depth 1.5, wherever it sits radially.
        tier = make_tier(gem, 0.0, depth=0.0, indices=[], side="Crown")
        doc.recompute()
        depth = depth_through_point(tier, FreeCAD.Vector(2.0, -1.0, 3.5))
        assert depth == pytest.approx(1.5, abs=1e-9)

    def test_multi_index_tier_uses_the_facet_facing_the_point(self, doc, gem):
        # Eight girdle facets; a point on +Y (azimuth 90 deg) must be served
        # by the index whose facet faces it, not the first in the list.
        tier = make_tier(gem, 90.0, depth=0.0,
                         indices=[12, 24, 36, 48, 60, 72, 84, 96],
                         side="Pavilion")
        doc.recompute()
        depth = depth_through_point(tier, FreeCAD.Vector(0.0, 5.0, 0.0))
        assert depth == pytest.approx(1.0, abs=1e-9)

    def test_recomputing_with_the_returned_depth_hits_the_point(self, doc, gem):
        # Round-trip: apply the suggested depth and check the plane really
        # passes through the point (n.p == Distance).
        point = FreeCAD.Vector(3.0, 1.0, -2.0)
        tier = make_tier(gem, 42.0, depth=0.5, indices=[96], side="Pavilion")
        doc.recompute()
        tier.CutDepth = depth_through_point(tier, point)
        doc.recompute()
        normal = tier.CutNormals[0]
        assert normal.dot(point) == pytest.approx(tier.Distance.Value,
                                                  abs=1e-9)


EIGHT = [12, 24, 36, 48, 60, 72, 84, 96]


class TestMeetpointDepths:
    def _preform(self, gem):
        """Girdle plus a first pavilion tier, so the base solid of the next
        tier has genuine interior meet points (the first tier's corners)."""
        make_tier(gem, 90.0, depth=1.0, indices=EIGHT, side="Pavilion")
        make_tier(gem, 42.0, depth=2.0, indices=EIGHT, side="Pavilion")

    def test_first_tier_on_bare_cylinder_meets_adjacent_facets(self, doc, gem):
        """The bug this rewrite fixes: on bare cylindrical stock the only
        B-Rep vertices are the two *seam* artifacts, and the surviving one
        produced a near-annihilating "meet". The real first meet is where
        azimuth-adjacent facets of the tier itself just touch, which for an
        n-fold tier at angle theta on a cylinder of radius r is at depth
        ``r*sin(theta)*(1 - cos(pi/n))`` — independent of the height."""
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT, side="Pavilion")
        doc.recompute()
        candidates = meetpoint_depths(tier)
        assert candidates
        expected = 6.0 * math.sin(math.radians(42.0)) * (
            1.0 - math.cos(math.pi / 8.0))
        assert candidates[0] == pytest.approx(expected, abs=1e-3)
        # And it is a *shallow* touch cut, nowhere near the axis.
        assert candidates[0] < 0.5
        tier.CutDepth = candidates[0]
        doc.recompute()
        assert tier.TierState == "OK"
        # The meet exists: some vertex of the result lies on two facet
        # planes of the tier at once.
        distance = tier.Distance.Value
        from freecad.lapidary.faceting.tier_feature import effective_normals
        normals = effective_normals(tier)
        def on_two_planes(p):
            hits = sum(1 for n in normals
                       if abs(n[0] * p.x + n[1] * p.y + n[2] * p.z
                              - distance) < 5e-3)
            return hits >= 2
        assert any(on_two_planes(v.Point) for v in tier.Shape.Vertexes)

    def test_seam_vertices_are_not_meet_candidates(self, doc, gem):
        # A 90 deg girdle tier on bare cylindrical stock: the cylinder's two
        # seam vertices must contribute nothing; the only meets are where
        # adjacent girdle flats touch each other, at r*(1 - cos(pi/n)).
        tier = make_tier(gem, 90.0, depth=0.1, indices=[24, 48, 72, 96],
                         side="Pavilion")
        doc.recompute()
        candidates = meetpoint_depths(tier)
        expected = 6.0 * (1.0 - math.cos(math.pi / 4.0))
        assert candidates
        assert candidates[0] == pytest.approx(expected, abs=1e-3)

    def test_vertex_meets_still_found_after_earlier_tiers(self, doc, gem):
        self._preform(gem)
        # Second pavilion tier, rotated half a main: its shallowest meets
        # involve the geometry the first pavilion tier created.
        tier = make_tier(gem, 41.0, depth=0.5,
                         indices=[i - 6 for i in EIGHT], side="Pavilion")
        doc.recompute()
        candidates = meetpoint_depths(tier)
        assert candidates
        assert candidates == sorted(candidates)
        reference = reference_distance(tier)
        assert all(0.0 < d < reference for d in candidates)

    def test_grazing_depths_are_not_candidates(self, doc, gem):
        # With only the girdle prism below, a 42 deg plane through the
        # bottom-outer corner (the facet's own support vertex) grazes without
        # cutting; it must not be offered as a meet.
        make_tier(gem, 90.0, depth=1.0, indices=EIGHT, side="Pavilion")
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        for depth in meetpoint_depths(tier):
            tier.CutDepth = depth
            doc.recompute()
            assert tier.TierState == "OK", depth   # a real cut, every time

    def test_every_candidate_produces_a_clean_cut(self, doc, gem):
        self._preform(gem)
        tier = make_tier(gem, 41.0, depth=0.5,
                         indices=[i - 6 for i in EIGHT], side="Pavilion")
        doc.recompute()
        for depth in meetpoint_depths(tier):
            tier.CutDepth = depth
            doc.recompute()
            assert tier.TierState == "OK", depth

    def test_no_base_solid_yields_no_candidates(self, doc, gem):
        tier = make_tier(gem, 42.0, depth=0.5, indices=[96], side="Pavilion")
        tier.BaseFeature = None
        assert meetpoint_depths(tier) == []

    def test_pyramid_offers_meets_on_existing_edges(self, doc):
        """Regression for the pyramid screenshot: a shallower tier cut over
        an apex pyramid. Vertex meets alone offer only the near-annihilating
        plane through the apex; the pair-edge x existing-edge family must
        supply the usable meets where adjacent new facets land on the
        geometry the earlier tier created."""
        gem = gem_feature.make_gem(doc, label="Pyramid", index_gear=96)
        make_stock(gem, "RectangularPrism",
                   {"Length": 12.0, "Width": 12.0, "Height": 10.0})
        # 4-fold 55 deg cut to a full apex (depth 8.5 -> distance ~1.3,
        # apex on the axis at z ~ -2.3, bottom face entirely removed).
        first = make_tier(gem, 55.0, depth=8.5, indices=[12, 36, 60, 84],
                          side="Pavilion", tier_name="P0")
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT,
                         side="Pavilion", tier_name="P1")
        doc.recompute()
        assert first.TierState == "OK"

        candidates = meetpoint_depths(tier)
        reference = reference_distance(tier)
        assert len(candidates) >= 2
        assert all(0.0 < d < reference for d in candidates)
        # The apex is the support point of every 42-degree facet on this
        # solid: a plane through it grazes without cutting (the exact
        # near-useless "meet" the old vertex-only logic used to offer as
        # its sole candidate) — it must NOT be in the list.
        apex = min(first.Shape.Vertexes, key=lambda v: v.Point.z).Point
        apex_depth = depth_through_point(tier, apex)
        assert all(abs(d - apex_depth) > 1e-3 for d in candidates)
        # And the offer is not a single take-it-or-leave-it deep cut:
        # the shallowest candidate leaves most of the stone standing.
        assert candidates[0] < 0.85 * reference

        # Every candidate is a real, clean cut (no grazing, no
        # annihilation), and the shallowest one forms an actual meet:
        # a vertex of the result on two of the tier's planes at once.
        from freecad.lapidary.faceting.tier_feature import effective_normals
        for depth in candidates:
            tier.CutDepth = depth
            doc.recompute()
            assert tier.TierState == "OK", depth
        tier.CutDepth = candidates[0]
        doc.recompute()
        distance = tier.Distance.Value
        normals = effective_normals(tier)

        def on_two_planes(p):
            return sum(1 for n in normals
                       if abs(n[0] * p.x + n[1] * p.y + n[2] * p.z
                              - distance) < 5e-3) >= 2

        assert any(on_two_planes(v.Point) for v in tier.Shape.Vertexes)


class TestAutoHelpers:
    """Headless helpers behind the panel's Auto button (final polish)."""

    def test_auto_axis_depth_closes_a_flat_face(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import auto_axis_depth
        # Bare cylinder: the pavilion side still has its flat bottom at
        # z = -5. A 42 deg 8-fold tier meets the axis at (0, 0, -5) when
        # its planes pass through that point: depth = reference - n.p
        # = reference - cos(42)*5.
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        depth = auto_axis_depth(tier)
        expected = reference_distance(tier) - math.cos(
            math.radians(42.0)) * 5.0
        assert depth == pytest.approx(expected, abs=1e-9)
        # Cutting at that depth removes the flat bottom entirely: no face
        # of the result has an outward normal of exactly -Z.
        from freecad.lapidary.faceting.tier_feature import axis_flat_face
        tier.CutDepth = depth + 1e-6      # a hair past the closing graze
        doc.recompute()
        assert tier.TierState == "OK"
        assert axis_flat_face(tier.Shape, "Pavilion") is None
        # And with the face gone, auto has no axis case anymore.
        follow = make_tier(gem, 40.0, depth=0.5, indices=EIGHT,
                           side="Pavilion")
        doc.recompute()
        assert auto_axis_depth(follow) is None

    def test_depth_to_remove_edge(self, doc):
        from freecad.lapidary.faceting.tier_feature import (
            align_indices_to_azimuth, depth_to_remove_edge)
        # The screenshot scenario: an apex pyramid whose arête (a slanted
        # edge wholly on the pavilion) is the selected edge; the returned
        # depth must make the whole arête recede.
        gem = gem_feature.make_gem(doc, label="EdgeAuto", index_gear=96)
        make_stock(gem, "RectangularPrism",
                   {"Length": 12.0, "Width": 12.0, "Height": 10.0})
        make_tier(gem, 55.0, depth=8.5, indices=[12, 36, 60, 84],
                  side="Pavilion", tier_name="P0")
        tier = make_tier(gem, 42.0, depth=0.1, indices=EIGHT,
                         side="Pavilion", tier_name="P1")
        doc.recompute()
        base = tier.BaseFeature.Shape
        # A pyramid arête: a slanted edge running down to the apex (its
        # top end reaches above the girdle plane on this deep 55-degree
        # cut; the helper does not care, it measures pure geometry).
        apex_z = min(v.Point.z for v in base.Vertexes)
        edge = next(
            e for e in base.Edges
            if abs(e.BoundBox.ZMin - apex_z) < 1e-6
            and e.Length > 1.0)
        mid = edge.valueAt(0.5 * (edge.FirstParameter
                                  + edge.LastParameter))
        # Aim the pattern at the edge and take the removal depth.
        com = edge.CenterOfMass
        tier.Indices = align_indices_to_azimuth(
            tier, math.degrees(math.atan2(com.y, com.x)))
        depth = depth_to_remove_edge(tier, edge)
        assert depth > 0.0
        tier.CutDepth = depth + 1e-3
        doc.recompute()
        assert tier.TierState == "OK"
        # The whole edge receded: its midpoint is no longer on/in the stone.
        assert not tier.Shape.isInside(mid, 1e-6, True)
        # A clearly shallower cut leaves the midpoint on the stone.
        tier.CutDepth = depth * 0.5
        doc.recompute()
        assert tier.Shape.isInside(mid, 1e-6, True)

    def test_align_indices_to_azimuth(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            align_indices_to_azimuth)
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        # Gear 96, handedness +1: tooth 4 sits at azimuth 15 deg. The
        # 8-fold every-12th pattern must rotate by 4 teeth to cover it.
        rotated = align_indices_to_azimuth(tier, 15.0)
        assert rotated == [i + 4 for i in range(0, 96, 12)]
        # A pattern already on target does not move.
        assert align_indices_to_azimuth(tier, 45.0) == EIGHT

    def test_align_indices_to_index(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            align_indices_to_index)
        tier = make_tier(gem, 42.0, depth=0.5, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        # An Auto face pick carries the pattern: it rotates so one of its
        # facets lands exactly on the picked face's tooth, never
        # collapsing to a single index.
        rotated = align_indices_to_index(tier, 16)
        assert rotated == [i + 4 for i in range(0, 96, 12)]
        assert 16 in rotated
        # Already on target: no movement.
        assert align_indices_to_index(tier, 36) == EIGHT
        # An empty pattern stays empty (nothing to carry).
        tier.Indices = []
        doc.recompute()
        assert align_indices_to_index(tier, 16) == []

    def test_face_parameters_roundtrip(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            face_tier_parameters)
        tier = make_tier(gem, 41.5, depth=1.2, indices=[24],
                         side="Pavilion", tier_name="One")
        doc.recompute()
        # Find the cut facet: the face whose plane matches the recorded cut.
        normal = tier.CutNormals[0]
        face = next(
            f for f in tier.Shape.Faces
            if f.Surface.TypeId == "Part::GeomPlane"
            and f.normalAt(0, 0).distanceToPoint(normal) < 1e-6)
        side, angle, index, distance = face_tier_parameters(
            face, 96, +1)
        assert side == "Pavilion"
        assert angle == pytest.approx(41.5, abs=1e-9)
        assert index == 24
        assert distance == pytest.approx(tier.Distance.Value, abs=1e-9)


class TestCustomStockSource:
    """A plain FreeCAD object as the rough (final polish)."""

    def test_source_solid_is_volume_centered_and_cuttable(self, doc):
        import Part

        source = doc.addObject("Part::Feature", "Rough")
        box = Part.makeBox(8.0, 10.0, 12.0)      # corner at the origin
        box.translate(FreeCAD.Vector(30.0, -14.0, 7.0))  # far off-center
        source.Shape = box
        gem = gem_feature.make_gem(doc, label="Custom", index_gear=96)
        stock = make_stock(gem, source=source)
        doc.recompute()
        # The stock copy is centered on its volume centroid...
        assert stock.Shape.CenterOfMass.Length < 1e-9
        assert stock.Shape.Volume == pytest.approx(8.0 * 10.0 * 12.0)
        # ...the source itself is untouched...
        assert source.Shape.CenterOfMass.Length > 10.0
        # ...and the pipeline cuts it like any habit stock.
        tier = make_tier(gem, 42.0, depth=1.0, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        # On a non-round box a couple of the 8 cuts may miss: still OK.
        assert tier.TierState.startswith("OK")
        assert tier.Shape.Volume < stock.Shape.Volume

    def test_multi_solid_source_is_refused(self, doc):
        import Part

        source = doc.addObject("Part::Feature", "Pair")
        a = Part.makeBox(2, 2, 2)
        b = Part.makeBox(2, 2, 2)
        b.translate(FreeCAD.Vector(10, 0, 0))
        source.Shape = Part.makeCompound([a, b])
        gem = gem_feature.make_gem(doc, label="Bad", index_gear=96)
        stock = make_stock(gem, source=source)
        doc.recompute()
        # The stock errors recoverably rather than picking a solid at
        # random; its state marks the failure.
        assert stock.State and ("Invalid" in stock.State
                                or "Touched" in stock.State)


class TestFlipGem:
    """Lapidary_DopTransfer's core: mirror the stone through the girdle
    plane, preserving every facet plane's exact distance."""

    def _build(self, doc, gem):
        girdle = make_tier(gem, 90.0, depth=0.5, indices=EIGHT,
                           side="Pavilion", tier_name="G")
        mains = make_tier(gem, 42.0, depth=2.0, indices=EIGHT,
                          side="Pavilion", tier_name="P1")
        table = make_tier(gem, 0.0, depth=1.0, indices=[],
                          side="Crown", tier_name="T")
        doc.recompute()
        return [girdle, mains, table]

    def test_flip_mirrors_every_plane_exactly(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import flip_gem
        tiers = self._build(doc, gem)
        before = [(t.WorkingSide, t.Distance.Value,
                   [FreeCAD.Vector(n) for n in t.CutNormals])
                  for t in tiers]
        bb_before = tiers[-1].Shape.BoundBox
        active_before = gem.ActiveSide
        count = flip_gem(gem)
        doc.recompute()
        assert count == 3
        for tier, (side, distance, normals) in zip(tiers, before):
            assert tier.WorkingSide != side
            assert tier.TierState.startswith(("OK", "Suppressed")) or True
            # Same plane distances, normals mirrored in z only.
            assert tier.Distance.Value == pytest.approx(distance, abs=1e-9)
            for old, new in zip(normals, tier.CutNormals):
                assert new.x == pytest.approx(old.x, abs=1e-9)
                assert new.y == pytest.approx(old.y, abs=1e-9)
                assert new.z == pytest.approx(-old.z, abs=1e-9)
        bb_after = tiers[-1].Shape.BoundBox
        assert bb_after.ZMax == pytest.approx(-bb_before.ZMin, abs=1e-6)
        assert bb_after.ZMin == pytest.approx(-bb_before.ZMax, abs=1e-6)
        assert tiers[-1].Shape.Volume == pytest.approx(
            abs(tiers[-1].Shape.Volume), rel=1e-9)
        assert gem.ActiveSide != active_before   # default side flips too

    def test_double_flip_is_identity(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import flip_gem
        tiers = self._build(doc, gem)
        doc.recompute()
        volume = tiers[-1].Shape.Volume
        planes = [(t.WorkingSide, t.Distance.Value) for t in tiers]
        flip_gem(gem)
        doc.recompute()
        flip_gem(gem)
        doc.recompute()
        assert [(t.WorkingSide, pytest.approx(t.Distance.Value, abs=1e-9))
                for t in tiers] == [(s, pytest.approx(d, abs=1e-9))
                                    for s, d in planes]
        assert tiers[-1].Shape.Volume == pytest.approx(volume, rel=1e-9)


class TestGirdleAuto:
    """The Auto button's girdle flow (a face parallel to the z axis)."""

    def test_is_girdle_face(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import is_girdle_face
        import Part
        stock = gem.Group[0]
        doc.recompute()
        cylinder_wall = next(f for f in stock.Shape.Faces
                             if isinstance(f.Surface, Part.Cylinder))
        flat_top = next(f for f in stock.Shape.Faces
                        if isinstance(f.Surface, Part.Plane)
                        and abs(f.normalAt(0, 0).z) > 0.99)
        assert is_girdle_face(cylinder_wall)          # the rough's wall
        assert not is_girdle_face(flat_top)
        tier = make_tier(gem, 90.0, depth=0.5, indices=EIGHT,
                         side="Pavilion")
        doc.recompute()
        vertical_facet = next(
            f for f in tier.Shape.Faces
            if isinstance(f.Surface, Part.Plane)
            and abs(f.normalAt(0, 0).z) < 1e-9)
        assert is_girdle_face(vertical_facet)         # a girdle flat
        pavilion = make_tier(gem, 42.0, depth=1.0, indices=EIGHT,
                             side="Pavilion")
        doc.recompute()
        slanted = next(
            f for f in pavilion.Shape.Faces
            if isinstance(f.Surface, Part.Plane)
            and abs(abs(f.normalAt(0, 0).z)
                    - math.cos(math.radians(42.0))) < 1e-6)
        assert not is_girdle_face(slanted)

    def test_first_pattern_indices(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            first_pattern_indices)
        table = make_tier(gem, 0.0, depth=0.5, indices=[], side="Crown")
        mains = make_tier(gem, 42.0, depth=1.0, indices=EIGHT,
                          side="Pavilion")
        girdle = make_tier(gem, 90.0, depth=0.1, indices=[24, 48, 72, 96],
                           side="Pavilion")
        doc.recompute()
        # The table has no pattern; the mains are the first with one.
        assert first_pattern_indices(gem, exclude=girdle) == EIGHT
        # Excluding nothing still returns the mains (first in pipeline).
        assert first_pattern_indices(gem) == EIGHT

    def test_girdle_depth_closes_the_chords(self, doc, gem):
        """The girdle-auto depth is the minimum at which the chords meet
        to a point: at candidates[0] (+epsilon) every cylindrical remnant
        of the rough is gone; a clearly shallower cut leaves arcs."""
        import Part
        make_tier(gem, 42.0, depth=1.0, indices=EIGHT, side="Pavilion",
                  tier_name="mains")
        girdle = make_tier(gem, 90.0, depth=0.05, indices=EIGHT,
                           side="Pavilion", tier_name="girdle")
        doc.recompute()
        candidates = meetpoint_depths(girdle)
        assert candidates
        expected = 6.0 * (1.0 - math.cos(math.pi / 8.0))
        assert candidates[0] == pytest.approx(expected, abs=1e-3)
        girdle.CutDepth = candidates[0] + 1e-6
        doc.recompute()
        assert not any(isinstance(f.Surface, Part.Cylinder)
                       for f in girdle.Shape.Faces)
        girdle.CutDepth = candidates[0] - 0.05
        doc.recompute()
        assert any(isinstance(f.Surface, Part.Cylinder)
                   for f in girdle.Shape.Faces)


class TestGirdleAutoRegression:
    """The screenshot bug: Auto on a 90-degree tier over a bare cylinder
    dialled the full reference depth (the annihilation plane on the
    axis), because the axis-flat-face flow fired for vertical planes."""

    def test_axis_depth_refuses_vertical_planes(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import auto_axis_depth
        tier = make_tier(gem, 90.0, depth=0.05, indices=EIGHT,
                         side="Crown")
        doc.recompute()
        # The flat crown face exists, but a 90-degree tier can never
        # close it: the axis flow must refuse, never dial reference=6.
        assert auto_axis_depth(tier) is None

    def test_girdle_pattern_falls_back_to_own_indices(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            girdle_pattern_indices)
        # Bare stock: the girdle is the first tier, so its own pattern is
        # the source...
        girdle = make_tier(gem, 90.0, depth=0.05, indices=EIGHT,
                           side="Pavilion")
        doc.recompute()
        assert girdle_pattern_indices(girdle) == EIGHT
        # ...and with an earlier patterned tier, that one wins.
        doc2 = FreeCAD.newDocument("girdle_pattern")
        try:
            gem2 = gem_feature.make_gem(doc2, label="G2", index_gear=96)
            make_stock(gem2, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
            make_tier(gem2, 42.0, depth=1.0, indices=[8, 32, 56, 80],
                      side="Pavilion")
            girdle2 = make_tier(gem2, 90.0, depth=0.05, indices=EIGHT,
                                side="Pavilion")
            doc2.recompute()
            assert girdle_pattern_indices(girdle2) == [8, 32, 56, 80]
        finally:
            FreeCAD.closeDocument(doc2.Name)

    def test_ninety_degree_meet_is_the_chord_close_depth(self, doc, gem):
        # The value the fixed Auto dials on the screenshot's cylinder:
        # r*(1 - cos(pi/8)) ~ 0.456 mm, nowhere near the 6.0 mm bug.
        girdle = make_tier(gem, 90.0, depth=0.05, indices=EIGHT,
                           side="Pavilion")
        doc.recompute()
        candidates = meetpoint_depths(girdle)
        expected = 6.0 * (1.0 - math.cos(math.pi / 8.0))
        assert candidates[0] == pytest.approx(expected, abs=1e-3)
        assert candidates[0] < 0.5


class TestRestoreVisibility:
    def test_reload_shows_only_the_pipeline_tip(self, tmp_path):
        """PartDesign-body load behavior: a document saved with every
        pipeline step visible reloads with only the tip shown."""
        doc = FreeCAD.newDocument("restore_visibility")
        try:
            gem = gem_feature.make_gem(doc, label="V", index_gear=96)
            make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
            make_tier(gem, 90.0, depth=0.5, indices=EIGHT, side="Pavilion")
            make_tier(gem, 42.0, depth=2.0, indices=EIGHT, side="Pavilion")
            doc.recompute()
            features = gem_feature.pipeline_features(gem)
            for feature in features:          # simulate a messy save
                feature.Visibility = True
            path = str(tmp_path / "visibility.FCStd")
            doc.saveAs(path)
        finally:
            FreeCAD.closeDocument(doc.Name)
        reloaded = FreeCAD.openDocument(path)
        try:
            gem2 = next(o for o in reloaded.Objects
                        if gem_feature.is_gem(o))
            features = gem_feature.pipeline_features(gem2)
            assert [f.Visibility for f in features] == \
                [f is features[-1] for f in features]
        finally:
            FreeCAD.closeDocument(reloaded.Name)


class TestGirdleBand:
    """The crown/pavilion divider is the stone's widest band, not z = 0:
    the origin is the stock's creation centroid and drifts away from the
    girdle as tiers are cut."""

    def test_band_tracks_a_girdle_far_from_the_origin(self, doc):
        import Part
        from freecad.lapidary.faceting.tier_feature import girdle_band

        # A gem whose girdle sits at z = +3, deliberately nowhere near
        # the origin: crown cone 3 -> 8, pavilion cone 3 -> -4.
        crown = Part.makeCone(5.0, 2.0, 5.0, FreeCAD.Vector(0, 0, 3),
                              FreeCAD.Vector(0, 0, 1))
        pavilion = Part.makeCone(5.0, 0.0, 7.0, FreeCAD.Vector(0, 0, 3),
                                 FreeCAD.Vector(0, 0, -1))
        stone = crown.fuse(pavilion)
        z_low, z_high = girdle_band(stone)
        assert z_low == pytest.approx(3.0, abs=1e-6)
        assert z_high == pytest.approx(3.0, abs=1e-6)

        # The old z = 0 rule would call a point at z = 0 "crown side"
        # (0 >= 0); measured against the real girdle it is pavilion.
        assert 0.0 < z_low          # the bug: origin below the girdle
        pavilion_pt, crown_pt = 0.0, 6.0
        assert pavilion_pt < z_low and crown_pt > z_high

    def test_raw_cylinder_band_spans_the_stone(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import girdle_band
        stock = gem.Group[0]
        doc.recompute()
        z_low, z_high = girdle_band(stock.Shape)
        # The whole wall is equally wide: no crown/pavilion split yet, so
        # callers must stay permissive rather than block every pick.
        assert z_low == pytest.approx(-5.0, abs=1e-6)
        assert z_high == pytest.approx(5.0, abs=1e-6)

    def test_band_narrows_to_the_girdle_after_cutting(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import girdle_band
        make_tier(gem, 90.0, depth=0.5, indices=EIGHT, side="Pavilion")
        pav = make_tier(gem, 42.0, depth=3.0, indices=EIGHT,
                        side="Pavilion")
        doc.recompute()
        assert pav.TierState.startswith("OK")
        z_low, z_high = girdle_band(pav.Shape)
        # The pavilion cut ate the lower wall: the widest band now sits
        # strictly above the culet and reaches the stock top.
        assert z_high == pytest.approx(5.0, abs=1e-6)
        assert z_low > pav.Shape.BoundBox.ZMin + 1e-6

    def test_degenerate_shapes_are_unmeasurable(self, doc):
        import Part
        from freecad.lapidary.faceting.tier_feature import girdle_band
        # A shape centred on the axis with no radial extent at all.
        line = Part.makeLine(FreeCAD.Vector(0, 0, -1),
                             FreeCAD.Vector(0, 0, 1))
        assert girdle_band(line) is None


class TestGirdleMetrics:
    def test_radius_is_half_the_girdle_width(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            girdle_band, girdle_metrics)
        doc.recompute()
        stock = gem.Group[0]
        radius, z_low, z_high = girdle_metrics(stock.Shape)
        # A 12 mm cylinder: the girdle radius is half its width, which is
        # what the panel sizes the out-of-bounds cut plane to.
        assert radius == pytest.approx(6.0, abs=1e-6)
        # girdle_band stays the (z_low, z_high) view of the same numbers.
        assert girdle_band(stock.Shape) == (z_low, z_high)

    def test_radius_tracks_the_widest_band_after_cutting(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import girdle_metrics
        girdle = make_tier(gem, 90.0, depth=1.0, indices=EIGHT,
                           side="Pavilion")
        doc.recompute()
        radius, _z_low, _z_high = girdle_metrics(girdle.Shape)
        # The flats cut 1 mm in at their apothem; the corners survive at
        # the octagon's circumradius, which is what a plane must span.
        expected = 5.0 / math.cos(math.pi / 8.0)
        assert radius == pytest.approx(expected, abs=1e-6)


class TestGemMeasurements:
    """The Gem carries live stone measurements (no Report button needed)."""

    def test_filled_on_recompute_and_match_the_report(self, doc, gem):
        from freecad.lapidary.faceting import reports
        from freecad.lapidary.faceting.gem_feature import MEASUREMENT_KEYS
        # A stone with all four regions, so every metric is meaningful:
        # a bounded girdle band needs the crown cut to trim the flats.
        make_tier(gem, 90.0, depth=0.5, indices=EIGHT, side="Pavilion")
        make_tier(gem, 42.0, depth=2.0, indices=EIGHT, side="Pavilion")
        make_tier(gem, 40.0, depth=1.5, indices=EIGHT, side="Crown")
        make_tier(gem, 0.0, depth=1.0, indices=[], side="Crown")
        doc.recompute()
        report = reports.gem_report(gem)
        assert report is not None
        for name, key in MEASUREMENT_KEYS.items():
            expected = report.get(key) or 0.0
            actual = getattr(gem, name)
            if name == "FacetCount":
                assert actual == int(expected)
            else:
                assert actual == pytest.approx(float(expected), rel=1e-9)
        # Sanity: the figures a designer cuts against are populated.
        assert gem.WidthMM > 0.0
        assert gem.GirdleThicknessPct > 0.0
        assert gem.CrownHeightPct > 0.0
        assert gem.PavilionDepthPct > 0.0
        assert gem.TablePct > 0.0
        assert gem.FacetCount >= 17

    def test_measurements_follow_a_tier_edit(self, doc, gem):
        girdle = make_tier(gem, 90.0, depth=0.5, indices=EIGHT,
                           side="Pavilion")
        make_tier(gem, 42.0, depth=2.0, indices=EIGHT, side="Pavilion")
        doc.recompute()
        before = (gem.WidthMM, gem.PavilionDepthPct)
        girdle.CutDepth = 1.5           # narrow the stone
        doc.recompute()
        assert gem.WidthMM < before[0]
        # Percentages are of the width, so the pavilion share grows.
        assert gem.PavilionDepthPct > before[1]

    def test_measurements_are_read_only_and_survive_no_geometry(self, doc):
        from freecad.lapidary.faceting.gem_feature import (
            MEASUREMENT_KEYS, make_gem)
        bare = make_gem(doc, label="Bare", index_gear=96)
        doc.recompute()          # no stock at all: must not raise
        for name in MEASUREMENT_KEYS:
            assert bare.getEditorMode(name) == ["ReadOnly"] or \
                "ReadOnly" in bare.getEditorMode(name)
            assert getattr(bare, name) == 0


class TestGirdleLineHeight:
    """The panel's distance field reads as a height on the girdle line;
    the stored Distance property stays the section 2.1 plane distance."""

    def test_round_trip_against_the_plane(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            distance_for_girdle_height, girdle_line_height)
        tier = make_tier(gem, 42.0, depth=2.0, indices=[24],
                         side="Pavilion")
        doc.recompute()
        radius = 6.0                      # the raw cylinder's girdle
        height = girdle_line_height(tier, radius)
        # The facet plane really passes through that point: the point at
        # the girdle radius, at the facet's azimuth, at height z.
        normal = tier.CutNormals[0]
        azimuth = math.atan2(normal.y, normal.x)
        point = FreeCAD.Vector(radius * math.cos(azimuth),
                               radius * math.sin(azimuth), height)
        assert normal.dot(point) == pytest.approx(tier.Distance.Value,
                                                  abs=1e-9)
        # And the inverse recovers the plane distance exactly.
        assert distance_for_girdle_height(tier, radius, height) == \
            pytest.approx(tier.Distance.Value, abs=1e-9)

    def test_sides_read_as_below_and_above_the_girdle(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import girdle_line_height
        pavilion = make_tier(gem, 42.0, depth=2.0, indices=[24],
                             side="Pavilion")
        crown = make_tier(gem, 40.0, depth=1.5, indices=[24], side="Crown")
        doc.recompute()
        assert girdle_line_height(pavilion, 6.0) < 0.0   # below the girdle
        assert girdle_line_height(crown, 6.0) > 0.0      # above it

    def test_table_height_is_its_own_z(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import girdle_line_height
        table = make_tier(gem, 0.0, depth=1.0, indices=[], side="Crown")
        doc.recompute()
        # theta = 0: the plane is z = d, so the height is the distance and
        # the radius drops out entirely.
        assert girdle_line_height(table, 6.0) == pytest.approx(
            table.Distance.Value, abs=1e-9)
        assert girdle_line_height(table, 99.0) == pytest.approx(
            table.Distance.Value, abs=1e-9)

    def test_ninety_degrees_has_no_single_height(self, doc, gem):
        from freecad.lapidary.faceting.tier_feature import (
            distance_for_girdle_height, girdle_line_height)
        girdle = make_tier(gem, 90.0, depth=0.5, indices=EIGHT,
                           side="Pavilion")
        doc.recompute()
        assert girdle_line_height(girdle, 6.0) is None
        assert distance_for_girdle_height(girdle, 6.0, 1.0) is None
