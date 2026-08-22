# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lighting model and Occluder protocol tests (DESIGN_OPTICS.md section 5)."""

import math

import numpy as np
import pytest

from freecad.lapidary.optics import lighting


UP = [0.0, 0.0, 1.0]
DOWN = [0.0, 0.0, -1.0]
HORIZONTAL = [1.0, 0.0, 0.0]


def _elev(deg):
    return [math.cos(math.radians(deg)), 0.0, math.sin(math.radians(deg))]


class TestModels:
    def test_uniform_hemisphere(self):
        model = lighting.UniformHemisphere()
        assert list(model.intensity([UP, DOWN, HORIZONTAL])) == [1.0, 0.0, 0.0]

    def test_cosine_dome(self):
        model = lighting.CosineDome()
        values = model.intensity([UP, DOWN, _elev(30.0)])
        assert values[0] == pytest.approx(1.0)
        assert values[1] == 0.0
        assert values[2] == pytest.approx(0.5)

    def test_ring_light_annulus(self):
        model = lighting.RingLight(30.0, 60.0)
        values = model.intensity(
            [_elev(45.0), _elev(20.0), _elev(75.0), UP, DOWN])
        assert list(values) == [1.0, 0.0, 0.0, 0.0, 0.0]

    def test_ring_light_validates_bounds(self):
        with pytest.raises(ValueError):
            lighting.RingLight(60.0, 30.0)

    def test_head_shadow_composition(self):
        model = lighting.HeadShadow(lighting.UniformHemisphere(),
                                    half_angle_deg=15.0)
        values = model.intensity([UP, _elev(80.0), _elev(45.0), DOWN])
        # 80 deg elevation = 10 deg off axis: inside the 15 deg cone.
        assert list(values) == [0.0, 0.0, 1.0, 0.0]
        assert list(model.in_cone([UP, _elev(45.0)])) == [True, False]

    def test_describe_is_self_documenting(self):
        model = lighting.HeadShadow(lighting.RingLight(20.0, 70.0), 10.0)
        text = model.describe()
        assert "ring light" in text and "head shadow" in text
        assert "20" in text and "70" in text and "10" in text


class TestOccluderProtocol:
    def test_null_occluder_blocks_nothing(self):
        occ = lighting.NullOccluder()
        assert not np.any(occ.blocked(np.zeros((5, 3)), np.eye(3)[
            np.zeros(5, dtype=int)], np.inf))

    def test_occluder_zeroes_blocked_directions(self):
        class BlockEverything(lighting.Occluder):
            def blocked(self, origins, directions, tmax):
                return np.ones(len(np.atleast_2d(directions)), dtype=bool)

        model = lighting.UniformHemisphere(occluder=BlockEverything())
        assert list(model.intensity([UP, _elev(45.0)])) == [0.0, 0.0]

    def test_frozen_contract_signature(self):
        """The Phase 6 contract: blocked(origins, directions, tmax)."""
        import inspect
        params = list(inspect.signature(
            lighting.Occluder.blocked).parameters)
        assert params == ["self", "origins", "directions", "tmax"]
