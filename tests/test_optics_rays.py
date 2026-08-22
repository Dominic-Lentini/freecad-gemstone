# SPDX-License-Identifier: LGPL-2.1-or-later
"""Single-ray branch-tree tests (DESIGN_OPTICS.md section 8, Phase 4b).

The golden fixture is the right-angle prism whose full path is derived by
hand in test_optics_tracer.py: down through the top, TIR at the
hypotenuse, out the leg at normal incidence. No FreeCAD needed.
"""

import numpy as np
import pytest

import optics_fixtures as fx
from freecad.lapidary.optics import rays


class TestPrismTree:
    def setup_method(self):
        self.segments = rays.ray_tree(
            fx.prism_polytope(), 1.6, (0.5, 0.0, 1.0),
            min_energy=1e-3)

    def test_segment_kinds_in_order(self):
        kinds = [s.kind for s in self.segments[:4]]
        # Approach, first-surface reflection, then the leg to the
        # hypotenuse (whose TIR spawns no escape), then inside again.
        assert kinds == [rays.KIND_INCIDENT, rays.KIND_ESCAPE,
                         rays.KIND_INTERNAL, rays.KIND_INTERNAL]

    def test_hand_derived_geometry(self):
        internal = [s for s in self.segments
                    if s.kind == rays.KIND_INTERNAL]
        # First leg: straight down from (0.5, 0, 1) to the hypotenuse at
        # (0.5, 0, -0.5); second leg: along +X to the leg face at x = 1.
        assert internal[0].start == pytest.approx((0.5, 0.0, 1.0), abs=1e-5)
        assert internal[0].end == pytest.approx((0.5, 0.0, -0.5), abs=1e-5)
        assert internal[1].end == pytest.approx((1.0, 0.0, -0.5), abs=1e-5)
        # First escape after the TIR leg exits along +X.
        escapes = [s for s in self.segments if s.kind == rays.KIND_ESCAPE]
        first_exit = escapes[1]           # escapes[0] is the entry glare
        direction = np.array(first_exit.end) - np.array(first_exit.start)
        direction /= np.linalg.norm(direction)
        assert direction == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)

    def test_energy_accounting(self):
        # Escaping branches plus the pruned continuation account for the
        # whole primary ray.
        escapes = sum(s.energy for s in self.segments
                      if s.kind == rays.KIND_ESCAPE)
        internal = [s for s in self.segments
                    if s.kind == rays.KIND_INTERNAL]
        n = 1.6
        R0 = ((n - 1.0) / (n + 1.0)) ** 2
        # The last internal leg carries the not-yet-escaped remainder;
        # everything after it was pruned below min_energy.
        assert escapes + internal[-1].energy * R0 <= 1.0 + 1e-9
        assert escapes > 0.9              # the prism leaks nearly all of it
        # Energies only ever decrease along the chain.
        energies = [s.energy for s in internal]
        assert energies == sorted(energies, reverse=True)

    def test_miss_returns_empty(self):
        assert rays.ray_tree(fx.prism_polytope(), 1.6, (9.0, 0.0, 1.0)) == []

    def test_srb_tree_is_bounded(self):
        segments = rays.ray_tree(fx.srb_polytope(), 1.54, (1.0, 0.5, 2.0))
        assert segments
        assert len(segments) < 2 * 32 + 2
        # Every segment stays within a sane bound of the stone.
        r = fx.srb_polytope().bounding_radius()
        for s in segments:
            assert np.linalg.norm(s.end) <= 4.0 * r
