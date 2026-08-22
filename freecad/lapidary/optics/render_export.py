# SPDX-License-Identifier: LGPL-2.1-or-later
"""External Render-workbench material export (DESIGN_OPTICS.md §6.1,
Phase 4c).

Writes a FreeCAD Material card (.FCMat, INI format) for a gem material,
derived from the same constants the tracer uses, so a Render-workbench
project (FreeCAD/FreeCAD-render, the supported successor of the old
Raytracing workbench) picks up correct glass parameters instead of
hand-guessed ones.

Card format (per FreeCAD-render docs/materials_advanced.md): a
``[Rendering]`` section with the generic ``Render.Type = Glass`` /
``Render.Glass.IOR`` / ``Render.Glass.Color`` keys, plus renderer
passthrough lines ``Render.<renderer>.NNNN`` executed in numeric order
with ``%NAME%`` instantiated at render time.

**UNIT TRAP (verified against LuxCore's documentation, do not "fix"):**
LuxCore models glass dispersion with a two-term Cauchy equation and its
``cauchyb`` input expects the **Cauchy-B coefficient in um^2**, NOT the
gemological (B–G) dispersion number. LuxCore's own docs give diamond as
B = 0.0121 and explicitly call 0.044 the "often quoted value" — 0.044 is
the gemological interval from our §6, a different quantity entirely;
feeding it to LuxCore roughly triples the rendered dispersion. This
exporter therefore emits ``Material.cauchy_b_um2()`` (the B of the same
fit the tracer refracts with, converted nm^2 -> um^2). Only LuxCore gets
a dispersion passthrough: per-engine conventions must be verified before
supporting another renderer's dispersion input (§6.1) — Cycles,
Appleseed and POV-Ray receive only the generic glass keys here.

Scope guard (§6.1, binding): this is a metadata bridge only. No renderer
is bundled, no rendered image is a Lapidary output, and nothing in the
validation suite treats renderer output as evidence about a design's
optics.

Headless module: pure string building, no FreeCAD imports; the GUI
command wrapper lives in optics/commands.py.
"""

from freecad.lapidary.optics import materials as _materials

__all__ = ["material_card", "default_card_name"]


def default_card_name(material):
    """A filesystem-friendly card name for a material."""
    keep = [c if c.isalnum() else "_" for c in material.name]
    return "Lapidary_" + "".join(keep).strip("_")


def material_card(material):
    """The .FCMat card text for a Material (see module docstring)."""
    n_d = material.n_d
    cauchy_b = material.cauchy_b_um2()
    tint = tuple(round(float(c), 4) for c in material.tint)
    note = (" %s." % material.birefringent_note.capitalize()
            if material.birefringent_note else "")
    lines = [
        "; %s — Lapidary optics material card (Phase 4c)" % material.name,
        "; Generated from the same constants the Lapidary tracer uses:",
        ";   n_d = %.4g (589.3 nm), gemological (B-G) dispersion = %.4g."
        % (n_d, material.dispersion),
        "; LuxCore's 'cauchyb' below is the Cauchy-B coefficient in um^2",
        "; (%.6g), NOT the gemological dispersion figure %.4g — LuxCore"
        % (cauchy_b, material.dispersion),
        "; documents diamond as B = 0.0121 and calls 0.044 the 'often",
        "; quoted value'; the two differ by roughly 3x. Do not swap them.",
        "; The transmission color is the cosmetic Lapidary viewport tint.",
        "",
        "[General]",
        "Name = %s" % default_card_name(material),
        "Description = %s gem material exported by the Lapidary "
        "workbench.%s Optical constants match the Lapidary optics "
        "tracer; renders are artistic output, not optical analysis."
        % (material.name, note),
        "",
        "[Rendering]",
        "Render.Type = Glass",
        "Render.Glass.IOR = %.6g" % n_d,
        "Render.Glass.Color = (%.4g, %.4g, %.4g)" % tint,
        "Render.Luxcore.0001 = scene.materials.%NAME%.type = glass",
        "Render.Luxcore.0002 = scene.materials.%%NAME%%.kt = "
        "%.4g %.4g %.4g" % tint,
        "Render.Luxcore.0003 = scene.materials.%%NAME%%.interiorior = "
        "%.6g" % n_d,
        # Cauchy-B in um^2 — see the unit trap in the module docstring.
        "Render.Luxcore.0004 = scene.materials.%%NAME%%.cauchyb = %.6g"
        % cauchy_b,
        "",
    ]
    return "\n".join(lines)


def write_material_card(material, path):
    """Write the card to ``path`` and return the text written."""
    text = material_card(material)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)
    return text


# Re-exported for the command's default choice.
DEFAULT_MATERIAL = _materials.PRESETS["Quartz"]
