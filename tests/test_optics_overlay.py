# SPDX-License-Identifier: LGPL-2.1-or-later
"""Diagram optics-overlay tests (DESIGN_OPTICS.md section 8, Phase 4b).

The overlay is an optional fill layer inside the existing diagram
renderer: with ``tier_tint=None`` the output must be byte-identical to
the base diagram, and toggling it on/off must leave the base unchanged.
Requires FreeCAD (the diagram builds from real B-Rep).
"""

import pytest

# The whole module (share_color included) sits behind the FreeCAD skip:
# optics.overlay imports the faceting feature modules, which import
# FreeCAD at module level — collecting this file on plain CPython must
# skip, not error.
FreeCAD = pytest.importorskip("FreeCAD")

from freecad.lapidary.faceting import diagram as diagram_pkg  # noqa: E402
from freecad.lapidary.optics import overlay, study_feature  # noqa: E402
from freecad.lapidary.optics.overlay import share_color  # noqa: E402
from test_pipeline import build_srb  # noqa: E402


@pytest.fixture(scope="module")
def srb_doc():
    doc = FreeCAD.newDocument("optics_overlay")
    try:
        yield build_srb(doc)
    finally:
        FreeCAD.closeDocument(doc.Name)


class TestShareColor:
    def test_scale_endpoints(self):
        assert share_color(0.0, 50.0) == "#ffffff"
        assert share_color(50.0, 50.0) == "#f7c42c"
        assert share_color(60.0, 50.0) == "#f7c42c"   # clamped
        assert share_color(10.0, 0.0) == "#ffffff"    # degenerate max


class TestOverlayLayer:
    def test_none_reproduces_the_base_diagram_exactly(self, srb_doc):
        gem, _stock, _tiers = srb_doc
        diagram = diagram_pkg.build_diagram(gem)
        base = diagram_pkg.render_svg(diagram)
        assert diagram_pkg.render_svg(diagram, tier_tint=None) == base
        assert diagram_pkg.render_svg(diagram, tier_tint={}) == base

    def test_tint_layer_only_changes_fills(self, srb_doc):
        gem, _stock, tiers = srb_doc
        diagram = diagram_pkg.build_diagram(gem)
        base = diagram_pkg.render_svg(diagram)
        tint = {tiers["P1 breaks"].Name: "#f7c42c"}
        tinted = diagram_pkg.render_svg(diagram, tier_tint=tint)
        assert tinted != base
        assert '#f7c42c' in tinted
        # Nothing but fill attributes may change.
        assert base.replace('fill="#fff"', "") == \
            tinted.replace('fill="#fff"', "").replace('fill="#f7c42c"', "")
        # Toggling back off restores the base bytes.
        assert diagram_pkg.render_svg(diagram, tier_tint=None) == base


class TestStudyTint:
    def test_fresh_study_yields_a_full_tint_map(self, srb_doc):
        gem, _stock, tiers = srb_doc
        study = study_feature.make_study(gem)
        study.GridResolution = 24
        study.TiltSteps = 0
        gem.Document.recompute()
        study_feature.run_study(study)
        tint = overlay.tier_tint_for_gem(gem)
        assert set(tint) == {t.Name for t in tiers.values()}
        assert all(color.startswith("#") and len(color) == 7
                   for color in tint.values())
        # The scale is normalized: the strongest tier reads fully gold.
        assert "#f7c42c" in tint.values()
        # Stale study -> no overlay.
        tiers["Table"].Distance = tiers["Table"].Distance.Value - 0.05
        gem.Document.recompute()
        assert overlay.tier_tint_for_gem(gem) == {}
        gem.Document.removeObject(study.Name)
