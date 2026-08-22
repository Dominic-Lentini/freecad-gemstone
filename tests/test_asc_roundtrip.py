# SPDX-License-Identifier: LGPL-2.1-or-later
"""GemCad .ASC round-trip tests (DESIGN.md section 7 acceptance criteria).

Requires FreeCAD (skipped under plain pytest without it). The sample-file
tests additionally skip when the gitignored reference/asc-samples material is
absent (see reference/README.md); an inline hand-built-gem round-trip always
runs so CI keeps coverage of the import/export mapping.

Published expected values for SRB.asc — the Standard Round Brilliant worked
example from the GemCad for Windows User's Guide, whose page-4 diagram
prints the dimension table for exactly this design:

    57 + 16 girdles = 73 facets, 8-fold mirror, 96 index
    L/W = 1.000   T/W = 0.584   U/W = 0.584
    P/W = 0.442   C/W = 0.111   Vol./W^3 = 0.182
"""

import glob
import os

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.faceting import gem_feature, ownership, reports  # noqa: E402
from freecad.lapidary.faceting.asc_io.document import (  # noqa: E402
    design_to_gem, gem_to_design)
from freecad.lapidary.faceting.asc_io.parser import (  # noqa: E402
    design_tier_specs, parse_asc, read_asc)
from freecad.lapidary.faceting.asc_io.writer import format_asc  # noqa: E402
from freecad.lapidary.faceting.gem_feature import final_shape  # noqa: E402
from freecad.lapidary.faceting.stock_feature import make_stock  # noqa: E402
from freecad.lapidary.faceting.tier_feature import make_tier  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "reference", "asc-samples")

needs_samples = pytest.mark.skipif(
    not os.path.isdir(SAMPLES_DIR),
    reason="reference/asc-samples not present (gitignored local material)")

GEOM_TOL = 1e-6


def all_samples():
    return sorted(glob.glob(os.path.join(SAMPLES_DIR, "*", "*.asc")))


def sample(*parts):
    return os.path.join(SAMPLES_DIR, *parts)


@pytest.fixture
def doc():
    document = FreeCAD.newDocument("asc_roundtrip")
    try:
        yield document
    finally:
        FreeCAD.closeDocument(document.Name)


def import_design(document, design, name="Imported"):
    gem = design_to_gem(document, design, label=name)
    document.recompute()
    for tier in gem_feature.pipeline_features(gem):
        if gem_feature.is_tier(tier):
            assert tier.isValid(), "%s: %s" % (tier.Label, tier.TierState)
    return gem


def assert_geometric_identity(shape_a, shape_b, tol=GEOM_TOL):
    """Same face count, every face's plane matched 1:1 within ``tol``, and
    matching vertex clouds within ``tol`` (section 7 acceptance)."""
    assert len(shape_a.Faces) == len(shape_b.Faces)
    assert len(shape_a.Vertexes) == len(shape_b.Vertexes)

    points_b = [v.Point for v in shape_b.Vertexes]
    for vertex in shape_a.Vertexes:
        nearest = min((vertex.Point - p).Length for p in points_b)
        assert nearest < tol, "vertex %s unmatched (nearest %g)" % (
            vertex.Point, nearest)

    planes_b = []
    for face in shape_b.Faces:
        plane = ownership.face_plane(face)
        if plane is not None:
            planes_b.append(plane)
    for face in shape_a.Faces:
        plane = ownership.face_plane(face)
        if plane is None:
            continue
        normal, d = plane
        matches = [
            1 for other_normal, other_d in planes_b
            if (normal - other_normal).Length < tol and abs(d - other_d) < tol
        ]
        assert len(matches) == 1, (
            "face plane (%s, %g) matched %d times" % (normal, d, len(matches)))


def roundtrip(document, gem, name="Reimported"):
    text = format_asc(gem_to_design(gem))
    return import_design(document, parse_asc(text), name=name), text


# ---------------------------------------------------------------------------
# Inline round-trip of a hand-built gem (always runs under FreeCAD)
# ---------------------------------------------------------------------------

