# SPDX-License-Identifier: LGPL-2.1-or-later
"""Vectorized-tracer vs. independent-scalar-tracer agreement
(DESIGN_OPTICS.md section 10).

Both implementations trace the same low-resolution grids through fixture
designs; per-pixel divergence fails the build naming the first differing
pixel and quantity. Independent implementations rarely share bugs, so this
is the strongest correctness evidence the module has. No FreeCAD needed.
"""

import numpy as np
import pytest

import optics_fixtures as fx
import reference_tracer as ref
from freecad.lapidary.optics import tracer as tr

RES = 32
TOL = 1e-7


def _uniform_hemisphere(direction):
    return 1.0 if direction[2] > 0.0 else 0.0


def _compare(poly, n_gem, tilt_deg=0.0):
    result = tr.trace(poly, n_gem, resolution=RES, tilt_deg=tilt_deg)
    planes, is_pav, face_tier, num_tiers = fx.as_reference_input(poly)
    # Path length accumulates the epsilon nudge over bounces, so the two
    # implementations must use the *same* epsilon for it to agree tightly.
    eps = 1e-7 * poly.bounding_radius()
    grid = ref.trace_grid(planes, is_pav, face_tier, num_tiers, n_gem,
                          RES, result.extent, _uniform_hemisphere,
                          tilt_deg=tilt_deg, eps=eps)

    for iy in range(RES):
        for ix in range(RES):
            pixel = grid[iy][ix]
            where = "pixel (iy=%d, ix=%d)" % (iy, ix)
            assert pixel.hit == bool(result.hit_mask[iy, ix]), \
                "hit mask differs at %s" % where
            if not pixel.hit:
                continue
            for name, mine, theirs in (
                    ("brightness", result.brightness[iy, ix],
                     pixel.brightness),
                    ("delivered", result.delivered[iy, ix],
                     pixel.delivered),
                    ("leaked", result.leaked[iy, ix], pixel.leaked),
                    ("pruned", result.pruned[iy, ix], pixel.pruned),
                    # Path sums scale with the stone (SRB paths run to
                    # ~100 mm), so they get a relative term as well.
                    ("path_energy", result.path_length_sum[iy, ix],
                     pixel.path_energy)):
                assert mine == pytest.approx(theirs, abs=TOL, rel=1e-9), \
                    "first divergence: %s branch at %s (%r vs %r)" % (
                        name, where, mine, theirs)

    # Per-tier attribution totals agree too.
    ref_return = np.sum([[p.tier_return for p in row] for row in grid],
                        axis=(0, 1))
    ref_leak = np.sum([[p.tier_leak for p in row] for row in grid],
                      axis=(0, 1))
    assert np.allclose(result.tier_return, ref_return, atol=RES * RES * TOL)
    assert np.allclose(result.tier_leak, ref_leak, atol=RES * RES * TOL)
    ref_max_path = max(max(p.max_path for p in row) for row in grid)
    assert result.max_path_length == pytest.approx(ref_max_path, abs=TOL,
                                                   rel=1e-9)


class TestMapLevelAgreement:
    """Phase 4b: render low-resolution *maps* from both engines and
    assert per-pixel agreement of the rendered images (DESIGN_OPTICS.md
    section 10 / 4b task 4). The scalar tracer's arrays go through the
    same imaging formulas, so this validates the whole
    trace -> classify -> quantize -> encode chain."""

    def _images(self, poly, n_gem):
        from freecad.lapidary.optics import imaging

        result = tr.trace(poly, n_gem, resolution=RES)
        planes, is_pav, face_tier, num_tiers = fx.as_reference_input(poly)
        eps = 1e-7 * poly.bounding_radius()
        grid = ref.trace_grid(planes, is_pav, face_tier, num_tiers, n_gem,
                              RES, result.extent, _uniform_hemisphere,
                              eps=eps)
        # Reference-side arrays (the imaging formulas restated on plain
        # scalar-tracer output).
        bright = np.array([[p.brightness for p in row] for row in grid])
        hit = np.array([[p.hit for p in row] for row in grid])
        delivered = np.array([[p.delivered for p in row] for row in grid])
        leaked = np.array([[p.leaked for p in row] for row in grid])
        head = np.array([[p.head for p in row] for row in grid])
        gray = np.round(255.0 * np.clip(bright, 0.0, 1.0)).astype(np.uint8)
        ref_bright = np.stack(
            [gray, gray, gray,
             np.where(hit, 255, 0).astype(np.uint8)], axis=2)[::-1]
        winner = np.argmax(np.stack([delivered - head, leaked, head]),
                           axis=0)
        codes = np.array([tr.CLASS_LIT, tr.CLASS_WINDOW, tr.CLASS_HEAD])
        ref_class = np.where(hit, codes[winner], tr.CLASS_MISS)
        ref_class_img = imaging.CLASS_COLORS[ref_class][::-1]
        return (imaging.brightness_image(result), ref_bright,
                imaging.classification_image(result), ref_class_img)

    @pytest.mark.parametrize("case", ["srb", "wedge"])
    def test_rendered_maps_agree(self, case):
        poly = (fx.srb_polytope() if case == "srb"
                else fx.wedge_polytope(38.0))
        mine_b, ref_b, mine_c, ref_c = self._images(poly, 1.54)
        # Brightness: identical up to one gray level (a float diff of
        # ~1e-7 can flip a value sitting exactly on a rounding boundary).
        diff = np.abs(mine_b.astype(int) - ref_b.astype(int))
        assert diff.max() <= 1, \
            "brightness maps diverge at %s" % (np.argwhere(diff > 1)[:1],)
        assert np.array_equal(mine_b[:, :, 3], ref_b[:, :, 3])
        assert np.array_equal(mine_c, ref_c), \
            "classification maps diverge at %s" % (
                np.argwhere(np.any(mine_c != ref_c, axis=2))[:1],)


class TestAgreement:
    def test_cube(self):
        from freecad.lapidary.optics.polytope import cube
        _compare(cube(1.0), 1.5)

    def test_slab(self):
        _compare(fx.slab_polytope(), 1.5)

    def test_prism(self):
        _compare(fx.prism_polytope(), 1.6)

    def test_windowing_wedge(self):
        _compare(fx.wedge_polytope(38.0), 1.54)

    def test_srb_quartz(self):
        _compare(fx.srb_polytope(), 1.54)

    def test_srb_diamond(self):
        _compare(fx.srb_polytope(), 2.417)

    def test_srb_tilted(self):
        _compare(fx.srb_polytope(), 1.54, tilt_deg=12.5)
