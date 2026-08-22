# SPDX-License-Identifier: LGPL-2.1-or-later
"""Multi-wavelength runs and the Lapidary Fire Index
(DESIGN_OPTICS.md section 6, Phase 4c).

**Lapidary Fire Index — definition (binding, restated verbatim-in-spirit
in every report that carries the number):** trace the view grid once per
wavelength sample; for each primary pixel take the *highest-energy exit
branch that travelled inside the stone* at each of the two wavelength
extremes (reddest and most violet samples) and measure the angular
spread, in degrees, between those two exit directions; the index is the
energy-weighted mean of that spread over stone pixels, where a pixel's
weight is the mean of its two branch energies. The first-surface
reflection never enters the stone and is therefore not an eligible
branch (it is achromatic by construction); pixels where either extreme
has no eligible escaping branch are excluded.

This is a Lapidary-defined, settings-dependent comparison metric between
designs traced with the same parameters. It is NOT comparable with fire
figures from DiamCalc, GemRay, or any other tool.

Pure numpy; no FreeCAD imports.
"""

from dataclasses import dataclass

import numpy as np

from freecad.lapidary.optics import materials as _materials
from freecad.lapidary.optics import metrics as _metrics
from freecad.lapidary.optics import tracer as _tracer

__all__ = ["FireResult", "fire_analysis", "wavelength_samples",
           "FIRE_DEFINITION"]

FIRE_DEFINITION = (
    "Lapidary Fire Index: per stone pixel, the angular spread (degrees) "
    "between the highest-energy interior exit branches (the achromatic "
    "first-surface reflection is excluded) at the red and violet "
    "wavelength extremes, averaged over pixels weighted by the mean of "
    "the two branch energies. A Lapidary-defined, settings-dependent "
    "comparison metric between designs; not comparable with fire figures "
    "from any other tool.")


def wavelength_samples(count):
    """The 3- or 5-sample wavelength set (nm) of DESIGN_OPTICS.md §6."""
    if int(count) == 3:
        return _materials.WAVELENGTHS_3
    if int(count) == 5:
        return _materials.WAVELENGTHS_5
    raise ValueError("wavelength sample count must be 3 or 5, got %r"
                     % (count,))


@dataclass
class FireResult:
    """Everything a multi-wavelength run produced."""

    wavelengths_nm: tuple
    #: brightness % per wavelength, parallel to ``wavelengths_nm``.
    brightness_by_wavelength: tuple
    #: the per-wavelength TraceResults, parallel to ``wavelengths_nm``.
    results: tuple
    #: (R, R) angular spread in degrees (0 where undefined).
    spread_deg: np.ndarray = None
    #: (R, R) pixel weights (0 where the spread is undefined).
    weight: np.ndarray = None
    fire_index: float = 0.0

    @property
    def violet_result(self):
        return self.results[int(np.argmin(self.wavelengths_nm))]

    @property
    def red_result(self):
        return self.results[int(np.argmax(self.wavelengths_nm))]


def fire_analysis(poly, material, lighting=None, wavelengths=None,
                  progress=None, **trace_kwargs):
    """Run the tracer per wavelength and compute the Fire Index.

    ``material`` supplies ``n(lambda)`` via its Cauchy fit;
    ``wavelengths`` defaults to the 3-sample set. Remaining keyword
    arguments go straight to :func:`tracer.trace` (resolution, max_depth,
    min_energy, absorption_per_mm, tilt, ...), so the fire run shares the
    study's exact settings. ``progress(fraction)`` spans all samples.
    """
    if wavelengths is None:
        wavelengths = _materials.WAVELENGTHS_3
    wavelengths = tuple(float(w) for w in wavelengths)
    results = []
    brightness = []
    n_samples = len(wavelengths)
    for i, wavelength in enumerate(wavelengths):
        sub = None
        if progress is not None:
            sub = (lambda base: lambda frac:
                   progress((base + frac) / n_samples))(i)
        result = _tracer.trace(poly, material.n(wavelength),
                               lighting=lighting, progress=sub,
                               **trace_kwargs)
        results.append(result)
        brightness.append(_metrics.brightness_pct(result))

    violet = results[int(np.argmin(wavelengths))]
    red = results[int(np.argmax(wavelengths))]
    valid = (violet.hit_mask & red.hit_mask
             & (violet.best_exit_energy > 0.0)
             & (red.best_exit_energy > 0.0))
    cos = np.clip(np.sum(violet.best_exit_dir * red.best_exit_dir,
                         axis=2), -1.0, 1.0)
    spread = np.where(valid, np.degrees(np.arccos(cos)), 0.0)
    weight = np.where(
        valid, 0.5 * (violet.best_exit_energy + red.best_exit_energy), 0.0)
    total = float(np.sum(weight))
    index = float(np.sum(spread * weight) / total) if total > 0.0 else 0.0
    return FireResult(
        wavelengths_nm=wavelengths,
        brightness_by_wavelength=tuple(brightness),
        results=tuple(results),
        spread_deg=spread,
        weight=weight,
        fire_index=index,
    )
