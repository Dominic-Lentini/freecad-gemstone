# SPDX-License-Identifier: LGPL-2.1-or-later
"""Polytope construction, validation, and convex-ray-walk golden tests
(DESIGN_OPTICS.md section 3).

The walk tests use hand-verified bounce sequences through a cube and a
regular octahedron; every expected number below is derived in a comment.
Pure-numpy tests run without FreeCAD; extraction tests skip without it.
"""

import math

import numpy as np
import pytest

from freecad.lapidary.optics import polytope as pt


SQ3 = math.sqrt(3.0)


class TestConstruction:
    def test_cube_vertices(self):
        cube = pt.cube(1.0)
        verts = cube.vertices()
        assert verts.shape == (8, 3)
        # All 8 sign combinations of (+-1, +-1, +-1).
        assert sorted(map(tuple, np.round(verts, 12))) == sorted(
            (x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0)
            for z in (-1.0, 1.0))
        assert cube.bounding_radius() == pytest.approx(math.sqrt(3.0))

    def test_octahedron_vertices(self):
        octa = pt.octahedron(1.0)
        verts = octa.vertices()
        assert verts.shape == (6, 3)
        assert octa.bounding_radius() == pytest.approx(1.0)

    def test_contains(self):
        cube = pt.cube(1.0)
        inside, outside, on_face = (0.5, -0.2, 0.9), (1.5, 0, 0), (1.0, 0, 0)
        assert list(cube.contains([inside, outside, on_face])) == [
            True, False, True]

    def test_rejects_non_unit_normals(self):
        with pytest.raises(ValueError, match="unit"):
            pt.Polytope([[2.0, 0.0, 0.0]], [1.0])

    def test_empty_polytope_refused(self):
        # Two opposing half-spaces with negative gap bound no volume.
        n = np.array([[1.0, 0, 0], [-1.0, 0, 0],
                      [0, 1.0, 0], [0, -1.0, 0]])
        p = pt.Polytope(n, np.array([1.0, -2.0, 1.0, 1.0]))
        with pytest.raises(pt.PolytopeError, match="no volume"):
            p.bounding_radius()


class TestCubeWalk:
    """Golden walks through the unit cube [-1, 1]^3.

    Face order (see polytope.cube): 0:+X 1:-X 2:+Y 3:-Y 4:+Z 5:-Z.
    """

    def setup_method(self):
        self.cube = pt.cube(1.0)

    def test_entry_straight_down(self):
        # From (0.25, 0, 5) along -Z: crosses z=+1 at t = 5 - 1 = 4.
        hit, t_in, face_in = self.cube.entry_hits([[0.25, 0.0, 5.0]],
                                                  [[0.0, 0.0, -1.0]])
        assert bool(hit[0])
        assert t_in[0] == pytest.approx(4.0)
        assert face_in[0] == 4  # +Z face

    def test_miss_beside_the_cube(self):
        hit, _t, _f = self.cube.entry_hits([[2.5, 0.0, 5.0]],
                                           [[0.0, 0.0, -1.0]])
        assert not bool(hit[0])

    def test_miss_pointing_away(self):
        hit, _t, _f = self.cube.entry_hits([[0.0, 0.0, 5.0]],
                                           [[0.0, 0.0, 1.0]])
        assert not bool(hit[0])

    def test_parallel_ray_outside_slab_misses(self):
        # Travels parallel to the top face, above it: never enters.
        hit, _t, _f = self.cube.entry_hits([[-5.0, 0.0, 1.5]],
                                           [[1.0, 0.0, 0.0]])
        assert not bool(hit[0])

    def test_exit_from_center(self):
        # From the origin along +X: exits x=+1 at t=1.
        t_out, face_out = self.cube.exit_hits([[0.0, 0.0, 0.0]],
                                              [[1.0, 0.0, 0.0]])
        assert t_out[0] == pytest.approx(1.0)
        assert face_out[0] == 0

    def test_two_bounce_sequence(self):
        # Hand-derived: from the origin along (0.8, 0, -0.6):
        #   t to x=+1 is 1/0.8 = 1.25;  t to z=-1 is 1/0.6 = 1.666..;
        #   so the first exit is +X (face 0) at (1, 0, -0.75).
        # Mirror there (normal +X): direction becomes (-0.8, 0, -0.6):
        #   t to z=-1 is 0.25/0.6 = 0.41666..;  t to x=-1 is 2/0.8 = 2.5;
        #   so the second exit is -Z (face 5) at (2/3, 0, -1).
        o = np.array([[0.0, 0.0, 0.0]])
        v = np.array([[0.8, 0.0, -0.6]])
        t1, f1 = self.cube.exit_hits(o, v)
        assert f1[0] == 0
        assert t1[0] == pytest.approx(1.25)
        p1 = o + t1[:, None] * v
        assert p1[0] == pytest.approx([1.0, 0.0, -0.75])
        n1 = self.cube.normals[f1[0]]
        v2 = v - 2.0 * (v @ n1)[:, None] * n1
        assert v2[0] == pytest.approx([-0.8, 0.0, -0.6])
        t2, f2 = self.cube.exit_hits(p1 - 1e-12 * n1, v2)
        assert f2[0] == 5
        assert t2[0] == pytest.approx(0.25 / 0.6)
        p2 = (p1 - 1e-12 * n1) + t2[:, None] * v2
        assert p2[0] == pytest.approx([2.0 / 3.0, 0.0, -1.0], abs=1e-9)


