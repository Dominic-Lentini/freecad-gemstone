# SPDX-License-Identifier: LGPL-2.1-or-later
"""Gem materials: refractive index, dispersion, Cauchy expansion
(DESIGN_OPTICS.md section 6).

A material is a name + refractive index ``n_d`` (sodium D line, 589.3 nm) +
dispersion, expanded to ``n(lambda)`` via a two-term Cauchy fit
``n = A + B / lambda^2``.

**Dispersion convention** (DESIGN_OPTICS.md section 6, as corrected
2026-08-15): values are stored the way gemological references publish
them — the Fraunhofer **B–G interval**, ``n(430.8 nm) - n(686.7 nm)``
(red B line to violet G line). Every standard table (diamond 0.044,
zircon 0.039, ...) uses this interval; the F–C interval (486.1/656.3 nm)
gives roughly half the number for the same stone and is *not*
interchangeable. The F/D/C *wavelength samples* used for tracing are a
separate choice from the B–G pair that defines the stored constant. The
Cauchy fit below anchors ``n_d`` exactly and reproduces the stored B–G
dispersion exactly; the F and C line indices follow from the fit.

The fit: with ``S = 1/430.8^2 - 1/686.7^2`` (nm^-2),

    B = dispersion / S
    A = n_d - B / 589.3^2

so ``n(589.3) = n_d`` and ``n(430.8) - n(686.7) = dispersion`` hold exactly
(the two-term model is then *evaluated* at the three standard lines C, D, F —
the "fit through the three standard lines" of section 6 in the only way a
two-parameter model can pass through them: D exactly, F and C by the model).

Pure Python + numpy; no FreeCAD imports.
"""

from dataclasses import dataclass

__all__ = [
    "Material",
    "PRESETS",
    "preset_names",
    "WAVELENGTH_D",
    "WAVELENGTHS_1",
    "WAVELENGTHS_3",
    "WAVELENGTHS_5",
]

#: Fraunhofer wavelengths (nm) used across the module.
WAVELENGTH_B = 686.7   # red (H-alpha... B is O2/Fraunhofer B; red end)
WAVELENGTH_G = 430.8   # violet
WAVELENGTH_C = 656.3   # red hydrogen line
WAVELENGTH_D = 589.3   # sodium doublet (gemology's n_d reference)
WAVELENGTH_F = 486.1   # blue hydrogen line

#: Wavelength sample sets (DESIGN_OPTICS.md section 6): brightness uses the
#: D line only; fire (Phase 4c) uses 3 or 5 samples.
WAVELENGTHS_1 = (WAVELENGTH_D,)
WAVELENGTHS_3 = (WAVELENGTH_F, WAVELENGTH_D, WAVELENGTH_C)
WAVELENGTHS_5 = (435.8, WAVELENGTH_F, WAVELENGTH_D, WAVELENGTH_C, 706.5)

#: 1/430.8^2 - 1/686.7^2 in nm^-2: the B-G Cauchy span.
_BG_SPAN = 1.0 / WAVELENGTH_G ** 2 - 1.0 / WAVELENGTH_B ** 2


@dataclass(frozen=True)
class Material:
    """An isotropic gem material.

    ``n_d``: refractive index at the sodium D line (589.3 nm).
    ``dispersion``: gemological (Fraunhofer B–G) dispersion,
    ``n(430.8) - n(686.7)``; see the module docstring.
    ``birefringent_note``: non-empty when ``n_d`` is the mean index of a
    birefringent species — the report output must say so
    (DESIGN_OPTICS.md section 6: isotropic only, use the mean index).

    ``tint`` (RGB, 0–1) and ``transparency`` (0–100) are **cosmetic
    viewport appearance only** (DESIGN_OPTICS.md section 6): nominal
    variety colors applied to the Gem's ViewObject so a sapphire reads
    blue in the 3D view. Coin3D rasterizes, it does not refract — the
    viewport look carries no optical information, so these fields must
    never reach the tracer or any metric, and are user-overridable per
    Gem (edit the ViewObject; they are only re-applied on preset change).
    """

    name: str
    n_d: float
    dispersion: float
    birefringent_note: str = ""
    tint: tuple = (0.92, 0.92, 0.95)     # cosmetic only, see docstring
    transparency: int = 70               # cosmetic only, see docstring

    def cauchy_coefficients(self):
        """(A, B) of ``n = A + B / lambda_nm^2``; see module docstring."""
        B = self.dispersion / _BG_SPAN
        A = self.n_d - B / WAVELENGTH_D ** 2
        return A, B

    def n(self, wavelength_nm=WAVELENGTH_D):
        """Refractive index at a wavelength (nm); scalar in, scalar out."""
        A, B = self.cauchy_coefficients()
        return A + B / float(wavelength_nm) ** 2

    def cauchy_b_um2(self):
        """The Cauchy-B coefficient in micrometres squared.

        This — NOT the gemological B–G dispersion number — is what
        LuxCore's glass ``cauchyb`` input expects (DESIGN_OPTICS.md
        section 6.1: LuxCore documents diamond as B = 0.0121 and calls
        0.044 merely the "often quoted value"; feeding it the gemological
        figure roughly triples the rendered dispersion). Our fit stores B
        in nm^2, so convert: 1 um^2 = 1e6 nm^2.
        """
        _A, B = self.cauchy_coefficients()
        return B / 1.0e6

    def describe(self):
        note = (" (%s)" % self.birefringent_note) if self.birefringent_note \
            else ""
        return ("%s: n_d = %.3f, dispersion (B–G) = %.3f%s"
                % (self.name, self.n_d, self.dispersion, note))


def _mean(lo, hi):
    return round((lo + hi) / 2.0, 3)


