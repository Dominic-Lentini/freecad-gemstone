# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for faceting.asc_io.parser / writer (pure Python, no FreeCAD).

Two layers: inline structural tests that always run (so CI covers the parser
without the reference material), and tests against the real sample files
under reference/asc-samples/, which skip when that gitignored directory is
absent (see reference/README.md for provenance/licensing).
"""

import glob
import os

import pytest

from freecad.lapidary.faceting.asc_io.parser import (
    AscParseError, design_tier_specs, parse_asc, read_asc)
from freecad.lapidary.faceting.asc_io.writer import format_asc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "reference", "asc-samples")

needs_samples = pytest.mark.skipif(
    not os.path.isdir(SAMPLES_DIR),
    reason="reference/asc-samples not present (gitignored local material)")


def sample(*parts):
    return os.path.join(SAMPLES_DIR, *parts)


def all_samples():
    return sorted(glob.glob(os.path.join(SAMPLES_DIR, "*", "*.asc")))


# ---------------------------------------------------------------------------
# Inline structural tests (always run)
# ---------------------------------------------------------------------------

INLINE = """GemCad 5.0
g 96 0.0
y 8 y
I 1.62
H Test Design
H by Nobody 1/1/26
a -90.000000 1.00000000 93 n G 87 81
a -41.000000 0.55000000 96 n M 12 24 G Meet culet
a 0.000000 0.30000000 96 n T
F A footnote.
"""


class TestParseInline:
    def test_metadata(self):
        design = parse_asc(INLINE)
        assert design.gear == 96
        assert design.gear_offset == 0.0
        assert design.symmetry_folds == 8
        assert design.symmetry_mirror == "y"
        assert design.refractive_index == 1.62
        assert design.headers == ["Test Design", "by Nobody 1/1/26"]
        assert design.footnotes == ["A footnote."]
        assert not design.warnings

    def test_facet_records(self):
        design = parse_asc(INLINE)
        assert len(design.tiers) == 3
        girdle, mains, table = design.tiers
        assert girdle.angle == -90.0
        assert [f.index for f in girdle.facets] == [93.0, 87.0, 81.0]
        assert girdle.facets[0].name == "G"
        assert girdle.facets[1].name == ""
        assert mains.instructions == ["Meet culet"]
        assert [f.index for f in mains.facets] == [96.0, 12.0, 24.0]
        assert table.facets[0].name == "T"

    def test_continuation_lines(self):
        design = parse_asc(
            "GemCad 5.0\ng 96 0.0\n"
            "a -90.000000 1.00000000 3 9\n"
            " 15 21 n X\n"
            " G Level girdle\n")
        tier = design.tiers[0]
        assert [f.index for f in tier.facets] == [3.0, 9.0, 15.0, 21.0]
        assert tier.facets[3].name == "X"
        assert tier.instructions == ["Level girdle"]

    def test_continuation_name_binds_to_last_facet(self):
        design = parse_asc(
            "GemCad 5.0\ng 96 0.0\n"
            "a -52.000000 0.31000000 1.57 n b 10.43\n"
            " n b\n")
        tier = design.tiers[0]
        assert tier.facets[0].name == "b"
        assert tier.facets[1].name == "b"

    def test_g_extends_to_end_of_line_only(self):
        design = parse_asc(
            "GemCad 5.0\ng 96 0.0\n"
            "a -90.000000 1.00000000 3 G Fix girdle width.\n"
            " 9 15\n")
        tier = design.tiers[0]
        assert tier.instructions == ["Fix girdle width."]
        assert [f.index for f in tier.facets] == [3.0, 9.0, 15.0]

    def test_errors(self):
        with pytest.raises(AscParseError):
            parse_asc("GemCad 5.0\ng 0 0.0\n")
        with pytest.raises(AscParseError):
            parse_asc("GemCad 5.0\na -41.0\n")
        with pytest.raises(AscParseError):
            parse_asc("GemCad 5.0\ng 96 0.0\na -41.0 0.5 n X\n")

    def test_unknown_material_warns_not_raises(self):
        design = parse_asc("GemCad 5.0\ng 96 0.0\nQ mystery line\n")
        assert design.warnings
        design = parse_asc(" n orphan continuation\n")
        assert design.warnings


class TestTierSpecsInline:
    def test_side_from_angle_sign(self):
        specs = design_tier_specs(parse_asc(INLINE))
        assert [s.side for s in specs] == ["Pavilion", "Pavilion", "Crown"]
        assert [s.angle for s in specs] == [90.0, 41.0, 0.0]

    def test_indices_normalized_and_sorted(self):
        specs = design_tier_specs(parse_asc(INLINE))
        assert specs[0].indices == [81, 87, 93]
        assert specs[1].indices == [12, 24, 96]      # 96 = tooth 0
        assert specs[1].name == "M"

    def test_negative_index_wraps(self):
        design = parse_asc("GemCad 5.0\ng 96 0.0\n"
                           "a -46.000000 0.52000000 -96 64 32 n 1\n")
        specs = design_tier_specs(design)
        assert specs[0].indices == [32, 64, 96]
        assert specs[0].name == "1"

    def test_integer_gear_offset_rebases_indices(self):
        design = parse_asc("GemCad 5.0\ng -96 48.0\n"
                           "a -46.000000 0.52000000 -96 64 32 n 1\n")
        specs = design_tier_specs(design)
        # i' = (i - 48) mod 96: -96 -> 48, 64 -> 16, 32 -> 80.
        assert specs[0].indices == [16, 48, 80]

    def test_fractional_indices_split_into_offset_groups(self):
        design = parse_asc("GemCad 5.0\ng 96 0.0\n"
                           "a -52.000000 0.31000000 1.57 n b 10.43 13.57 22.43\n")
        specs = design_tier_specs(design)
        assert len(specs) == 2
        by_offset = {s.index_offset: s for s in specs}
        assert by_offset[0.57].indices == [1, 13]
        assert by_offset[0.43].indices == [10, 22]
        # Both groups keep the record's angle/distance and name where present.
        assert all(s.angle == 52.0 and s.side == "Pavilion" for s in specs)

    def test_negative_distance_rejected(self):
        design = parse_asc("GemCad 5.0\ng 96 0.0\n"
                           "a -0.000000 -0.10000000 96\n")
        with pytest.raises(AscParseError):
            design_tier_specs(design)


class TestWriterInline:
    def test_writer_parser_roundtrip(self):
        design = parse_asc(INLINE)
        text = format_asc(design)
        again = parse_asc(text)
        assert again.gear == design.gear
        assert again.symmetry_folds == design.symmetry_folds
        assert again.refractive_index == design.refractive_index
        assert again.headers == design.headers
        assert again.footnotes == design.footnotes
        assert len(again.tiers) == len(design.tiers)
        for a, b in zip(design.tiers, again.tiers):
            assert b.angle == pytest.approx(a.angle, abs=1e-6)
            assert b.distance == pytest.approx(a.distance, abs=1e-8)
            assert [f.index for f in b.facets] == [f.index for f in a.facets]
            assert [f.name for f in b.facets] == [f.name for f in a.facets]
            assert b.instructions == a.instructions

    def test_long_records_wrap_with_continuations(self):
        design = parse_asc(INLINE)
        design.tiers[0].facets = design.tiers[0].facets * 12  # force a wrap
        text = format_asc(design)
        assert any(line.startswith(" ") for line in text.splitlines())
        assert all(len(line) <= 79 for line in text.splitlines())
        again = parse_asc(text)
        assert len(again.tiers[0].facets) == len(design.tiers[0].facets)


# ---------------------------------------------------------------------------
# Real sample files (skip without reference/)
# ---------------------------------------------------------------------------

@needs_samples
class TestSamples:
    def test_at_least_five_fixtures(self):
        assert len(all_samples()) >= 5

    def test_all_samples_parse_without_errors(self):
        for path in all_samples():
            design = read_asc(path)
            for warning in design.warnings:
                # Warnings are tolerated but none are expected on these files.
                pytest.fail("%s: %s" % (os.path.basename(path), warning))

    def test_srb(self):
        design = read_asc(sample("mbparker", "SRB.asc"))
        assert design.gear == 96
        assert design.symmetry_folds == 8
        assert design.refractive_index == 1.54
        assert design.headers[0] == "Standard Round Brilliant"
        specs = design_tier_specs(design)
        assert len(specs) == 7
        assert [len(s.indices) for s in specs] == [16, 16, 8, 16, 8, 8, 1]
        assert [s.side for s in specs] == (
            ["Pavilion"] * 3 + ["Crown"] * 4)
        assert specs[0].angle == 90.0
        assert specs[0].distance == pytest.approx(1.02653281)
        assert specs[0].name == "G"
        assert specs[-1].name == "T"
        # 73 published facets (57 + 16 girdles, manual page 4).
        assert sum(len(s.indices) for s in specs) == 73

    def test_negative_gear_with_offset(self):
        design = read_asc(sample("mbparker", "CubeIllusionTri.asc"))
        assert design.gear == -96
        assert design.gear_offset == 48.0
        assert design.symmetry_folds == 3
        specs = design_tier_specs(design)
        assert specs[0].indices == [16, 48, 80]
        assert len(design.footnotes) == 3

    def test_pear_inline_names_and_instructions(self):
        design = read_asc(sample("mbparker", "Compear125.asc"))
        assert design.symmetry_folds == 1
        girdle_tiers = [t for t in design.tiers if t.angle == -90.0]
        assert len(girdle_tiers) == 4     # multi-tier girdle, distinct d
        assert len({t.distance for t in girdle_tiers}) == 4
        first = design.tiers[0]
        named = [f for f in first.facets if f.name]
        assert all(f.name == "1" for f in named)
        assert first.instructions == ["Meet center point"]
        assert design.footnotes[0].startswith("Dop so the center")

    def test_turkey_continuation_instruction(self):
        design = read_asc(sample("mbparker", "Turkey.asc"))
        tier_a = next(t for t in design.tiers
                      if any(f.name == "A" for f in t.facets))
        assert "Fix girdle width." in tier_a.instructions
        assert len(tier_a.facets) == 16

    def test_fractional_sample_groups(self):
        design = read_asc(sample("sftdevstar", "sample-03.asc"))
        specs = design_tier_specs(design)
        fractional = [s for s in specs if s.index_offset]
        assert len(fractional) == 2
        offsets = sorted(s.index_offset for s in fractional)
        assert offsets == [pytest.approx(0.43), pytest.approx(0.57)]
        assert all(len(s.indices) == 8 for s in fractional)

    def test_writer_roundtrips_every_sample(self):
        for path in all_samples():
            design = read_asc(path)
            again = parse_asc(format_asc(design))
            specs_a = design_tier_specs(design)
            specs_b = design_tier_specs(again)
            assert len(specs_a) == len(specs_b), path
            for a, b in zip(specs_a, specs_b):
                assert b.side == a.side, path
                assert b.angle == pytest.approx(a.angle, abs=1e-6)
                assert b.distance == pytest.approx(a.distance, abs=1e-8)
                assert b.indices == a.indices, path
                assert b.index_offset == pytest.approx(a.index_offset,
                                                       abs=1e-9)