class TestHandBuiltGemRoundtrip:
    def test_export_reimport_identity(self, doc):
        gem = gem_feature.make_gem(doc, label="Inline", index_gear=96)
        gem.DesignName = "Inline Test Stone"
        gem.Author = "Nobody"
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        make_tier(gem, 90.0, 4.5, list(range(6, 97, 6)), side="Pavilion",
                  tier_name="G")
        make_tier(gem, 42.0, 3.1, list(range(12, 97, 12)), side="Pavilion",
                  tier_name="P1")
        make_tier(gem, 35.0, 3.0, list(range(12, 97, 12)), side="Crown",
                  tier_name="C1", index_offset=0.5)
        make_tier(gem, 0.0, 1.4, [], side="Crown", tier_name="T")
        doc.recompute()

        reimported, text = roundtrip(doc, gem)
        assert "Inline Test Stone" in text
        assert "by Nobody" in text
        assert reimported.IndexGear == 96
        assert_geometric_identity(final_shape(gem), final_shape(reimported))

    def test_fractional_offset_written_as_fractional_indices(self, doc):
        # A full stone (girdle + pavilion + table close the rough completely;
        # stock dimensions are not stored in .ASC, so only a fully faceted
        # stone can round-trip identically).
        gem = gem_feature.make_gem(doc, label="Cheater", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        make_tier(gem, 90.0, 4.0, [24, 48, 72, 96], side="Pavilion",
                  index_offset=0.25, tier_name="G")
        make_tier(gem, 45.0, 3.2, [24, 48, 72, 96], side="Pavilion",
                  index_offset=0.25, tier_name="P")
        make_tier(gem, 40.0, 3.0, [24, 48, 72, 96], side="Crown",
                  index_offset=0.25, tier_name="C")
        make_tier(gem, 0.0, 1.5, [], side="Crown", tier_name="T")
        doc.recompute()
        design = gem_to_design(gem)
        values = [f.index for f in design.tiers[0].facets]
        assert values == [24.25, 48.25, 72.25, 0.25]
        reimported, _text = roundtrip(doc, gem)
        assert_geometric_identity(final_shape(gem), final_shape(reimported))

    def test_suppressed_tier_skipped(self, doc):
        gem = gem_feature.make_gem(doc, label="Sup", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        make_tier(gem, 90.0, 4.0, [24, 48, 72, 96], side="Pavilion")
        skipped = make_tier(gem, 0.0, 2.0, [], side="Crown")
        skipped.Suppressed = True
        doc.recompute()
        design = gem_to_design(gem)
        assert len(design.tiers) == 1


# ---------------------------------------------------------------------------
# Real sample files
# ---------------------------------------------------------------------------

@needs_samples
class TestSampleImports:
    def test_every_sample_imports_cleanly(self, doc):
        for path in all_samples():
            design = read_asc(path)
            gem = import_design(doc, design,
                                name=os.path.basename(path))
            specs = design_tier_specs(design)
            if not specs:
                continue
            # Every facet listed in the file exists on the final B-Rep and is
            # attributed to its tier by the ownership mechanism.
            owners = ownership.classify_faces(gem)
            tier_faces = sum(1 for owner in owners
                             if gem_feature.is_tier(owner))
            assert tier_faces == sum(len(s.indices) or 1 for s in specs), path

    def test_full_designs_leave_no_rough(self, doc):
        # The four mbparker designs are complete stones: every face of the
        # final shape belongs to a tier, none to the stock.
        for path in sorted(glob.glob(os.path.join(SAMPLES_DIR, "mbparker",
                                                  "*.asc"))):
            gem = import_design(doc, read_asc(path),
                                name=os.path.basename(path))
            owners = ownership.classify_faces(gem)
            stock_faces = [i for i, owner in enumerate(owners)
                           if not gem_feature.is_tier(owner)]
            assert not stock_faces, path

    def test_srb_metrics_match_published_dimension_table(self, doc):
        gem = import_design(doc, read_asc(sample("mbparker", "SRB.asc")),
                            name="SRB")
        report = reports.gem_report(gem)
        assert report["facet_count"] == 73
        assert report["lw_ratio"] == pytest.approx(1.000, abs=0.001)
        assert report["table_pct"] == pytest.approx(58.4, abs=0.06)
        assert report["pavilion_pct"] == pytest.approx(44.2, abs=0.06)
        assert report["crown_pct"] == pytest.approx(11.1, abs=0.06)
        vol_ratio = report["volume"] / report["width"] ** 3
        assert vol_ratio == pytest.approx(0.182, abs=0.0006)
        # Depth is pavilion + crown + girdle by construction.
        assert report["depth_pct"] == pytest.approx(
            report["pavilion_pct"] + report["crown_pct"]
            + report["girdle_pct"], abs=1e-6)

    def test_handedness_from_negative_gear(self, doc):
        gem = import_design(
            doc, read_asc(sample("mbparker", "CubeIllusionTri.asc")),
            name="Cube")
        assert gem.Handedness == "Clockwise"
        assert gem.IndexGear == 96

    def test_metadata_mapping(self, doc):
        gem = import_design(doc,
                            read_asc(sample("mbparker", "Compear125.asc")),
                            name="Pear")
        assert gem.DesignName == "05.101 Compear 1:1.25"
        assert gem.Author.startswith("Robert W. Strickland")
        assert gem.IntendedRI == pytest.approx(1.54)
        assert gem.AscSymmetryFolds == 1
        assert list(gem.AscFootnotes)


@needs_samples
class TestSampleRoundtrips:
    def test_export_reimport_geometric_identity(self, doc):
        for path in all_samples():
            design = read_asc(path)
            if not design.tiers:
                continue
            gem = import_design(doc, design, name=os.path.basename(path))
            reimported, _text = roundtrip(
                doc, gem, name=os.path.basename(path) + "_rt")
            assert_geometric_identity(final_shape(gem),
                                      final_shape(reimported))

    def test_empty_design_roundtrip(self, doc):
        design = read_asc(sample("sftdevstar", "sample-01.asc"))
        assert not design.tiers
        gem = import_design(doc, design, name="Empty")
        again = parse_asc(format_asc(gem_to_design(gem)))
        assert not again.tiers
        assert again.gear == design.gear
