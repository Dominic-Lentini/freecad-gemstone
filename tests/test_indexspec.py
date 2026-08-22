# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for faceting.indexspec (pure Python, no FreeCAD required)."""

import pytest

from freecad.lapidary.faceting.indexspec import (
    mirror_indices,
    IndexSpecError, format_indices, parse_index_spec, rotate_indices)


class TestCommaList:
    def test_basic(self):
        assert parse_index_spec("3,21,27,45", 96) == [3, 21, 27, 45]

    def test_whitespace_and_dashes(self):
        assert parse_index_spec("03-09-15-21", 96) == [3, 9, 15, 21]
        assert parse_index_spec(" 3 , 21  27 ", 96) == [3, 21, 27]

    def test_sorted_and_deduplicated(self):
        assert parse_index_spec("45,3,45,21", 96) == [3, 21, 45]

    def test_zero_normalized_to_gear(self):
        assert parse_index_spec("0,12,24", 96) == [12, 24, 96]
        assert parse_index_spec("96,12", 96) == [12, 96]

    def test_out_of_range_rejected(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("97", 96)
        with pytest.raises(IndexSpecError):
            parse_index_spec("3,121", 120)

    def test_garbage_rejected(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("3,x,9", 96)
        with pytest.raises(IndexSpecError):
            parse_index_spec("3.5", 96)


class TestSymmetricShorthand:
    def test_96_over_8(self):
        # 96/8 = every 12th tooth, anchored on tooth N; shifting the pattern
        # is done visually (rotate_indices / the panel's rotate buttons).
        assert parse_index_spec("96/8", 96) == [12, 24, 36, 48, 60, 72, 84, 96]

    def test_other_gears(self):
        assert parse_index_spec("80/8", 80) == [10, 20, 30, 40, 50, 60, 70, 80]
        assert parse_index_spec("72/6", 72) == [12, 24, 36, 48, 60, 72]

    def test_gear_mismatch_rejected(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("96/8", 80)

    def test_uneven_division_rejected(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("96/7", 96)

    def test_zero_count_rejected(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("96/0", 96)


class TestEmptyAndEdge:
    def test_empty_means_axial_facet(self):
        assert parse_index_spec("", 96) == []
        assert parse_index_spec("   ", 96) == []
        assert parse_index_spec(None, 96) == []

    def test_bad_gear(self):
        with pytest.raises(IndexSpecError):
            parse_index_spec("3", 0)


class TestRotatePattern:
    def test_rotate_forward_and_back(self):
        mains = [12, 24, 36, 48, 60, 72, 84, 96]
        shifted = rotate_indices(mains, 96, 3)
        assert shifted == [3, 15, 27, 39, 51, 63, 75, 87]
        assert rotate_indices(shifted, 96, -3) == mains

    def test_rotate_wraps_around_gear(self):
        assert rotate_indices([95, 96], 96, 2) == [1, 2]
        assert rotate_indices([1, 2], 96, -2) == [95, 96]

    def test_rotate_reaches_break_positions(self):
        # The classic use: shift 8-fold mains onto the 16-fold half/break
        # start (every 12 starting at 3 after a +3 rotation).
        assert rotate_indices(parse_index_spec("96/8", 96), 96, 3)[0] == 3

    def test_bad_gear(self):
        with pytest.raises(IndexSpecError):
            rotate_indices([1], 0, 1)


class TestFormat:
    def test_gemcad_style(self):
        assert format_indices([3, 9, 15], 96) == "03-09-15"
        assert format_indices([12, 96], 96) == "12-96"
        assert format_indices([], 96) == ""

    def test_wide_gear(self):
        assert format_indices([5, 100], 120) == "005-100"

    def test_roundtrip(self):
        original = [3, 9, 15, 21, 27, 33, 39, 45, 51, 57, 63, 69, 75, 81, 87, 93]
        assert parse_index_spec(format_indices(original, 96), 96) == original


class TestSymmetry:
    """KSP-style radial symmetry for the index wheel (final polish)."""

    def test_all_folds_offered_for_any_gear(self):
        from freecad.lapidary.faceting.indexspec import symmetry_folds
        for gear in (96, 120, 77, 64):
            assert symmetry_folds(gear) == list(range(1, 10))

    def test_divisor_orbits_are_exact(self):
        from freecad.lapidary.faceting.indexspec import symmetry_orbit
        assert symmetry_orbit(12, 96, 4) == [12, 36, 60, 84]
        assert symmetry_orbit(96, 96, 4) == [24, 48, 72, 96]
        assert symmetry_orbit(5, 96, 1) == [5]

    def test_non_divisor_orbits_snap_to_the_nearest_tooth(self):
        from freecad.lapidary.faceting.indexspec import symmetry_orbit
        # 5-fold on a 96 gear: ideal step 19.2 teeth, quantized.
        assert symmetry_orbit(96, 96, 5) == [19, 38, 58, 77, 96]
        assert len(symmetry_orbit(96, 96, 7)) == 7
        assert len(symmetry_orbit(96, 96, 9)) == 9
        # Every snapped copy is a whole tooth in 1..N.
        for fold in (5, 7, 9):
            for i in symmetry_orbit(3, 96, fold):
                assert isinstance(i, int) and 1 <= i <= 96

    def test_orbit_rejects_bad_fold(self):
        from freecad.lapidary.faceting.indexspec import symmetry_orbit
        with pytest.raises(IndexSpecError):
            symmetry_orbit(3, 96, 0)

    def test_expand_symmetric(self):
        from freecad.lapidary.faceting.indexspec import expand_symmetric
        assert expand_symmetric([3], 96, 8) == [3, 15, 27, 39, 51, 63,
                                                75, 87]
        # Already-closed patterns are unchanged.
        eight = list(range(12, 97, 12))
        assert expand_symmetric(eight, 96, 8) == eight
        assert expand_symmetric([], 96, 4) == []


class TestSymmetryRegions:
    """Alternating shading needs an even region count to close around the
    circle, so odd folds double (see the index wheel)."""

    def test_even_folds_use_one_region_per_pole(self):
        from freecad.lapidary.faceting.indexspec import symmetry_regions
        assert symmetry_regions(2) == 2      # 1 shaded
        assert symmetry_regions(4) == 4      # 2 shaded
        assert symmetry_regions(6) == 6
        assert symmetry_regions(8) == 8

    def test_odd_folds_double_so_every_pole_is_shaded(self):
        from freecad.lapidary.faceting.indexspec import symmetry_regions
        assert symmetry_regions(3) == 6      # 3 shaded, 3 light
        assert symmetry_regions(5) == 10
        assert symmetry_regions(7) == 14
        assert symmetry_regions(9) == 18

    def test_region_counts_are_always_even_and_alternate_cleanly(self):
        from freecad.lapidary.faceting.indexspec import (
            symmetry_folds, symmetry_regions)
        for gear in (96, 120, 77, 80):
            for fold in symmetry_folds(gear):
                regions = symmetry_regions(fold)
                assert regions % 2 == 0, (gear, fold)
                # A shaded region always lands on a pole: the poles sit
                # every regions/fold regions apart, which must be whole.
                if fold > 1:
                    assert regions % fold == 0

    def test_no_symmetry_shades_nothing(self):
        from freecad.lapidary.faceting.indexspec import symmetry_regions
        assert symmetry_regions(1) == 0

    def test_rejects_bad_fold(self):
        from freecad.lapidary.faceting.indexspec import symmetry_regions
        with pytest.raises(IndexSpecError):
            symmetry_regions(0)


class TestMirror:
    def test_ns_mirror_swaps_east_and_west(self):
        # 96 gear: tooth 12 (east side) mirrors to tooth 84 (west side);
        # teeth on the axis itself (96 north, 48 south) are fixed points.
        assert mirror_indices([12], 96, "ns") == [84]
        assert mirror_indices([96, 48], 96, "ns") == [48, 96]

    def test_ew_mirror_swaps_north_and_south(self):
        # Tooth 12 mirrors to 36 across the horizontal axis; the east
        # pole (24) and west pole (72) are fixed points.
        assert mirror_indices([12], 96, "ew") == [36]
        assert mirror_indices([24, 72], 96, "ew") == [24, 72]

    def test_union_with_original_is_a_copy(self):
        pattern = [3, 9, 15, 21]
        both = sorted(set(pattern) | set(mirror_indices(pattern, 96, "ns")))
        assert both == [3, 9, 15, 21, 75, 81, 87, 93]

    def test_mirror_is_an_involution_on_even_gears(self):
        pattern = [1, 7, 40, 96]
        for axis in ("ns", "ew"):
            image = mirror_indices(pattern, 96, axis)
            assert mirror_indices(image, 96, axis) == sorted(pattern)

    def test_odd_gear_ew_mirror_snaps_to_the_nearest_tooth(self):
        # 77 gear: N/2 = 38.5, so tooth 10 ideally maps to 28.5 and
        # snaps to a whole tooth.
        assert mirror_indices([10], 77, "ew") in ([28], [29])

    def test_bad_axis_rejected(self):
        with pytest.raises(IndexSpecError):
            mirror_indices([1], 96, "diagonal")
