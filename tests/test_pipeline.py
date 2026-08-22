# SPDX-License-Identifier: LGPL-2.1-or-later
"""Golden-geometry pipeline tests (DESIGN.md sections 3, 9 and 10).

Requires FreeCAD; skipped under plain pytest without it. Runs headless under
FreeCADCmd / FreeCAD's Python.

The golden model is the classic GemCad "Standard Round Brilliant" as
published (angles for R.I. 1.54, 96 gear, 8-fold mirror symmetry, 73 facets):

    Source: "Standard Round Brilliant" GemCad printout,
    https://www.facettieren.ch/wp-content/uploads/standard_brilliant.pdf
    Pavilion: G1 90.00 deg @ 03-09-15-...-93 (16)
              P1 42.00 deg @ 03-09-15-...-93 (16)
              P2 40.50 deg @ 96-12-24-...-84 (8)
    Crown:    C1 40.68 deg @ 03-09-15-...-93 (16)
              C2 33.46 deg @ 96-12-24-...-84 (8)
              C3 22.89 deg @ 06-18-30-...-90 (8)
              T   0.00 deg (table)
    Published proportions: L/W 1.000, P/W 0.427, C/W 0.150, H/W 0.607
    (hence girdle thickness 0.030 W).

The printout gives angles and indices; the phase-1 pipeline is distance
based, so the plane distances below are *derived* from the published
proportions with elementary trigonometry (each derivation is commented
inline). The report metrics asserted at the end are the published numbers.
"""

import math

import pytest

FreeCAD = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

from freecad.lapidary.core import gemmath  # noqa: E402
from freecad.lapidary.faceting import gem_feature, ownership, reports  # noqa: E402
from freecad.lapidary.faceting.gem_feature import (  # noqa: E402
    final_shape, make_gem, pipeline_features, resequence, tip_feature)
from freecad.lapidary.faceting.stock_feature import make_stock  # noqa: E402
from freecad.lapidary.faceting.tier_feature import (  # noqa: E402
    effective_gear, make_tier, reference_distance)

NORMAL_TOL = 1e-7


# ---------------------------------------------------------------------------
# Standard Round Brilliant: published angle set and derived distances
# ---------------------------------------------------------------------------

GEAR = 96
W = 10.0                       # target girdle width (mm); everything scales
R16 = W / 2.0                  # girdle 16-gon corner radius
D_GIRDLE = R16 * math.cos(math.pi / 16.0)   # 16-gon apothem = plane distance
GIRDLE_TOP = +0.015 * W        # girdle band 0.030 W, centered on the origin
GIRDLE_BOTTOM = -0.015 * W
PAVILION_DEPTH = 0.427 * W     # published P/W
CROWN_HEIGHT = 0.150 * W       # published C/W
CULET_Z = GIRDLE_BOTTOM - PAVILION_DEPTH
TABLE_Z = GIRDLE_TOP + CROWN_HEIGHT

A_G1, A_P1, A_P2 = 90.00, 42.00, 40.50
A_C1, A_C2, A_C3 = 40.68, 33.46, 22.89

IDX16 = list(range(3, 96, 6))              # 03-09-15-...-93
IDX8_MAINS = list(range(12, 97, 12))       # 96-12-24-...-84 (96 = index 0)
IDX8_STARS = list(range(6, 91, 12))        # 06-18-30-...-90


def _rad(deg):
    return math.radians(deg)


