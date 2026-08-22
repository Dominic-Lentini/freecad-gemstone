# SPDX-License-Identifier: LGPL-2.1-or-later
"""Icon-resource checks (DESIGN.md section 9, Phase 3 "polish (icons, ...)").

Pure file and XML checks — no FreeCAD, no Qt. The interesting one is
:meth:`TestIcons.test_every_icon_is_distinct`: through Phases 0-2 every
command shipped the *same* placeholder gem drawing, so a regression here would
be invisible in a screenshot-free test suite but obvious to a user staring at
eight identical toolbar buttons.
"""

import os
import xml.etree.ElementTree as ElementTree

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, "freecad", "lapidary", "resources", "icons")

SVG_NS = "http://www.w3.org/2000/svg"

#: One per command registered by init_gui, plus the workbench itself and the
#: two ViewProvider icons.
EXPECTED = [
    "Lapidary_Workbench",
    "Lapidary_NewGem",
    "Lapidary_FacetTier",
    "Lapidary_ImportASC",
    "Lapidary_ExportASC",
    "Lapidary_Diagram",
    "Lapidary_CuttingSheet",
    "Lapidary_Report",
    "Lapidary_Stock",
    "Lapidary_TierWarning",
    "Lapidary_DopTransfer",
    # Optics (Phases 4a/4b): commands plus the stale-study tree icon.
    "Lapidary_OpticsStudy",
    "Lapidary_OpticsStudyStale",
    "Lapidary_RunOptics",
    "Lapidary_OpticsResults",
    "Lapidary_TraceRay",
    "Lapidary_ExportRenderMaterial",
]


def _path(name):
    return os.path.join(ICON_DIR, name + ".svg")


class TestIcons:
    @pytest.mark.parametrize("name", EXPECTED)
    def test_icon_exists_and_is_valid_svg(self, name):
        path = _path(name)
        assert os.path.isfile(path), path
        root = ElementTree.parse(path).getroot()
        assert root.tag == "{%s}svg" % SVG_NS
        assert root.get("viewBox") == "0 0 64 64"
        assert root.get("width") == "64" and root.get("height") == "64"

    @pytest.mark.parametrize("name", EXPECTED)
    def test_icon_carries_a_licence_header(self, name):
        with open(_path(name), encoding="utf-8") as stream:
            assert "SPDX-License-Identifier: LGPL-2.1-or-later" in stream.read()

    def test_every_icon_is_distinct(self):
        """No two commands may share a drawing — the Phase 0 placeholders all
        did, which is exactly what the Phase 3 polish pass replaced."""
        drawings = {}
        for name in EXPECTED:
            with open(_path(name), encoding="utf-8") as stream:
                # Compare the markup with comments and whitespace removed, so
                # a copy-paste with only the comment changed still trips this.
                body = ElementTree.tostring(
                    ElementTree.parse(stream).getroot(), encoding="unicode")
                body = "".join(body.split())
            assert body not in drawings, "%s duplicates %s" % (
                name, drawings[body])
            drawings[body] = name

    def test_no_placeholder_icons_remain(self):
        for name in EXPECTED:
            with open(_path(name), encoding="utf-8") as stream:
                assert "placeholder" not in stream.read().lower(), name

    def test_icons_are_self_contained(self):
        """Toolbar icons must not reach for external images or fonts."""
        for name in EXPECTED:
            with open(_path(name), encoding="utf-8") as stream:
                text = stream.read()
            assert "<image" not in text, name
            assert "xlink:href" not in text, name
            assert "http://" not in text.replace(SVG_NS, ""), name