class TestOctahedronWalk:
    """Golden walk through the regular octahedron |x|+|y|+|z| <= 1.

    Face order (see polytope.octahedron, sign product order):
    0:(+,+,+) 1:(+,+,-) 2:(+,-,+) 3:(+,-,-) 4:(-,+,+) 5:(-,+,-)
    6:(-,-,+) 7:(-,-,-), each plane (sx*x + sy*y + sz*z)/sqrt(3) = 1/sqrt(3).
    """

    def setup_method(self):
        self.octa = pt.octahedron(1.0)

    def test_three_event_sequence(self):
        # Hand-derived, ray from (0.4, 0.12, 5) along -Z:
        # Entry: the top faces hit the vertical line at z = 1 -+ x -+ y;
        #   the *largest* t (deepest plane crossing) is face 0 (+,+,+) at
        #   z = 1 - 0.4 - 0.12 = 0.48, t = 5 - 0.48 = 4.52.
        o = np.array([[0.4, 0.12, 5.0]])
        v = np.array([[0.0, 0.0, -1.0]])
        hit, t_in, face_in = self.octa.entry_hits(o, v)
        assert bool(hit[0])
        assert face_in[0] == 0
        assert t_in[0] == pytest.approx(4.52)
        p0 = o + t_in[:, None] * v
        assert p0[0] == pytest.approx([0.4, 0.12, 0.48])

        # Continue straight down from the entry point (as after an
        # undeviated refraction): the first bottom face crossed is face 1
        # (+,+,-) where x + y - z = 1, i.e. z = 0.4 + 0.12 - 1 = -0.48,
        # so t = 0.48 - (-0.48) = 0.96.
        t1, f1 = self.octa.exit_hits(p0, v)
        assert f1[0] == 1
        assert t1[0] == pytest.approx(0.96)
        p1 = p0 + t1[:, None] * v
        assert p1[0] == pytest.approx([0.4, 0.12, -0.48])

        # Mirror off face 1's normal (1, 1, -1)/sqrt(3):
        #   v.n = 1/sqrt(3), v' = v - 2(v.n)n = (-2/3, -2/3, -1/3).
        n1 = self.octa.normals[f1[0]]
        v2 = v - 2.0 * (v @ n1)[:, None] * n1
        assert v2[0] == pytest.approx([-2 / 3, -2 / 3, -1 / 3])

        # Next exit, hand-computed over all faces with n.v' > 0:
        #   face 3 (+,-,-): t = 0.72;  face 7 (-,-,-): t = 0.624;
        #   face 6 (-,-,+): t = 2;     face 5 (-,+,-): t = 2.4;
        # argmin -> face 7 at t = 0.624, landing at
        #   (0.4, 0.12, -0.48) + 0.624 * v' = (-0.016, -0.296, -0.688)
        # (check: 0.016 + 0.296 + 0.688 = 1 on face -x - y - z = 1).
        t2, f2 = self.octa.exit_hits(p1 - 1e-12 * n1, v2)
        assert f2[0] == 7
        assert t2[0] == pytest.approx(0.624)
        p2 = (p1 - 1e-12 * n1) + t2[:, None] * v2
        assert p2[0] == pytest.approx([-0.016, -0.296, -0.688], abs=1e-9)


