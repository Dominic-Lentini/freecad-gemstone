# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for freecad.lapidary.core.gemmath (DESIGN.md section 2.1 sanity cases).

Pure Python: runs under plain pytest with no FreeCAD installed.
"""

import math

import pytest

from freecad.lapidary.core import gemmath
from freecad.lapidary.core.gemmath import Side

TOL = 1e-12


def norm(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def assert_close(a, b, tol=TOL):
    assert abs(a - b) <= tol, "%r != %r (tol %g)" % (a, b, tol)


def assert_vec_close(u, v, tol=TOL):
    for a, b in zip(u, v):
        assert_close(a, b, tol)


class TestSanityCases:
    """The normative sanity checks spelled out in section 2.1."""

    def test_theta_zero_crown_is_plus_z(self):
        # theta=0 crown -> n = +Z (table)
        n = gemmath.facet_normal(0.0, 96, 0, Side.CROWN)
        assert_vec_close(n, (0.0, 0.0, 1.0))
        # index is irrelevant at theta=0 (sin(theta)=0 kills the azimuth terms)
        n = gemmath.facet_normal(0.0, 96, 37, Side.CROWN)
        assert_vec_close(n, (0.0, 0.0, 1.0))

    def test_theta_zero_pavilion_is_minus_z(self):
        n = gemmath.facet_normal(0.0, 96, 0, Side.PAVILION)
        assert_vec_close(n, (0.0, 0.0, -1.0))

    def test_theta_ninety_is_horizontal(self):
        # theta=90 -> n horizontal (girdle facet)
        for index in (0, 12, 48, 95):
            n = gemmath.facet_normal(90.0, 96, index, Side.CROWN)
            assert_close(n[2], 0.0)
            assert_close(norm(n), 1.0)

    def test_theta_ninety_identical_for_either_side(self):
        # girdle facet is identical for either side
        for index in (0, 7, 50):
            nc = gemmath.facet_normal(90.0, 96, index, Side.CROWN)
            np_ = gemmath.facet_normal(90.0, 96, index, Side.PAVILION)
            assert_vec_close(nc, np_)

    def test_pavilion_is_mirror_through_girdle_plane(self):
        # Dop transfer is exactly the sign flip of n_z -- a mirror through the
        # girdle plane, not a rotation: x and y components must be untouched.
        for angle in (17.0, 41.0, 43.0, 63.5):
            for index in (0, 3, 21, 93):
                nc = gemmath.facet_normal(angle, 96, index, Side.CROWN)
                np_ = gemmath.facet_normal(angle, 96, index, Side.PAVILION)
                assert_close(nc[0], np_[0])
                assert_close(nc[1], np_[1])
                assert_close(nc[2], -np_[2])

    def test_pavilion_main_points_down_and_out(self):
        # Typical pavilion main theta ~ 41-43 deg -> normal points down-and-out.
        n = gemmath.facet_normal(42.0, 96, 3, Side.PAVILION)
        assert n[2] < 0.0
        assert math.hypot(n[0], n[1]) > 0.0

    def test_azimuth_spacing_gear_96(self):
        # One tooth on a 96 gear is 360/96 = 3.75 degrees.
        step = 360.0 / 96.0
        for i in range(96):
            a0 = gemmath.azimuth_deg(96, i)
            a1 = gemmath.azimuth_deg(96, i + 1)
            assert_close(abs(a1 - a0), step)
        # Default handedness dir = +1 (resolved in Phase 2): index advances
        # counter-clockwise viewed from the crown (+Z), GemCad convention.
        assert_close(gemmath.azimuth_deg(96, 1), step)
        assert_close(gemmath.azimuth_deg(96, 24), 90.0)

    def test_index_gear_wraps(self):
        # Index N is the same tooth as index 0.
        n0 = gemmath.facet_normal(42.0, 96, 0)
        n96 = gemmath.facet_normal(42.0, 96, 96)
        assert_vec_close(n0, n96, tol=1e-9)

    def test_fractional_index_offset(self):
        # A cheater of one whole tooth equals stepping the index by one.
        assert_close(gemmath.azimuth_deg(96, 3, index_offset=1.0),
                     gemmath.azimuth_deg(96, 4))
        # Half a tooth lands exactly between two teeth.
        a3 = gemmath.azimuth_deg(96, 3)
        a4 = gemmath.azimuth_deg(96, 4)
        assert_close(gemmath.azimuth_deg(96, 3, index_offset=0.5), (a3 + a4) / 2.0)
        # Negative cheater goes the other way.
        assert_close(gemmath.azimuth_deg(96, 3, index_offset=-0.25),
                     360.0 * 2.75 / 96.0)
        # The offset propagates through the normal.
        n = gemmath.facet_normal(42.0, 96, 3, Side.CROWN, index_offset=0.5)
        n_half = gemmath.facet_normal(42.0, 96, 3.5, Side.CROWN)
        assert_vec_close(n, n_half)


class TestAzimuthAndHandedness:
    def test_azimuth_formula(self):
        # phi = dir * 360 * (i + c) / N
        assert_close(gemmath.azimuth_deg(80, 10, 0.0, -1), -45.0)
        assert_close(gemmath.azimuth_deg(80, 10, 0.0, +1), 45.0)
        assert_close(gemmath.azimuth_deg(120, 30, 0.0, +1), 90.0)

    def test_handedness_mirrors_y(self):
        # Flipping dir mirrors the normal across the XZ plane.
        for index in (1, 5, 40):
            n_ccw = gemmath.facet_normal(35.0, 96, index, handedness=+1)
            n_cw = gemmath.facet_normal(35.0, 96, index, handedness=-1)
            assert_close(n_ccw[0], n_cw[0])
            assert_close(n_ccw[1], -n_cw[1])
            assert_close(n_ccw[2], n_cw[2])

    def test_default_handedness_is_plus_one(self):
        # Resolved in Phase 2 (see FORMAT_NOTES.md): GemCad indices increase
        # counter-clockwise viewed from the crown.
        assert gemmath.DEFAULT_HANDEDNESS == +1
        assert_close(gemmath.azimuth_deg(96, 24),
                     gemmath.azimuth_deg(96, 24, handedness=+1))

    def test_other_common_gears(self):
        for gear in (96, 80, 77, 72, 64, 120):
            step = 360.0 / gear
            assert_close(abs(gemmath.azimuth_deg(gear, 1)), step)


class TestNormalsAreUnit:
    @pytest.mark.parametrize("angle", [0.0, 10.0, 34.5, 42.0, 90.0, 95.0])
    @pytest.mark.parametrize("side", [Side.CROWN, Side.PAVILION])
    def test_unit_length(self, angle, side):
        for index in (0, 1, 13, 95):
            n = gemmath.facet_normal(angle, 96, index, side)
            assert_close(norm(n), 1.0)


class TestPlaneAndHalfSpace:
    def test_facet_plane_returns_normal_and_distance(self):
        n, d = gemmath.facet_plane(42.0, 96, 3, 5.5, Side.PAVILION)
        assert d == 5.5
        assert_vec_close(n, gemmath.facet_normal(42.0, 96, 3, Side.PAVILION))

    def test_distance_must_be_positive(self):
        for bad in (0.0, -1.0):
            with pytest.raises(ValueError):
                gemmath.facet_plane(42.0, 96, 3, bad)

    def test_point_on_plane_lies_on_plane(self):
        n, d = gemmath.facet_plane(42.0, 96, 3, 5.5, Side.PAVILION)
        p = gemmath.point_on_plane(n, d)
        assert_close(gemmath.signed_distance(n, d, p), 0.0, tol=1e-9)

    def test_half_space_retention(self):
        # Cutting a facet retains the half-space n.x <= d: the origin always
        # survives (d > 0), a point past the plane along n is cut away.
        n, d = gemmath.facet_plane(30.0, 96, 8, 2.0, Side.CROWN)
        assert gemmath.is_retained(n, d, (0.0, 0.0, 0.0))
        outside = tuple(2.0 * c * d for c in n)
        assert not gemmath.is_retained(n, d, outside)
        assert gemmath.signed_distance(n, d, outside) > 0.0


class TestSides:
    def test_side_sign(self):
        assert gemmath.side_sign(Side.CROWN) == 1.0
        assert gemmath.side_sign(Side.PAVILION) == -1.0

    def test_side_accepts_strings(self):
        assert gemmath.side_sign("Crown") == 1.0
        assert gemmath.side_sign("pavilion") == -1.0
        n_str = gemmath.facet_normal(42.0, 96, 3, "Pavilion")
        n_enum = gemmath.facet_normal(42.0, 96, 3, Side.PAVILION)
        assert_vec_close(n_str, n_enum)

    def test_invalid_side_rejected(self):
        with pytest.raises(ValueError):
            gemmath.side_sign("girdle")
        with pytest.raises(ValueError):
            gemmath.side_sign(None)


class TestValidation:
    def test_gear_must_be_positive_integer(self):
        for bad in (0, -96, 96.0, "96", None, True):
            with pytest.raises(ValueError):
                gemmath.azimuth_deg(bad, 1)

    def test_handedness_must_be_unit_sign(self):
        for bad in (0, 2, -2, 0.5, None):
            with pytest.raises(ValueError):
                gemmath.azimuth_deg(96, 1, handedness=bad)
