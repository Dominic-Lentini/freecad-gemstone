# SPDX-License-Identifier: LGPL-2.1-or-later
"""GemCad-style 2D faceting diagrams (DESIGN.md section 8).

Layers, outermost first:

* :func:`gem_diagram_svg` — the one call the GUI needs: Gem in, SVG string out.
* :mod:`~freecad.lapidary.faceting.diagram.projection` — reads the finished
  B-Rep and builds the plain-data :class:`~...diagram.model.Diagram`. The only
  layer that imports FreeCAD.
* :mod:`~freecad.lapidary.faceting.diagram.stats` and
  :mod:`~freecad.lapidary.faceting.diagram.svg` — pure Python, no FreeCAD and
  no Qt, so the whole rendering half runs under plain pytest.

``DIAGRAM_NOTES.md`` in this package records which presentation conventions
were verified against real GemCad printouts, and how.
"""

from freecad.lapidary.faceting.diagram.model import Diagram, LabelStyle
from freecad.lapidary.faceting.diagram.svg import (
    A4_PORTRAIT, LETTER_PORTRAIT, PageStyle, page_size_mm, render_svg)

__all__ = ["Diagram", "LabelStyle", "PageStyle", "A4_PORTRAIT",
           "LETTER_PORTRAIT", "render_svg", "page_size_mm", "build_diagram",
           "gem_diagram_svg"]


def build_diagram(gem, include_elevation=True,
                  label_style=LabelStyle.NAME):
    """Build the diagram model for ``gem`` (None if it has no solid yet).

    Imported lazily so that ``import freecad.lapidary.faceting.diagram`` stays
    usable without FreeCAD — only this function needs it.
    """
    from freecad.lapidary.faceting.diagram.projection import (
        build_diagram as _build)
    return _build(gem, include_elevation=include_elevation,
                  label_style=label_style)


def gem_diagram_svg(gem, include_elevation=True,
                    label_style=LabelStyle.NAME, style=None):
    """The printable faceting diagram of ``gem`` as an SVG string, or None
    when the gem has no finished solid."""
    diagram = build_diagram(gem, include_elevation=include_elevation,
                            label_style=label_style)
    if diagram is None:
        return None
    return render_svg(diagram, style=style)