class TestVectorization:
    def test_batch_matches_single(self):
        rng = np.random.default_rng(42)
        octa = pt.octahedron(1.0)
        origins = rng.normal(size=(64, 3)) * 3.0
        dirs = rng.normal(size=(64, 3))
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        hit_b, t_b, f_b = octa.entry_hits(origins, dirs)
        for i in range(len(origins)):
            hit, t, f = octa.entry_hits(origins[i:i + 1], dirs[i:i + 1])
            assert hit[0] == hit_b[i]
            if hit[0]:
                assert t[0] == pytest.approx(t_b[i])
                assert f[0] == f_b[i]


class TestMerge:
    def test_near_duplicate_planes_merge(self):
        # Two coplanar +X entries (adjacent cuts on the same plane) and one
        # distinct -X entry: merged to 2 planes, largest-area owner wins.
        n = np.array([[1.0, 0, 0], [1.0, 0, 0], [-1.0, 0, 0]])
        d = np.array([1.0, 1.0 + 1e-9, 1.0])
        tiers = np.array([0, 1, 2], dtype=np.intp)
        areas = np.array([1.0, 3.0, 2.0])
        polys = [None, None, None]
        mn, md, mt, ma, _mp = pt._merge_coplanar(n, d, tiers, areas, polys)
        assert len(md) == 2
        plus = int(np.argmax(mn @ np.array([1.0, 0, 0])))
        assert mt[plus] == 1          # larger-area member owns the plane
        assert ma[plus] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Extraction from real gem geometry (requires FreeCAD)
# ---------------------------------------------------------------------------

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.faceting.gem_feature import make_gem  # noqa: E402
from freecad.lapidary.faceting.stock_feature import make_stock  # noqa: E402
from freecad.lapidary.faceting.tier_feature import make_tier  # noqa: E402


@pytest.fixture
def doc():
    doc = FreeCAD.newDocument("optics_polytope_test")
    try:
        yield doc
    finally:
        FreeCAD.closeDocument(doc.Name)


class TestExtraction:
    def test_srb_extracts_with_full_attribution(self, doc):
        from test_pipeline import SRB_TIERS, build_srb

        gem, _stock, _tiers = build_srb(doc)
        poly = pt.extract_polytope(gem)
        # 73 distinct facet planes (no two SRB facets are coplanar).
        assert poly.num_faces == 73
        assert poly.tier_labels == tuple(t[0] for t in SRB_TIERS)
        # Per-tier plane counts match the published facet counts.
        for tier_id, (_name, _side, _angle, _dist, _idx, count) in enumerate(
                SRB_TIERS):
            assert int(np.sum(poly.tier_ids == tier_id)) == count
        assert not np.any(poly.tier_ids == pt.NO_TIER)
        # Extraction implies convexity: re-check via the vertex enumeration.
        verts = poly.vertices()
        assert np.all(poly.contains(verts, tol=1e-6))
        # Total face area matches the B-Rep's.
        from freecad.lapidary.faceting.gem_feature import final_shape
        assert float(np.sum(poly.areas)) == pytest.approx(
            final_shape(gem).Area, rel=1e-9)

    def test_curved_remnant_refused_actionably(self, doc):
        # A cylinder stock with only a table cut keeps its curved side face:
        # the refusal must point the user at a 90 degree girdle tier.
        gem = make_gem(doc, label="Curved", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 10.0, "Height": 8.0})
        make_tier(gem, 0.0, 3.0, [], side="Crown", tier_name="Table")
        doc.recompute()
        with pytest.raises(pt.PolytopeError, match="girdle"):
            pt.extract_polytope(gem)

    def test_no_geometry_refused_actionably(self, doc):
        gem = make_gem(doc, label="Empty", index_gear=96)
        with pytest.raises(pt.PolytopeError, match="no solid geometry"):
            pt.extract_polytope(gem)