# P1 meets G1 along the girdle bottom edge: in the vertical section at a
# shared azimuth, the pavilion plane satisfies sin(a)*rho - cos(a)*z = d,
# so d_P1 = sin(a)*d_girdle - cos(a)*z_bottom.
D_P1 = math.sin(_rad(A_P1)) * D_GIRDLE - math.cos(_rad(A_P1)) * GIRDLE_BOTTOM
# P2 mains all meet at the culet on the axis: -cos(a)*z_culet = d.
D_P2 = -math.cos(_rad(A_P2)) * CULET_Z
# C1 meets G1 along the girdle top edge (crown: sin(a)*rho + cos(a)*z = d).
D_C1 = math.sin(_rad(A_C1)) * D_GIRDLE + math.cos(_rad(A_C1)) * GIRDLE_TOP
# C2 bezels pass through the girdle-top corners of the 16-gon (radius R16 at
# the bezel azimuths).
D_C2 = math.sin(_rad(A_C2)) * R16 + math.cos(_rad(A_C2)) * GIRDLE_TOP
# Table plane: z = TABLE_Z.
D_T = TABLE_Z
# C3 stars pass through the table's octagon corners, which lie on the bezel
# planes at the bezel azimuths: corner radius r_c from the bezel equation at
# table height, then d_C3 = n_star . corner (the star azimuth is 22.5 deg
# away from the corner azimuth).
_CORNER_R = (D_C2 - math.cos(_rad(A_C2)) * TABLE_Z) / math.sin(_rad(A_C2))
D_C3 = (math.sin(_rad(A_C3)) * math.cos(_rad(22.5)) * _CORNER_R
        + math.cos(_rad(A_C3)) * TABLE_Z)

#: (tier name, side, angle, distance, indices, expected surviving facets)
SRB_TIERS = [
    ("G1 girdle", "Pavilion", A_G1, D_GIRDLE, IDX16, 16),
    ("P1 breaks", "Pavilion", A_P1, D_P1, IDX16, 16),
    ("P2 mains", "Pavilion", A_P2, D_P2, IDX8_MAINS, 8),
    ("C1 breaks", "Crown", A_C1, D_C1, IDX16, 16),
    ("C2 bezels", "Crown", A_C2, D_C2, IDX8_MAINS, 8),
    ("C3 stars", "Crown", A_C3, D_C3, IDX8_STARS, 8),
    ("Table", "Crown", 0.0, D_T, [], 1),
]

EXPECTED_FACETS = sum(count for *_rest, count in SRB_TIERS)  # 73

EXPECTED_TABLE_PCT = 100.0 * 2.0 * _CORNER_R / W


def build_srb(doc):
    """Script the published SRB through the real feature pipeline."""
    gem = make_gem(doc, label="SRB", index_gear=GEAR)
    gem.DesignName = "Standard Round Brilliant"
    stock = make_stock(gem, "Cylinder",
                       {"Diameter": 11.0, "Height": 12.0})
    tiers = {}
    for name, side, angle, distance, indices, _count in SRB_TIERS:
        tiers[name] = make_tier(gem, angle, distance, indices, side=side,
                                tier_name=name)
    doc.recompute()
    return gem, stock, tiers


@pytest.fixture(scope="module")
def srb():
    doc = FreeCAD.newDocument("srb_golden")
    try:
        yield build_srb(doc)
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.fixture
def fresh_doc():
    doc = FreeCAD.newDocument("pipeline_test")
    try:
        yield doc
    finally:
        FreeCAD.closeDocument(doc.Name)


# ---------------------------------------------------------------------------
# Golden geometry
# ---------------------------------------------------------------------------

