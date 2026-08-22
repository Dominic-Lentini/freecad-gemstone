# SPDX-License-Identifier: LGPL-2.1-or-later
"""OpticsStudy document-object tests (DESIGN_OPTICS.md section 7).

Requires FreeCAD; skipped under plain pytest without it. Covers creation,
the geometry fingerprint, the Stale flag lifecycle, headless study
execution with in-document results, and cancellation.
"""

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.optics import study_feature  # noqa: E402
from freecad.lapidary.optics.polytope import PolytopeError  # noqa: E402
from freecad.lapidary.optics.tracer import TraceCancelled  # noqa: E402
from test_pipeline import build_srb  # noqa: E402


@pytest.fixture
def doc():
    doc = FreeCAD.newDocument("optics_study_test")
    try:
        yield doc
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.fixture
def srb(doc):
    return build_srb(doc)


def _fast_inputs(study):
    """Make the study cheap enough for CI."""
    study.GridResolution = 24
    study.TiltMaxDeg = 10.0
    study.TiltSteps = 2
    study.Document.recompute()


class TestStudyObject:
    def test_creation_under_the_gem(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        assert study in gem.Group
        assert study_feature.is_study(study)
        assert study_feature.find_studies(gem) == [study]
        assert study.Stale            # never run
        # Creating the study must not disturb the modeling pipeline.
        gem.Document.recompute()
        from freecad.lapidary.faceting.gem_feature import tip_feature
        assert tip_feature(gem).isValid()
        assert len(tip_feature(gem).Shape.Faces) == 73

    def test_material_preset_copies_constants(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        study.MaterialPreset = "Diamond"
        assert study.RefractiveIndex == pytest.approx(2.417)
        assert study.Dispersion == pytest.approx(0.044)
        material = study_feature.study_material(study)
        assert material.name == "Diamond"
        # Overriding a constant turns the material custom.
        study.RefractiveIndex = 2.3
        assert "custom" in study_feature.study_material(study).name

    def test_cosmetic_appearance_is_a_headless_noop(self, srb):
        # The viewport tint applies only under a GUI; headless it must
        # decline quietly (and preset switching above already proves the
        # onChanged path does not crash without one).
        from freecad.lapidary.optics import appearance, materials
        gem, _stock, _tiers = srb
        assert appearance.apply_material_appearance(
            gem, materials.PRESETS["Corundum"]) is False

    def test_fingerprint_is_stable_across_recomputes(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        fp1 = study_feature.geometry_fingerprint(gem, study)
        gem.Document.recompute()
        fp2 = study_feature.geometry_fingerprint(gem, study)
        assert fp1 == fp2 and fp1 and not fp1.startswith("invalid")


class TestRunAndStaleness:
    def test_run_stores_results_in_document(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        fractions = []
        study_feature.run_study(study, progress=lambda f: (
            fractions.append(f) or True))
        assert not study.Stale
        assert 0.0 < study.LightReturnPct < 100.0
        assert 0.0 < study.LeakPct < 100.0
        assert len(study.TiltAngles) == 2
        assert study.TiltAngles[0] == 0.0
        assert len(study.TiltBrightness) == 2
        assert study.RuntimeS > 0.0
        assert 0.0 < study.MeanPathLength <= study.MaxPathLength
        assert "Internal path length" in study.ResultSummary
        assert "Light return" in study.ResultSummary
        assert "not comparable" in study.ResultSummary
        assert fractions and fractions[-1] == pytest.approx(1.0)
        # Phase 4b: per-tier rows stored as parallel list properties.
        assert len(study.TierNames) == 8          # 7 tiers + "(none)"
        assert len(study.TierReturnPct) == 8
        assert len(study.TierLeakPct) == 8
        # Phase 4b: maps embedded via PropertyFileIncluded.
        import os
        for prop in ("BrightnessMapFile", "ClassificationMapFile",
                     "TiltMapsFile", "TiltCurveFile"):
            path = getattr(study, prop)
            assert path and os.path.isfile(path), prop
            with open(path, "rb") as stream:
                assert stream.read(8) == b"\x89PNG\r\n\x1a\n", prop
        # Fresh results survive a plain recompute.
        gem.Document.recompute()
        assert not study.Stale

    def test_geometry_edit_flips_stale_and_revert_clears_it(self, srb):
        gem, _stock, tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        study_feature.run_study(study)
        assert not study.Stale

        table = tiers["Table"]
        original = table.Distance.Value
        table.Distance = original - 0.1
        gem.Document.recompute()
        assert study.Stale
        # Reverting the geometry restores the stored fingerprint.
        table.Distance = original
        gem.Document.recompute()
        assert not study.Stale

    def test_input_edit_flips_stale(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        study_feature.run_study(study)
        study.HeadShadowDeg = 12.0
        gem.Document.recompute()
        assert study.Stale

    def test_cancel_leaves_results_untouched(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        with pytest.raises(TraceCancelled):
            study_feature.run_study(study, progress=lambda f: False)
        assert study.Stale
        assert study.ResultSummary == ""

    def test_multiwavelength_run_stores_fire_results(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        study.Wavelengths = "3"
        study.TiltSteps = 0
        gem.Document.recompute()
        study_feature.run_study(study)
        assert study.FireIndex > 0.0
        assert list(study.WavelengthsNm) == [486.1, 589.3, 656.3]
        assert len(study.WavelengthBrightness) == 3
        import os
        path = study.SpreadMapFile
        assert path and os.path.isfile(path)
        with open(path, "rb") as stream:
            assert stream.read(8) == b"\x89PNG\r\n\x1a\n"
        assert "Lapidary Fire Index" in study.ResultSummary
        assert "not comparable" in study.ResultSummary
        # Switching back to a single wavelength clears the fire results.
        study.Wavelengths = "1"
        gem.Document.recompute()
        assert study.Stale
        study_feature.run_study(study)
        assert study.FireIndex == 0.0
        assert list(study.WavelengthsNm) == []

    def test_absorption_input_participates(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        assert study.AbsorptionPerMM == 0.0        # off by default
        study_feature.run_study(study)
        baseline = study.LightReturnPct
        study.AbsorptionPerMM = 0.2
        gem.Document.recompute()
        assert study.Stale                          # fingerprint input
        study_feature.run_study(study)
        assert study.LightReturnPct < baseline
        assert "APPROXIMATE" in study.ResultSummary

    def test_lighting_choices_build(self, srb):
        gem, _stock, _tiers = srb
        study = study_feature.make_study(gem)
        for model in study_feature.LIGHTING_MODELS:
            study.LightingModel = model
            assert study_feature.study_lighting(study) is not None
        study.HeadShadowDeg = 10.0
        assert "head shadow" in study_feature.study_lighting(
            study).describe()

    def test_invalid_geometry_raises_actionably(self, doc):
        from freecad.lapidary.faceting.gem_feature import make_gem
        from freecad.lapidary.faceting.stock_feature import make_stock
        from freecad.lapidary.faceting.tier_feature import make_tier

        gem = make_gem(doc, label="Curved", index_gear=96)
        make_stock(gem, "Cylinder", {"Diameter": 10.0, "Height": 8.0})
        make_tier(gem, 0.0, 3.0, [], side="Crown", tier_name="Table")
        doc.recompute()
        study = study_feature.make_study(gem)
        with pytest.raises(PolytopeError, match="girdle"):
            study_feature.run_study(study)
        assert study.Stale


class TestSaveRestore:
    def test_results_survive_save_and_reload(self, tmp_path):
        doc = FreeCAD.newDocument("optics_study_saveload")
        gem, _stock, _tiers = build_srb(doc)
        study = study_feature.make_study(gem)
        _fast_inputs(study)
        study_feature.run_study(study)
        stored = (study.LightReturnPct, study.ResultSummary,
                  study.Fingerprint)
        path = str(tmp_path / "srb_study.FCStd")
        doc.saveAs(path)
        FreeCAD.closeDocument(doc.Name)
        reloaded = FreeCAD.openDocument(path)
        try:
            studies = [o for o in reloaded.Objects
                       if study_feature.is_study(o)]
            assert len(studies) == 1
            study2 = studies[0]
            assert (study2.LightReturnPct, study2.ResultSummary,
                    study2.Fingerprint) == stored
            # The embedded maps travel inside the .FCStd (Phase 4b).
            import os
            path = study2.BrightnessMapFile
            assert path and os.path.isfile(path)
            with open(path, "rb") as stream:
                assert stream.read(8) == b"\x89PNG\r\n\x1a\n"
            reloaded.recompute()
            assert not study2.Stale
        finally:
            FreeCAD.closeDocument(reloaded.Name)
