# SPDX-License-Identifier: LGPL-2.1-or-later
"""GemCad .ASC interchange (DESIGN.md section 7).

``parser`` and ``writer`` are pure Python (no FreeCAD, no GUI) and testable
with plain pytest; ``document`` maps parsed designs onto the Gem/FacetTier
pipeline and back. Format ground truth is documented in FORMAT_NOTES.md.
"""
