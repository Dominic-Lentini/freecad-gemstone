# SPDX-License-Identifier: LGPL-2.1-or-later
"""RayTrace document objects and the results sheet (tree integration).

Trace Ray no longer draws a transient pivy overlay: each trace is a real
``Lapidary::RayTrace`` Part::FeaturePython nested under its study, and
``run_study`` materializes a ``Lapidary::OpticsResultsSheet`` object so
the results dock can be reopened from the tree. Requires FreeCAD.
"""

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.optics import ray_feature, study_feature  # noqa: E402
from test_pipeline import build_srb  # noqa: E402


@pytest.fixture
def doc():
    doc = FreeCAD.newDocument("ray_feature_test")
    try:
        yield doc
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.fixture
def study(doc):
    gem, _stock, _tiers = build_srb(doc)
    study = study_feature.make_study(gem)
    doc.recompute()
    return study


class TestRayTraceObject:
    def test_make_ray_trace_builds_edges(self, doc, study):
        trace = ray_feature.make_ray_trace(
            study, FreeCAD.Vector(0.5, 0.0, 20.0))
        doc.recompute()
        assert ray_feature.is_ray_trace(trace)
        assert trace.Study is study
        assert not trace.Shape.isNull()
        assert len(trace.Shape.Edges) >= 2   # incident + at least a bounce
        assert ray_feature.ray_traces_of(study) == [trace]

    def test_wavelength_defaults_to_sodium_d(self, doc, study):
        trace = ray_feature.make_ray_trace(
            study, FreeCAD.Vector(0.0, 0.0, 20.0))
        from freecad.lapidary.optics.materials import WAVELENGTH_D
        assert trace.WavelengthNm == pytest.approx(WAVELENGTH_D)

    def test_editing_pick_point_recomputes_the_path(self, doc, study):
        trace = ray_feature.make_ray_trace(
            study, FreeCAD.Vector(0.5, 0.0, 20.0))
        doc.recompute()
        before = [tuple(v.Point) for v in trace.Shape.Vertexes]
        trace.PickPoint = FreeCAD.Vector(-1.5, 0.5, 20.0)
        doc.recompute()
        after = [tuple(v.Point) for v in trace.Shape.Vertexes]
        assert before != after

    def test_miss_fails_soft_to_empty_shape(self, doc, study):
        trace = ray_feature.make_ray_trace(
            study, FreeCAD.Vector(500.0, 500.0, 20.0))
        doc.recompute()
        assert trace.Shape.isNull() or not trace.Shape.Edges

    def test_removable_like_any_feature(self, doc, study):
        trace = ray_feature.make_ray_trace(
            study, FreeCAD.Vector(0.5, 0.0, 20.0))
        doc.recompute()
        doc.removeObject(trace.Name)
        assert ray_feature.ray_traces_of(study) == []


class TestResultsSheet:
    def test_run_study_creates_the_sheet(self, doc, study):
        study.GridResolution = 24
        study.TiltMaxDeg = 10.0
        study.TiltSteps = 2
        doc.recompute()
        study_feature.run_study(study)
        sheet = study_feature.results_sheet_of(study)
        assert sheet is not None
        assert study_feature.is_results_sheet(sheet)
        assert sheet.Study is study

    def test_rerun_reuses_the_sheet(self, doc, study):
        study.GridResolution = 24
        study.TiltMaxDeg = 10.0
        study.TiltSteps = 2
        doc.recompute()
        study_feature.run_study(study)
        first = study_feature.results_sheet_of(study)
        study_feature.run_study(study)
        assert study_feature.results_sheet_of(study) is first

    def test_no_sheet_before_first_run(self, doc, study):
        assert study_feature.results_sheet_of(study) is None
