# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for core.registry (stock habit registry, DESIGN.md section 2).

Requires FreeCAD; skipped under plain pytest without it.
"""

import math

import pytest

FreeCAD = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

from freecad.lapidary.core import registry  # noqa: E402

REQUIRED_HABITS = [
    "Cylinder", "RectangularPrism", "HexagonalPrism",
    "Octahedron", "Dodecahedron", "TrigonalPrism",
]


class TestRegistry:
    def test_all_required_habits_registered(self):
        for key in REQUIRED_HABITS:
            assert key in registry.habit_keys()

    def test_unknown_habit_raises(self):
        with pytest.raises(KeyError):
            registry.get_habit("KryptoniteShard")

    def test_habits_are_extensible(self):
        habit = registry.StockHabit(
            "TestSphere", "Test sphere", [("Diameter", "Diameter", 10.0)],
            lambda Diameter: Part.makeSphere(Diameter / 2.0))
        registry.register_habit(habit)
        try:
            shape = registry.build_stock("TestSphere", {"Diameter": 4.0})
            assert shape.Volume == pytest.approx(4.0 / 3.0 * math.pi * 8.0,
                                                 rel=1e-9)
        finally:
            registry._REGISTRY.pop("TestSphere", None)

    def test_bad_dimensions_rejected(self):
        with pytest.raises(ValueError):
            registry.build_stock("Cylinder", {"Diameter": 0.0})
        with pytest.raises(ValueError):
            registry.build_stock("Cylinder", {"Radius": 5.0})


class TestMassCentering:
    @pytest.mark.parametrize("key", REQUIRED_HABITS)
    def test_center_of_mass_at_origin(self, key):
        shape = registry.build_stock(key)
        assert shape.CenterOfMass.Length < 1e-9

    @pytest.mark.parametrize("key", REQUIRED_HABITS)
    def test_centering_is_baked_into_geometry(self, key):
        # A FeaturePython recompute resets the assigned shape's placement to
        # the object's Placement, so centering must live in the geometry, not
        # the shape location (regression: the stock came back off-center).
        shape = registry.build_stock(key)
        assert shape.Placement.Base.Length < 1e-12
        assert shape.Placement.Rotation.isIdentity()
        bb = shape.BoundBox
        assert abs(bb.ZMax + bb.ZMin) < 1e-9
        assert abs(bb.XMax + bb.XMin) < 1e-9

    def test_third_party_offcenter_builder_is_recentered_in_geometry(self):
        habit = registry.StockHabit(
            "TestOffCenter", "Off-center box",
            [("Size", "Size", 4.0)],
            lambda Size: Part.makeBox(Size, Size, Size))  # corner at origin
        registry.register_habit(habit)
        try:
            shape = registry.build_stock("TestOffCenter")
            assert shape.CenterOfMass.Length < 1e-9
            assert shape.Placement.Base.Length < 1e-12
            assert min(v.Point.z for v in shape.Vertexes) == pytest.approx(-2.0)
        finally:
            registry._REGISTRY.pop("TestOffCenter", None)

    @pytest.mark.parametrize("key", REQUIRED_HABITS)
    def test_valid_single_solid_brep(self, key):
        shape = registry.build_stock(key)
        assert shape.isValid()
        assert len(shape.Solids) == 1
        assert shape.Volume > 0.0


class TestVolumes:
    def test_cylinder(self):
        shape = registry.build_stock("Cylinder", {"Diameter": 10.0, "Height": 8.0})
        assert shape.Volume == pytest.approx(math.pi * 25.0 * 8.0, rel=1e-9)

    def test_rectangular_prism(self):
        shape = registry.build_stock(
            "RectangularPrism", {"Length": 4.0, "Width": 3.0, "Height": 2.0})
        assert shape.Volume == pytest.approx(24.0, rel=1e-12)

    def test_hex_prism(self):
        # Area of a regular hexagon with across-flats f: f^2 * sqrt(3) / 2.
        f, h = 10.0, 6.0
        shape = registry.build_stock(
            "HexagonalPrism", {"WidthAcrossFlats": f, "Height": h})
        assert shape.Volume == pytest.approx(f * f * math.sqrt(3.0) / 2.0 * h,
                                             rel=1e-9)
        # Across-flats extent matches the parameter (flats face +/-X).
        assert shape.BoundBox.XLength == pytest.approx(f, abs=1e-9)

    def test_trigonal_prism(self):
        s, h = 9.0, 5.0
        shape = registry.build_stock("TrigonalPrism", {"Side": s, "Height": h})
        assert shape.Volume == pytest.approx(math.sqrt(3.0) / 4.0 * s * s * h,
                                             rel=1e-9)

    def test_octahedron(self):
        # Regular octahedron, vertex-to-vertex size 2a: volume = 4/3 a^3.
        size = 12.0
        a = size / 2.0
        shape = registry.build_stock("Octahedron", {"Size": size})
        assert shape.Volume == pytest.approx(4.0 / 3.0 * a ** 3, rel=1e-9)
        assert len(shape.Faces) == 8
        bb = shape.BoundBox
        for extent in (bb.XLength, bb.YLength, bb.ZLength):
            assert extent == pytest.approx(size, abs=1e-9)

    def test_dodecahedron(self):
        # Regular dodecahedron with inradius r: V = 20 r^3 sqrt(15) *
        # (5 - sqrt(5)) / ((5 + 2 sqrt(5)) * ... ) -- use the edge-length
        # form instead: r_in = a/2 * sqrt(5/2 + 11/(2 sqrt(5))),
        # V = a^3 (15 + 7 sqrt(5)) / 4.
        size = 12.0
        r_in = size / 2.0
        a = 2.0 * r_in / math.sqrt(2.5 + 1.1 * math.sqrt(5.0))
        expected = a ** 3 * (15.0 + 7.0 * math.sqrt(5.0)) / 4.0
        shape = registry.build_stock("Dodecahedron", {"Size": size})
        assert shape.Volume == pytest.approx(expected, rel=1e-9)
        assert len(shape.Faces) == 12
        # Size is face-to-face: opposite flats along a face normal.
        f = shape.Faces[0]
        u0, u1, v0, v1 = f.ParameterRange
        n = f.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        assert abs(n.dot(f.CenterOfMass)) == pytest.approx(size / 2.0, abs=1e-9)

    def test_all_faces_planar_on_polyhedra(self):
        for key in ("Octahedron", "Dodecahedron", "TrigonalPrism",
                    "RectangularPrism", "HexagonalPrism"):
            shape = registry.build_stock(key)
            for face in shape.Faces:
                assert isinstance(face.Surface, Part.Plane), \
                    "%s has a non-planar face" % key