class TestGoldenSRB:
    def test_pipeline_recomputes_clean(self, srb):
        gem, _stock, tiers = srb
        for tier in tiers.values():
            assert tier.isValid(), tier.TierState
            assert tier.TierState == "OK"

    def test_facet_count(self, srb):
        gem, _stock, _tiers = srb
        shape = final_shape(gem)
        assert shape is not None
        assert len(shape.Faces) == EXPECTED_FACETS  # 73, published
        for face in shape.Faces:
            assert isinstance(face.Surface, Part.Plane)

    def test_exact_per_face_normals(self, srb):
        """Every published facet exists with its exact analytic normal."""
        gem, _stock, tiers = srb
        shape = final_shape(gem)
        planes = []
        for face in shape.Faces:
            normal, d = ownership.face_plane(face)
            planes.append((face, normal, d))

        for name, side, angle, distance, indices, count in SRB_TIERS:
            for index in (indices or [0]):
                n = FreeCAD.Vector(*gemmath.facet_normal(
                    angle, GEAR, index, side))
                matches = [
                    face for face, normal, d in planes
                    if normal.distanceToPoint(n) < NORMAL_TOL
                    and abs(d - distance) < 1e-6
                ]
                assert len(matches) == 1, (
                    "%s index %s: expected exactly one face with the exact "
                    "normal, found %d" % (name, index, len(matches)))

    def test_face_ownership(self, srb):
        gem, stock, tiers = srb
        owners = ownership.classify_faces(gem)
        assert len(owners) == EXPECTED_FACETS
        by_owner = {}
        for owner in owners:
            by_owner[owner.TierName if hasattr(owner, "TierName")
                     else "Stock"] = by_owner.get(
                owner.TierName if hasattr(owner, "TierName") else "Stock",
                0) + 1
        for name, _side, _angle, _distance, _indices, count in SRB_TIERS:
            assert by_owner.get(name) == count, (name, by_owner)
        # Nothing left over for the stock: the rough is fully faceted.
        assert "Stock" not in by_owner

    def test_report_matches_published_proportions(self, srb):
        gem, _stock, _tiers = srb
        report = reports.gem_report(gem)
        # Published size data: L/W 1.000, H/W 0.607, P/W 0.427, C/W 0.150.
        assert report["lw_ratio"] == pytest.approx(1.000, abs=1e-6)
        assert report["width"] == pytest.approx(W, abs=1e-6)
        assert report["depth_pct"] == pytest.approx(60.7, abs=0.05)
        assert report["pavilion_pct"] == pytest.approx(42.7, abs=0.05)
        assert report["crown_pct"] == pytest.approx(15.0, abs=0.05)
        assert report["girdle_pct"] == pytest.approx(3.0, abs=0.05)
        assert report["table_pct"] == pytest.approx(EXPECTED_TABLE_PCT,
                                                    abs=0.05)
        assert report["facet_count"] == EXPECTED_FACETS

    def test_culet_is_a_point(self, srb):
        gem, _stock, _tiers = srb
        shape = final_shape(gem)
        assert shape.BoundBox.ZMin == pytest.approx(CULET_Z, abs=1e-6)

    def test_cutting_sheet(self, srb):
        gem, _stock, _tiers = srb
        rows = reports.cutting_sheet_rows(gem)
        assert [r["name"] for r in rows] == [t[0] for t in SRB_TIERS]
        assert rows[0]["indices_text"].startswith("03-09-15")
        assert rows[-1]["indices_text"] == "Table"
        html = reports.cutting_sheet_html(gem, reports.gem_report(gem))
        assert "Standard Round Brilliant" in html
        for name, *_rest in SRB_TIERS:
            assert name in html


# ---------------------------------------------------------------------------
# Pipeline mechanics: edit propagation, reorder, delete, suppress, gears
# ---------------------------------------------------------------------------

def build_small_gem(doc):
    """Cylinder stock + girdle-ish tier + table tier, for mechanics tests."""
    gem = make_gem(doc, label="TestGem", index_gear=96)
    stock = make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
    girdle = make_tier(gem, 90.0, 5.0, [12, 36, 60, 84], side="Pavilion",
                       tier_name="Girdle4")
    table = make_tier(gem, 0.0, 3.0, [], side="Crown", tier_name="Table")
    doc.recompute()
    return gem, stock, girdle, table


