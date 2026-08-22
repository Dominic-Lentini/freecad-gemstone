# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fire / dispersion tests (DESIGN_OPTICS.md section 6, Phase 4c).

Per the phase prompt: fire-index determinism, and a diamond-vs-quartz
fixture pair asserting only the ORDERING of fire indices — never absolute
values, which are Lapidary-defined and settings-dependent. No FreeCAD.
"""

import numpy as np
import pytest

import optics_fixtures as fx
from freecad.lapidary.optics import fire, imaging, materials

RES = 32


def _srb_fire(material, wavelengths=materials.WAVELENGTHS_3):
    return fire.fire_analysis(fx.srb_polytope(), material,
                              wavelengths=wavelengths, resolution=RES)


class TestFireAnalysis:
    def test_structure(self):
        result = _srb_fire(materials.PRESETS["Quartz"])
        assert result.wavelengths_nm == materials.WAVELENGTHS_3
        assert len(result.brightness_by_wavelength) == 3
        assert all(0.0 < b < 100.0
                   for b in result.brightness_by_wavelength)
        assert result.spread_deg.shape == (RES, RES)
        assert result.fire_index > 0.0
        # Weights are zero exactly where the spread is undefined.
        assert np.all((result.weight > 0) | (result.spread_deg == 0.0))
        # Extremes resolve to the right per-wavelength results.
        assert result.violet_result.n_gem > result.red_result.n_gem

    def test_five_sample_option(self):
        result = _srb_fire(materials.PRESETS["Quartz"],
                           wavelengths=materials.WAVELENGTHS_5)
        assert len(result.brightness_by_wavelength) == 5
        assert result.fire_index > 0.0

    def test_determinism(self):
        a = _srb_fire(materials.PRESETS["Quartz"])
        b = _srb_fire(materials.PRESETS["Quartz"])
        assert a.fire_index == b.fire_index
        assert a.spread_deg.tobytes() == b.spread_deg.tobytes()
        assert a.brightness_by_wavelength == b.brightness_by_wavelength

    def test_diamond_vs_quartz_ordering_only(self):
        """Diamond (dispersion 0.044) must out-fire quartz (0.013).
        ORDERING only — never absolute values.

        Fixture choice: a 20-degree wedge, below BOTH critical angles
        (diamond 24.4 deg, quartz 40.5 deg), so the dominant branch for
        both materials is the same single clean pavilion refraction and
        the ordering follows from dn alone: the exit spread of that
        refraction is dn * sin(a) / cos(theta_t), which is ~0.90 deg for
        diamond vs ~0.18 deg for quartz — a 5x margin that grid effects
        cannot flip. (On the SRB cut *for* R.I. 1.54 the energy-weighted
        mean is legitimately dominated by quartz's near-grazing exits —
        see docs/dev-notes.md, Phase 4c; that is a property of the
        design/material mismatch, not of the tracer, so the ordering
        fixture avoids it by construction.)"""
        wedge = fx.wedge_polytope(20.0)
        diamond = fire.fire_analysis(wedge, materials.PRESETS["Diamond"],
                                     resolution=RES)
        quartz = fire.fire_analysis(wedge, materials.PRESETS["Quartz"],
                                    resolution=RES)
        assert diamond.fire_index > quartz.fire_index

    def test_higher_dispersion_same_index_orders_on_the_srb(self):
        """A same-n_d, higher-dispersion material must out-fire its
        low-dispersion twin on the SRB too — isolating dispersion from
        the refractive-index/design interaction that makes the
        diamond-vs-quartz SRB comparison tail-dominated."""
        low = materials.Material("test-low", 1.54, 0.010)
        high = materials.Material("test-high", 1.54, 0.040)
        assert _srb_fire(high).fire_index > _srb_fire(low).fire_index

    def test_wavelength_samples_validation(self):
        assert fire.wavelength_samples(3) == materials.WAVELENGTHS_3
        assert fire.wavelength_samples(5) == materials.WAVELENGTHS_5
        with pytest.raises(ValueError):
            fire.wavelength_samples(2)

    def test_definition_text_carries_the_caveat(self):
        assert "not comparable" in fire.FIRE_DEFINITION
        assert "degrees" in fire.FIRE_DEFINITION


class TestSpreadImage:
    def test_spread_map_renders(self):
        result = _srb_fire(materials.PRESETS["Diamond"])
        img = imaging.spread_image(result)
        assert img.shape == (RES, RES, 4)
        valid = (result.weight > 0)[::-1]
        assert np.all(img[valid, 3] == 255)
        assert np.all(img[~valid, 3] == 0)
        # The strongest-spread pixel reads fully violet.
        assert img[..., 2].max() >= 200
        data = imaging.write_png(img)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data == imaging.write_png(imaging.spread_image(result))
