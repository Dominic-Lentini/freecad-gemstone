# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for core.halfspace (DESIGN.md section 2.1 cutting-box construction).

Requires FreeCAD; skipped under plain pytest without it. Runs headless under
FreeCADCmd / FreeCAD's Python.
"""

import math

import pytest

FreeCAD = pytest.importorskip("FreeCAD")
import Part  # noqa: E402  (import order: only valid once FreeCAD imports)

from freecad.lapidary.core import gemmath, halfspace  # noqa: E402

TOL = 1e-9


def unit(v):
    v = FreeCAD.Vector(*v)
    v.normalize()
    return v


@pytest.fixture
def stock():
    # 12 x 10 cylinder, mass-centered like real stock.
    return Part.makeCylinder(6.0, 10.0, FreeCAD.Vector(0, 0, -5.0))


class TestCuttingBox:
    @pytest.mark.parametrize("normal,distance", [
        ((0, 0, 1), 3.0),
        ((0, 0, -1), 4.0),
        ((1, 0, 0), 2.5),
        (gemmath.facet_normal(42.0, 96, 3, "Pavilion"), 4.0),
        (gemmath.facet_normal(34.5, 96, 71, "Crown", 0.5), 3.7),
    ])
    def test_inner_face_exactly_on_plane(self, stock, normal, distance):
        box = halfspace.cutting_box(normal, distance, stock.BoundBox)
        n = unit(normal)
        dots = [n.dot(v.Point) for v in box.Vertexes]
        # The box occupies the discarded half-space: n.x >= d for every
        # vertex, with the inner face exactly at d.
        assert min(dots) == pytest.approx(distance, abs=TOL)
        assert max(dots) > distance
        # One face of the box lies exactly on the plane with a planar surface.
        on_plane = [f for f in box.Faces
                    if all(abs(n.dot(v.Point) - distance) < TOL
                           for v in f.Vertexes)]
        assert len(on_plane) == 1
        assert isinstance(on_plane[0].Surface, Part.Plane)

    def test_extents_at_least_ten_diagonals(self, stock):
        bbox = stock.BoundBox
        diag = bbox.DiagonalLength
        n = gemmath.facet_normal(42.0, 96, 3, "Pavilion")
        box = halfspace.cutting_box(n, 4.0, bbox)
        # Every edge of the box must be >= 10x the bounding diagonal.
        lengths = sorted(set(round(e.Length, 6) for e in box.Edges))
        assert min(lengths) >= 10.0 * diag

    def test_covers_shape_beyond_plane(self, stock):
        # Cutting must remove exactly the material beyond the plane: compare
        # against an analytic slab volume for a horizontal cut.
        result = halfspace.cut_halfspace(stock, (0, 0, 1), 3.0)
        expected = math.pi * 36.0 * 8.0  # cylinder r=6 from z=-5 to z=+3
        assert result.Volume == pytest.approx(expected, rel=1e-9)
        assert result.BoundBox.ZMax == pytest.approx(3.0, abs=1e-7)

    def test_cut_face_normal_is_exact(self, stock):
        n = unit(gemmath.facet_normal(41.0, 96, 12, "Pavilion"))
        result = halfspace.cut_halfspace(stock, n, 4.0)
        # Find the newly created planar facet and check its outward normal.
        facet = None
        for f in result.Faces:
            if not isinstance(f.Surface, Part.Plane):
                continue
            u0, u1, v0, v1 = f.ParameterRange
            fn = f.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            if fn.dot(n) > 1.0 - 1e-9:
                facet = f
                break
        assert facet is not None, "cut did not produce the expected facet"
        assert n.dot(facet.CenterOfMass) == pytest.approx(4.0, abs=1e-7)

    def test_no_meshes_exact_brep(self, stock):
        result = halfspace.cut_halfspace(stock, (0, 0, 1), 3.0)
        assert result.isValid()
        assert len(result.Solids) == 1
        # Every face is an analytic surface (Plane or Cylinder here).
        for f in result.Faces:
            assert isinstance(f.Surface, (Part.Plane, Part.Cylinder))

    def test_annihilating_cut_yields_empty(self, stock):
        # Discarded half-space z >= -6 contains the whole stock (z in [-5, 5]):
        # everything is cut away.
        result = halfspace.cut_halfspace(stock, (0, 0, 1), -6.0)
        assert not result.Solids or result.Volume < 1e-9

    def test_missing_cut_is_noop(self, stock):
        # Plane beyond the stock: nothing is removed.
        result = halfspace.cut_halfspace(stock, (0, 0, 1), 50.0)
        assert result.Volume == pytest.approx(stock.Volume, rel=1e-12)

    def test_retain_halfspace_equals_cut(self, stock):
        # The common()-based formulation is mathematically identical to the
        # cut()-based one (it exists as an arbiter for silent OCC cut
        # failures; see docs/dev-notes.md).
        for normal, distance in [
            ((0, 0, 1), 3.0),
            (gemmath.facet_normal(42.0, 96, 3, "Pavilion"), 4.0),
            (gemmath.facet_normal(34.5, 96, 71, "Crown", 0.5), 3.7),
        ]:
            cut_result = halfspace.cut_halfspace(stock, normal, distance)
            common_result = halfspace.retain_halfspace(stock, normal, distance)
            assert common_result.Volume == pytest.approx(cut_result.Volume,
                                                         rel=1e-9)
            n = unit(normal)
            facet = [f for f in common_result.Faces
                     if isinstance(f.Surface, Part.Plane)
                     and abs(n.dot(f.CenterOfMass) - distance) < 1e-7]
            assert facet, "retained facet plane missing"

    def test_degenerate_inputs_rejected(self, stock):
        with pytest.raises(ValueError):
            halfspace.cutting_box((0, 0, 0), 3.0, stock.BoundBox)
        empty = FreeCAD.BoundBox()
        with pytest.raises(ValueError):
            halfspace.cutting_box((0, 0, 1), 3.0, empty)
