# SPDX-License-Identifier: LGPL-2.1-or-later
"""Property / metamorphic tests and the performance smoke report
(DESIGN_OPTICS.md section 10).

Boundary-pixel caveat, shared by several tests here: a metamorphic
transform (rotating the stone, scaling it) changes the floating-point
representation of the plane set, so a pixel whose ray path grazes a facet
edge or sits on the TIR knife edge may legitimately flip. The mass of the
map must be unchanged; assertions therefore use high quantiles plus the
headline number, not the per-pixel max. No FreeCAD needed.
"""

import time

import numpy as np
import pytest

import optics_fixtures as fx
from freecad.lapidary.optics import metrics
from freecad.lapidary.optics import polytope as pt
from freecad.lapidary.optics import tracer as tr

QUARTZ_N = 1.54


def _rotate_polytope(poly, rot):
    return pt.Polytope((rot @ poly.normals.T).T, poly.dists.copy(),
                       poly.tier_ids.copy(), poly.tier_labels,
                       poly.tier_sides)


class TestRotationInvariance:
    def test_rotating_stone_grid_and_lighting_together_changes_nothing(self):
        """Rotate the stone by M and view it with the same M as the grid
        tilt: every ray then meets the same geometry, so all maps must
        match the untilted trace of the unrotated stone."""
        poly = fx.srb_polytope()
        base = tr.trace(poly, QUARTZ_N, resolution=48)
        rot = tr.view_rotation(17.0, 33.0)
        tilted = tr.trace(_rotate_polytope(poly, rot), QUARTZ_N,
                          resolution=48, tilt_deg=17.0,
                          tilt_azimuth_deg=33.0)
        assert np.array_equal(base.hit_mask, tilted.hit_mask)
        diff = np.abs(base.brightness - tilted.brightness)
        assert float(np.quantile(diff, 0.995)) < 1e-7
        assert metrics.brightness_pct(base) == pytest.approx(
            metrics.brightness_pct(tilted), abs=0.05)
        assert np.allclose(base.tier_return, tilted.tier_return, atol=0.05)


class TestScaleInvariance:
    def test_uniform_scaling_changes_nothing(self):
        """No absorption in the base model, and every tolerance scales
        with the stone, so a scaled gem traces identically."""
        poly = fx.srb_polytope()
        scaled = pt.Polytope(poly.normals.copy(), poly.dists * 3.7,
                             poly.tier_ids.copy(), poly.tier_labels,
                             poly.tier_sides)
        base = tr.trace(poly, QUARTZ_N, resolution=48)
        big = tr.trace(scaled, QUARTZ_N, resolution=48)
        assert np.array_equal(base.hit_mask, big.hit_mask)
        diff = np.abs(base.brightness - big.brightness)
        assert float(np.quantile(diff, 0.995)) < 1e-9
        assert metrics.brightness_pct(base) == pytest.approx(
            metrics.brightness_pct(big), abs=0.01)
        # Path length is the one quantity that is NOT scale-invariant:
        # it is a physical distance and scales linearly with the stone.
        assert metrics.mean_path_length(big) == pytest.approx(
            3.7 * metrics.mean_path_length(base), rel=1e-6)
        assert big.max_path_length == pytest.approx(
            3.7 * base.max_path_length, rel=1e-6)


class TestGridConvergence:
    def test_headline_number_converges_under_refinement(self):
        """Refining the grid must settle the headline number: each
        refinement step's change stays within the documented band and does
        not grow. (The value converges to the continuum mean over the
        silhouette; successive deltas shrink roughly with pixel count.)"""
        poly = fx.srb_polytope()
        values = [metrics.brightness_pct(
            tr.trace(poly, QUARTZ_N, resolution=r)) for r in (64, 128, 256)]
        d1 = abs(values[1] - values[0])
        d2 = abs(values[2] - values[1])
        assert d1 < 1.0        # documented band: < 1 percentage point
        assert d2 < 0.5
        assert d2 <= d1 + 0.05  # not diverging


class TestDeterminism:
    def test_identical_inputs_identical_bytes(self):
        poly = fx.srb_polytope()
        a = tr.trace(poly, QUARTZ_N, resolution=32, tilt_deg=7.0)
        b = tr.trace(poly, QUARTZ_N, resolution=32, tilt_deg=7.0)
        for name in ("brightness", "delivered", "leaked", "pruned",
                     "head_energy", "class_map"):
            assert getattr(a, name).tobytes() == getattr(b, name).tobytes(), \
                name
        assert a.tier_return.tobytes() == b.tier_return.tobytes()

    def test_progress_callback_does_not_change_results(self):
        poly = fx.srb_polytope()
        a = tr.trace(poly, QUARTZ_N, resolution=32)
        b = tr.trace(poly, QUARTZ_N, resolution=32,
                     progress=lambda frac: True)
        assert a.brightness.tobytes() == b.brightness.tobytes()

    def test_cancellation_raises(self):
        with pytest.raises(tr.TraceCancelled):
            tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32,
                     progress=lambda frac: False)


class TestPerformanceSmoke:
    def test_srb_128_runtime_report(self):
        """Reports (does not assert) the SRB runtime at 128^2 — the
        DESIGN_OPTICS.md section 10 target is 'tens of seconds or better'
        at 256^2; 128^2 is the CI-friendly proxy."""
        poly = fx.srb_polytope()
        start = time.perf_counter()
        result = tr.trace(poly, QUARTZ_N, resolution=128)
        elapsed = time.perf_counter() - start
        print("\n[perf] SRB 128x128, depth %d, 1 wavelength: %.2f s "
              "(%.0f rays hit, brightness %.1f %%)"
              % (result.max_depth, elapsed, result.num_hit,
                 metrics.brightness_pct(result)))
