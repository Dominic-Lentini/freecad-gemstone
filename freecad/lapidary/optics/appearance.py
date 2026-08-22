# SPDX-License-Identifier: LGPL-2.1-or-later
"""Cosmetic viewport appearance for the Gem (DESIGN_OPTICS.md section 6).

Applies a material preset's nominal ``tint``/``transparency`` to the Gem
pipeline's ViewObjects so a sapphire reads blue in the tree and 3D view.

**Presentation only — this is not optics.** Coin3D rasterizes, it does not
refract: the viewport look is identical for a brilliant design and a fully
windowed one and carries no optical information. Nothing here may feed the
tracer or any metric, and nothing in the tracer may read the ViewObject.
The tint is re-applied only when the user picks a preset; per-Gem manual
overrides of the ViewObject colors are deliberately left alone otherwise.

Importable headless: every entry point no-ops without a GUI.
"""

import FreeCAD

from freecad.lapidary.faceting import gem_feature

__all__ = ["apply_material_appearance"]


def apply_material_appearance(gem, material):
    """Set the pipeline ViewObjects' ShapeColor/Transparency from a
    :class:`~freecad.lapidary.optics.materials.Material`'s cosmetic
    fields. No-op headless. Returns True when anything was applied.

    All pipeline features are tinted (not just the tip) so the look
    survives tier reordering and tip changes.
    """
    if not FreeCAD.GuiUp or gem is None or material is None:
        return False
    applied = False
    for feature in gem_feature.pipeline_features(gem):
        vobj = getattr(feature, "ViewObject", None)
        if vobj is None:
            continue
        try:
            vobj.ShapeColor = tuple(float(c) for c in material.tint)
            vobj.Transparency = int(material.transparency)
            applied = True
        except Exception as err:      # a themed VP may lack the property
            FreeCAD.Console.PrintWarning(
                "Lapidary: could not tint %s: %s\n" % (feature.Label, err))
    return applied
