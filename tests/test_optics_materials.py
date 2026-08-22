# SPDX-License-Identifier: LGPL-2.1-or-later
"""Materials and Cauchy dispersion tests (DESIGN_OPTICS.md section 6).

The anchor-line property is exact by construction and asserted exactly:
n(589.3) = n_d and n(430.8) - n(686.7) = dispersion. The BK7 preset is
re-derived here from the cited Sellmeier equation, so the preset's rounded
constants are pinned to their source rather than to memory.
"""

import math

import pytest

from freecad.lapidary.optics import materials as m


class TestCauchyFit:
    @pytest.mark.parametrize("name", list(m.PRESETS))
    def test_anchor_lines_exact(self, name):
        mat = m.PRESETS[name]
        assert mat.n(m.WAVELENGTH_D) == pytest.approx(mat.n_d, abs=1e-12)
        assert (mat.n(m.WAVELENGTH_G) - mat.n(m.WAVELENGTH_B)
                == pytest.approx(mat.dispersion, abs=1e-12))

    @pytest.mark.parametrize("name", list(m.PRESETS))
    def test_normal_dispersion_shape(self, name):
        """Cauchy with B > 0: index decreases monotonically with
        wavelength, and stays physical across the visible band."""
        mat = m.PRESETS[name]
        samples = [mat.n(w) for w in (400.0, 500.0, 600.0, 700.0)]
        assert samples == sorted(samples, reverse=True)
        assert all(1.0 < n < 4.0 for n in samples)

    def test_f_and_c_lines_bracket_the_d_line(self):
        mat = m.PRESETS["Diamond"]
        assert mat.n(m.WAVELENGTH_F) > mat.n_d > mat.n(m.WAVELENGTH_C)


class TestPresets:
    def test_bk7_matches_its_sellmeier_source(self):
        """Re-derive the [BK7] preset from the cited Sellmeier equation
        (newlightphotonics.com/BK7-properties.html, lambda in um)."""
        def n_bk7(um):
            l2 = um * um
            return math.sqrt(
                1.0 + 1.03961 * l2 / (l2 - 0.0060007)
                + 0.23179 * l2 / (l2 - 0.020018)
                + 1.01047 * l2 / (l2 - 103.56))

        n_d = n_bk7(0.5893)
        bg = n_bk7(0.4308) - n_bk7(0.6867)
        preset = m.PRESETS["Glass (crown, BK7)"]
        assert preset.n_d == pytest.approx(n_d, abs=5e-4)     # 1.5167 -> 1.517
        assert preset.dispersion == pytest.approx(bg, abs=5e-4)  # 0.0138

    def test_diamond_reference_values(self):
        # IGS: n_d 2.417; GemologyProject/GemSelect: dispersion 0.044 (B-G).
        diamond = m.PRESETS["Diamond"]
        assert diamond.n_d == 2.417
        assert diamond.dispersion == 0.044

    def test_birefringent_presets_carry_the_mean_index_note(self):
        for name in ("Quartz", "Beryl", "Corundum", "Topaz", "Tourmaline",
                     "Zircon"):
            mat = m.PRESETS[name]
            assert mat.birefringent_note, name
            assert mat.birefringent_note in mat.describe()

    def test_wavelength_sample_sets(self):
        assert m.WAVELENGTHS_1 == (589.3,)
        assert m.WAVELENGTHS_3 == (486.1, 589.3, 656.3)
        assert len(m.WAVELENGTHS_5) == 5
        assert set(m.WAVELENGTHS_3) < set(m.WAVELENGTHS_5)

    @pytest.mark.parametrize("name", list(m.PRESETS))
    def test_cosmetic_appearance_fields_are_valid(self, name):
        """Tint/transparency are presentation-only viewport defaults
        (DESIGN_OPTICS.md section 6) — well-formed, never consumed by the
        tracer (the tracer takes only a refractive index)."""
        mat = m.PRESETS[name]
        assert len(mat.tint) == 3
        assert all(0.0 <= c <= 1.0 for c in mat.tint)
        assert 0 <= mat.transparency <= 100

    def test_preset_names_cover_the_design_list(self):
        # DESIGN_OPTICS.md section 6's requested species set.
        names = " ".join(m.preset_names()).lower()
        for species in ("quartz", "beryl", "corundum", "topaz", "tourmaline",
                        "garnet", "spinel", "zircon", "zirconia", "diamond",
                        "glass"):
            assert species in names, species
