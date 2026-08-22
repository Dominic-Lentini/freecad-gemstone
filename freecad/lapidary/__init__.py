# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lapidary: a FreeCAD workbench for designing faceted gemstones.

This package must stay importable without FreeCAD (plain CPython) so the pure
math/IO layers are testable headless; anything that needs FreeCAD lives behind
``init_gui.py`` or guarded imports.
"""

from freecad.lapidary.version import __version__

__all__ = ["__version__"]
