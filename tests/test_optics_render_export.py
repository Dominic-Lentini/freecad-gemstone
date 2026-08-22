# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render-material export tests (DESIGN_OPTICS.md section 6.1, Phase 4c).

The critical assertion, demanded by the phase prompt: the exported card's
LuxCore ``cauchyb`` value is the Cauchy-B coefficient (um^2) of the same
fit the tracer refracts with — NOT the gemological B–G dispersion figure,
which is roughly 3x larger for diamond. No FreeCAD.
"""

import re

import pytest

from freecad.lapidary.optics import materials, render_export


def _cauchyb_from_card(card):
    match = re.search(
        r"Render\.Luxcore\.0004 = scene\.materials\.%NAME%\.cauchyb = "
        r"([0-9.eE+-]+)", card)
    assert match, "no LuxCore cauchyb passthrough line in the card"
    return float(match.group(1))


class TestCauchyBUnitTrap:
    def test_cauchy_b_is_the_fit_coefficient_in_um2(self):
        for name, material in materials.PRESETS.items():
            _a, b_nm2 = material.cauchy_coefficients()
            assert material.cauchy_b_um2() == pytest.approx(
                b_nm2 / 1.0e6), name

    def test_diamond_card_does_not_carry_the_gemological_figure(self):
        diamond = materials.PRESETS["Diamond"]
        card = render_export.material_card(diamond)
        cauchyb = _cauchyb_from_card(card)
        # The fit's B for diamond lands near LuxCore's own 0.0121 (ours
        # is 0.0135 from the B-G anchoring) — same order of magnitude...
        assert 0.008 < cauchyb < 0.02
        # ...and emphatically NOT the gemological 0.044.
        assert cauchyb != pytest.approx(diamond.dispersion, rel=0.5)
        assert diamond.dispersion / cauchyb > 2.5

    @pytest.mark.parametrize("name", list(materials.PRESETS))
    def test_card_cauchyb_matches_the_material(self, name):
        material = materials.PRESETS[name]
        card = render_export.material_card(material)
        assert _cauchyb_from_card(card) == pytest.approx(
            material.cauchy_b_um2(), rel=1e-4)


class TestCardContent:
    def test_glass_declaration(self):
        quartz = materials.PRESETS["Quartz"]
        card = render_export.material_card(quartz)
        assert "[Rendering]" in card
        assert "Render.Type = Glass" in card
        assert "Render.Glass.IOR = %.6g" % quartz.n_d in card
        assert ("scene.materials.%NAME%.interiorior = "
                + "%.6g" % quartz.n_d) in card
        assert "scene.materials.%NAME%.type = glass" in card

    def test_scope_guard_language(self):
        card = render_export.material_card(materials.PRESETS["Quartz"])
        assert "not optical analysis" in card
        assert "Do not swap them" in card

    def test_card_name_is_filesystem_friendly(self):
        assert render_export.default_card_name(
            materials.PRESETS["Garnet (almandine)"]) == \
            "Lapidary_Garnet__almandine"

    def test_write_material_card(self, tmp_path):
        path = tmp_path / "quartz.FCMat"
        text = render_export.write_material_card(
            materials.PRESETS["Quartz"], str(path))
        assert path.read_text(encoding="utf-8") == text