#: Preset library. Sources, per DESIGN_OPTICS.md section 6 (values looked up
#: 2026-08-15, not written from memory):
#:
#: [IGS]  International Gem Society, "Table of Refractive Indices and Double
#:        Refraction of Selected Gems",
#:        https://www.gemsociety.org/article/table-refractive-index-double-refraction-gems/
#:        — n_d ranges. Where a species has a range (birefringence and/or
#:        composition), the preset uses the midpoint of the cited range,
#:        rounded to 3 decimals; per-stone values can always be overridden
#:        on the study.
#: [GP]   The Gemology Project, "Dispersion" value table (B–G interval),
#:        http://gemologyproject.com/wiki/index.php?title=Dispersion
#: [GS]   GemSelect, "Gemstone Dispersion Chart" (B–G interval),
#:        https://www.gemselect.com/gem-info/dispersion-chart.php
#:        — agrees with [GP] on every species below; cross-check source.
#: [WP]   Wikipedia, "Cubic zirconia": RI 2.15–2.18, dispersion 0.058–0.066.
#: [BK7]  Schott N-BK7 crown glass via the Sellmeier data reproduced at
#:        https://www.newlightphotonics.com/BK7-properties.html
#:        (B1 1.03961/C1 0.0060007, B2 0.23179/C2 0.020018,
#:        B3 1.01047/C3 103.56, lambda in um): n(589.3) = 1.5167,
#:        n(430.8) - n(686.7) = 0.0138 (evaluated from that equation; see
#:        tests/test_optics_materials.py which re-derives both numbers).
#: Tint colors below are NOMINAL variety colors, cosmetic only (a "citrine
#: yellow" for quartz would be as valid as the pale smoky gray chosen) —
#: they are presentation defaults, not sourced optical data, and carry no
#: optical meaning. See the Material docstring.
PRESETS = {
    # name: n_d [source], dispersion [source]
    "Quartz": Material(
        "Quartz", _mean(1.544, 1.553), 0.013,        # [IGS], [GP][GS]
        birefringent_note="mean of the 1.544–1.553 birefringent range",
        tint=(0.93, 0.91, 0.88), transparency=75),   # pale smoky
    "Beryl": Material(
        "Beryl", _mean(1.562, 1.602), 0.014,         # [IGS], [GP][GS]
        birefringent_note="mean of the 1.562–1.602 birefringent range",
        tint=(0.45, 0.78, 0.60), transparency=65),   # emerald green
    "Corundum": Material(
        "Corundum", _mean(1.762, 1.778), 0.018,      # [IGS], [GP][GS]
        birefringent_note="mean of the 1.762–1.778 birefringent range",
        tint=(0.25, 0.35, 0.80), transparency=60),   # sapphire blue
    "Topaz": Material(
        "Topaz", _mean(1.609, 1.643), 0.014,         # [IGS], [GP][GS]
        birefringent_note="mean of the 1.609–1.643 birefringent range",
        tint=(0.98, 0.82, 0.55), transparency=70),   # imperial gold
    "Tourmaline": Material(
        "Tourmaline", _mean(1.614, 1.666), 0.017,    # [IGS], [GP][GS]
        birefringent_note="mean of the 1.614–1.666 birefringent range",
        tint=(0.35, 0.70, 0.45), transparency=60),   # verdelite green
    "Garnet (almandine)": Material(
        "Garnet (almandine)", _mean(1.770, 1.820), 0.027,    # [IGS], [GP]
        tint=(0.55, 0.12, 0.18), transparency=45),   # deep red
    "Garnet (pyrope)": Material(
        "Garnet (pyrope)", _mean(1.720, 1.756), 0.022,       # [IGS], [GP][GS]
        tint=(0.70, 0.15, 0.15), transparency=50),   # blood red
    "Garnet (spessartine)": Material(
        "Garnet (spessartine)", _mean(1.790, 1.820), 0.027,  # [IGS], [GP][GS]
        tint=(0.95, 0.50, 0.15), transparency=55),   # mandarin orange
    "Garnet (grossular)": Material(
        "Garnet (grossular)", _mean(1.734, 1.759), 0.027,    # [IGS], [GP]
        tint=(0.30, 0.65, 0.35), transparency=60),   # tsavorite green
    "Garnet (andradite)": Material(
        "Garnet (andradite)", _mean(1.880, 1.940), 0.057,    # [IGS], [GP][GS]
        tint=(0.45, 0.75, 0.30), transparency=60),   # demantoid green
    "Spinel": Material(
        "Spinel", _mean(1.712, 1.762), 0.020,        # [IGS], [GP][GS]
        tint=(0.85, 0.25, 0.35), transparency=60),   # red spinel
    "Zircon": Material(
        "Zircon", _mean(1.810, 2.024), 0.039,        # [IGS], [GP][GS]
        birefringent_note="mean of the 1.810–2.024 range (low to high "
                          "zircon; strongly birefringent)",
        tint=(0.60, 0.80, 0.95), transparency=70),   # starlite blue
    "Cubic zirconia": Material(
        "Cubic zirconia", _mean(2.150, 2.180), 0.062,        # [WP] midpoints
        tint=(0.96, 0.96, 0.98), transparency=75),   # colorless
    "Diamond": Material(
        "Diamond", 2.417, 0.044,                     # [IGS] 2.417, [GP][GS]
        tint=(0.97, 0.97, 0.98), transparency=75),   # colorless
    "Glass (crown, BK7)": Material(
        "Glass (crown, BK7)", 1.517, 0.014,          # [BK7], rounded
        tint=(0.90, 0.95, 0.93), transparency=80),   # bottle-glass hint
}


def preset_names():
    """Preset names in a stable presentation order."""
    return list(PRESETS.keys())