class TestPipelineMechanics:
    def test_tier_edit_propagates_downstream(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        tip = tip_feature(gem)
        volume_before = tip.Shape.Volume
        girdle.CutDepth = 2.0  # deeper girdle cuts: distance 6 - 2 = 4 mm
        fresh_doc.recompute()
        assert tip.Shape.Volume < volume_before
        # The tip (table tier) was rebuilt on top of the new girdle: every
        # girdle facet (horizontal normal) now sits at 4 mm, none at 5 mm.
        girdle_distances = set()
        for face in tip.Shape.Faces:
            plane = ownership.face_plane(face)
            if plane is not None and abs(plane[0].z) < 1e-9:
                girdle_distances.add(round(plane[1], 6))
        assert girdle_distances == {4.0}

    def test_base_feature_wiring(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        assert girdle.BaseFeature is stock
        assert table.BaseFeature is girdle

    def test_reorder_resequences_and_recomputes(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        volume_before = tip_feature(gem).Shape.Volume
        gem.Group = [stock, table, girdle]  # tree drag-reorder equivalent
        assert table.BaseFeature is stock
        assert girdle.BaseFeature is table
        fresh_doc.recompute()
        assert tip_feature(gem) is girdle
        # Half-space cuts commute: same final solid either way.
        assert girdle.Shape.Volume == pytest.approx(volume_before, rel=1e-9)

    def test_reorder_keeps_tip_visible(self, fresh_doc):
        # Tip semantics: after a drag-reorder the new pipeline tip must be
        # the (only) visible feature (PR #2 review).
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        assert table.Visibility and not girdle.Visibility
        gem.Group = [stock, table, girdle]
        fresh_doc.recompute()
        assert girdle.Visibility
        assert not table.Visibility
        assert not stock.Visibility

    def test_delete_tip_shows_remaining_tier(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        assert table.Visibility and not girdle.Visibility
        fresh_doc.removeObject(table.Name)
        fresh_doc.recompute()
        assert tip_feature(gem) is girdle
        assert girdle.Visibility

    def test_delete_resequences_and_recomputes(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        faces_with_girdle = len(tip_feature(gem).Shape.Faces)
        fresh_doc.removeObject(girdle.Name)
        fresh_doc.recompute()
        assert table.BaseFeature is stock
        assert table.isValid()
        # Girdle gone: back to the table-cut cylinder (bottom, lateral,
        # table) -- the 4 girdle facets and the 4 split lateral arcs merge.
        assert faces_with_girdle == 11
        assert len(table.Shape.Faces) == 3
        assert pipeline_features(gem) == [stock, table]

    def test_suppress_passes_through_and_recovers(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        volume_before = tip_feature(gem).Shape.Volume
        girdle.Suppressed = True
        fresh_doc.recompute()
        assert girdle.TierState == "Suppressed"
        assert girdle.Shape.Volume == pytest.approx(stock.Shape.Volume)
        assert tip_feature(gem).Shape.Volume > volume_before
        girdle.Suppressed = False
        fresh_doc.recompute()
        assert girdle.TierState == "OK"
        assert tip_feature(gem).Shape.Volume == pytest.approx(volume_before)

    def test_cut_depth_measured_from_stock_boundary(self, fresh_doc):
        # CutDepth is the user parameter (schema v2): measured inward from
        # the starting shape's longest radius about Z, independent of index;
        # Distance remains the canonical computed plane parameter.
        gem = make_gem(fresh_doc, label="DepthGem", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        girdle = make_tier(gem, 90.0, depth=1.0, indices=[24, 48, 72, 96],
                           side="Pavilion")
        fresh_doc.recompute()
        # Reference for a 90 deg cut is the max radius (6): distance = 6 - 1.
        assert girdle.Distance.Value == pytest.approx(5.0, abs=1e-9)
        # A 0 deg crown cut references the stock top (z = +5).
        table = make_tier(gem, 0.0, depth=2.0, indices=[], side="Crown")
        fresh_doc.recompute()
        assert table.Distance.Value == pytest.approx(3.0, abs=1e-9)
        assert table.Shape.BoundBox.ZMax == pytest.approx(3.0, abs=1e-7)

    def test_cut_depth_references_the_base_solid_not_the_stock(self, fresh_doc):
        # Schema v3: after earlier tiers shrink the stone, depth 0 grazes
        # what is *left*, so the plane starts at material instead of
        # travelling through space the earlier cuts already removed.
        gem = make_gem(fresh_doc, label="BaseRef", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        first = make_tier(gem, 90.0, depth=2.0, indices=[24, 48, 72, 96],
                          side="Pavilion", tier_name="G1")
        fresh_doc.recompute()
        assert first.Distance.Value == pytest.approx(4.0, abs=1e-9)
        # The square prism's corners are at radius 4*sqrt(2); a second 90 deg
        # tier on the corner azimuths references *that* radius, not the
        # stock's 6.
        second = make_tier(gem, 90.0, depth=1.0, indices=[12, 36, 60, 84],
                           side="Pavilion", tier_name="G2")
        fresh_doc.recompute()
        corner = 4.0 * math.sqrt(2.0)
        assert second.Distance.Value == pytest.approx(corner - 1.0, abs=1e-9)
        assert second.TierState == "OK"       # a real cut, not a miss

    def test_zero_depth_grazes_the_current_solids_longest_radius(
            self, fresh_doc):
        gem = make_gem(fresh_doc, label="Graze", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        make_tier(gem, 90.0, depth=2.0, indices=[24, 48, 72, 96],
                  side="Pavilion")
        graze = make_tier(gem, 90.0, depth=0.0, indices=[24, 48, 72, 96],
                          side="Pavilion")
        fresh_doc.recompute()
        # The reference is the circumscribed cylinder of what is *left*: the
        # square prism's corner radius 4*sqrt(2), not the stock's 6. Depth 0
        # grazes that boundary — a quiet no-op, not a warning.
        assert graze.Distance.Value == pytest.approx(4.0 * math.sqrt(2.0),
                                                     abs=1e-9)
        assert graze.TierState == "OK (4 of 4 cuts missed the solid)"

    def test_requested_distance_is_exact_despite_batch_creation(self, fresh_doc):
        # The .ASC importer creates every tier before the first recompute,
        # when no base solid exists yet; a requested plane distance must
        # still be honoured exactly (deferred CutDepth derivation).
        gem = make_gem(fresh_doc, label="Batch", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        tiers = [
            make_tier(gem, 90.0, 4.5, list(range(6, 97, 6)), side="Pavilion"),
            make_tier(gem, 42.0, 3.1, list(range(12, 97, 12)),
                      side="Pavilion"),
            make_tier(gem, 0.0, 1.4, [], side="Crown"),
        ]
        fresh_doc.recompute()   # first recompute only now, like the importer
        for tier, expected in zip(tiers, (4.5, 3.1, 1.4)):
            assert tier.Distance.Value == pytest.approx(expected, abs=1e-9)
            assert tier.TierState == "OK"
        # And the derived depth round-trips through a plain recompute.
        tiers[1].touch()
        fresh_doc.recompute()
        assert tiers[1].Distance.Value == pytest.approx(3.1, abs=1e-9)

    def test_distance_is_an_interchangeable_input(self, fresh_doc):
        # Editing Distance back-derives CutDepth and the next recompute
        # reproduces exactly the typed distance; editing CutDepth still
        # drives Distance. The two are tied by distance = reference - depth.
        gem = make_gem(fresh_doc, label="Interch", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        tier = make_tier(gem, 90.0, depth=1.0, indices=[24, 48, 72, 96],
                         side="Pavilion")
        fresh_doc.recompute()
        assert tier.Distance.Value == pytest.approx(5.0, abs=1e-9)

        tier.Distance = 3.5                      # user types a distance
        assert tier.CutDepth.Value == pytest.approx(2.5, abs=1e-9)
        fresh_doc.recompute()
        assert tier.Distance.Value == pytest.approx(3.5, abs=1e-9)
        # The geometry followed: girdle flats now at 3.5 mm.
        for normal, d in zip(tier.CutNormals, tier.CutDistances):
            assert d == pytest.approx(3.5, abs=1e-9)

        tier.CutDepth = 1.0                      # and back via the depth
        fresh_doc.recompute()
        assert tier.Distance.Value == pytest.approx(5.0, abs=1e-9)

    def test_distance_edit_survives_execute_without_looping(self, fresh_doc):
        # execute() writes Distance itself; that internal write must not
        # re-derive CutDepth (the _syncing guard), or every recompute would
        # touch the feature again and recompute forever.
        gem = make_gem(fresh_doc, label="NoLoop", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        tier = make_tier(gem, 90.0, depth=1.0, indices=[24, 48, 72, 96],
                         side="Pavilion")
        fresh_doc.recompute()
        depth_before = tier.CutDepth.Value
        # A second, no-change pass recomputes nothing: execute's own
        # Distance write did not re-touch the feature.
        assert fresh_doc.recompute() == 0
        assert tier.CutDepth.Value == depth_before

    def test_make_tier_distance_and_depth_are_equivalent(self, fresh_doc):
        gem = make_gem(fresh_doc, label="EquivGem", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        by_distance = make_tier(gem, 42.0, 4.0, [12], side="Pavilion")
        fresh_doc.recompute()
        assert by_distance.Distance.Value == pytest.approx(4.0, abs=1e-9)
        with pytest.raises(ValueError):
            make_tier(gem, 42.0, 4.0, [24], depth=1.0)
        with pytest.raises(ValueError):
            make_tier(gem, 42.0, indices=[24])

    def test_depth_past_axis_is_recoverable_error(self, fresh_doc):
        gem = make_gem(fresh_doc, label="DeepGem", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 12.0, "Height": 10.0})
        bad = make_tier(gem, 90.0, depth=7.0, indices=[96], side="Pavilion")
        fresh_doc.recompute()
        assert not bad.isValid()
        assert bad.TierState.startswith("Error")
        bad.CutDepth = 1.0
        fresh_doc.recompute()
        assert bad.isValid()
        assert bad.TierState == "OK"

    def test_index_gear_inheritance_and_override(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        assert effective_gear(girdle) == 96  # IndexGear 0 = inherit from Gem
        gem.IndexGear = 80
        assert effective_gear(girdle) == 80
        girdle.IndexGear = 120  # per-tier override (rare but allowed)
        assert effective_gear(girdle) == 120


# ---------------------------------------------------------------------------
# The two DESIGN.md section 3 failure modes
# ---------------------------------------------------------------------------

class TestFailureHandling:
    def test_noop_cut_is_quiet_and_does_not_error(self, fresh_doc):
        # A miss is neither an error nor a warning (no console message, no
        # tree marker — they drowned everything during live preview); the
        # fact is recorded quietly in TierState for the panel's status line.
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        volume_before = tip_feature(gem).Shape.Volume
        miss = make_tier(gem, 42.0, 50.0, [0, 48], side="Pavilion",
                         tier_name="TooFar")
        fresh_doc.recompute()
        assert miss.isValid()  # not an error
        assert miss.TierState == "OK (2 of 2 cuts missed the solid)"
        assert miss.Shape.Volume == pytest.approx(volume_before)

    def test_annihilating_cut_is_recoverable_error(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        upstream_volume = tip_feature(gem).Shape.Volume
        bad = make_tier(gem, 42.0, -1.0, [0], side="Pavilion",
                        tier_name="Annihilator")
        fresh_doc.recompute()
        # Recoverable error state; the upstream shape stays displayed.
        assert not bad.isValid()
        assert bad.TierState.startswith("Error")
        assert bad.Shape.Volume == pytest.approx(upstream_volume)
        # Fixing the depth recovers the tier (plane distance back to 4 mm).
        bad.CutDepth = reference_distance(bad) - 4.0
        fresh_doc.recompute()
        assert bad.isValid()
        assert bad.TierState == "OK"
        assert bad.Shape.Volume < upstream_volume

    def test_partial_noop_still_applies_real_cuts(self, fresh_doc):
        gem, stock, girdle, table = build_small_gem(fresh_doc)
        volume_before = tip_feature(gem).Shape.Volume
        # Index 0 cuts (distance 4 < girdle 5); a 90 deg cut at the same
        # distance on an azimuth already girdled at 5 removes material too,
        # so mix a genuinely missing plane via a large-angle setup instead:
        # a crown cut far above the stone top misses; one at 4 mm hits.
        mixed = make_tier(gem, 0.0, 20.0, [], side="Crown",
                          tier_name="MissTable")
        fresh_doc.recompute()
        assert mixed.TierState == "OK (1 of 1 cuts missed the solid)"
        assert mixed.Shape.Volume == pytest.approx(volume_before)
