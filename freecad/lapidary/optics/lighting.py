# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lighting models and the Occluder protocol (DESIGN_OPTICS.md section 5).

Every model maps escape directions to an intensity ``L(directions) -> [0, 1]``
and accepts an :class:`Occluder`. All directions are in the *view frame*: +Z
is "up", toward the observer's hemisphere; the tracer rotates stone-frame
exit directions into this frame before evaluating (tilt rotates the grid and
the lighting together, never the geometry).

Mathematical definitions (restated in report output per DESIGN_OPTICS.md
section 10 — every metric must be interpretable on its own terms):

- ``UniformHemisphere``: L = 1 for dir_z > 0, else 0. An isotropic diffuse
  dome; the default for the headline light-return number. Defined here, not
  borrowed from any tool or standard.
- ``CosineDome``: L = max(dir_z, 0). Dome radiance weighted by elevation.
- ``RingLight(lo_deg, hi_deg)``: L = 1 when the direction's elevation above
  the horizon lies in [lo_deg, hi_deg], else 0.
- ``HeadShadow(base, half_angle_deg)``: L = 0 inside the cone of the given
  half-angle about the view axis (+Z), else the wrapped model's L.
  Composable with any of the above; models the observer blocking light.

Occluder protocol (FROZEN CONTRACT — see class docstring).
"""

import math

import numpy as np

__all__ = [
    "Occluder",
    "NullOccluder",
    "LightingModel",
    "UniformHemisphere",
    "CosineDome",
    "RingLight",
    "HeadShadow",
]


class Occluder:
    """Anything in the scene that may *block* rays but never refracts.

    FROZEN CONTRACT (DESIGN_OPTICS.md section 5): Phase 6 stone-setting
    occluders are coded against exactly this signature. Changing the name,
    argument order, or semantics of :meth:`blocked` is a breaking change and
    must be versioned, not edited.

    ``blocked(origins, directions, tmax) -> bool array``

    - ``origins``: (N, 3) ray start points;
    - ``directions``: (N, 3) unit ray directions;

    Frame convention (part of the contract): both origins and directions
    are in the *view frame* (+Z toward the observer) — the frame lighting
    models are evaluated in. The tracer rotates stone-frame escape points
    and directions into the view frame before any occluder query; a Phase 6
    mesh occluder therefore receives the stone->view rotation when it is
    built, not per call.

    - ``tmax``: scalar or (N,) — only obstructions within ray parameter
      ``t < tmax`` count (``numpy.inf`` for "to the environment");
    - returns an (N,) bool array, True where the ray is obstructed.

    Occluders inject at exactly two points: the lighting model (what light
    reaches the stone) and escape queries (whether an exiting ray reaches
    the environment or observer).
    """

    def blocked(self, origins, directions, tmax):
        raise NotImplementedError


class NullOccluder(Occluder):
    """The Phase 4 occluder: nothing in the scene blocks anything."""

    def blocked(self, origins, directions, tmax):
        return np.zeros(len(np.atleast_2d(directions)), dtype=bool)


class LightingModel:
    """Base: intensity of the lighting environment seen along directions.

    ``intensity(directions, origins=None)`` evaluates L in [0, 1] per
    direction; rays blocked by the model's occluder score 0. ``origins``
    (stone-frame escape points) default to the origin when omitted —
    correct for the NullOccluder and for distant-environment models.
    """

    def __init__(self, occluder=None):
        self.occluder = occluder if occluder is not None else NullOccluder()

    def _radiance(self, directions):
        raise NotImplementedError

    def intensity(self, directions, origins=None):
        directions = np.atleast_2d(np.asarray(directions, np.float64))
        if origins is None:
            origins = np.zeros_like(directions)
        value = self._radiance(directions)
        mask = self.occluder.blocked(origins, directions, np.inf)
        return np.where(mask, 0.0, value)

    def describe(self):
        """One-line mathematical definition, for report output."""
        raise NotImplementedError


class UniformHemisphere(LightingModel):
    """L = 1 for dir_z > 0, else 0 (isotropic diffuse dome; the default)."""

    def _radiance(self, directions):
        return (directions[:, 2] > 0.0).astype(np.float64)

    def describe(self):
        return ("uniform hemisphere: L = 1 for upward escape directions "
                "(dir_z > 0), 0 below the horizon")


class CosineDome(LightingModel):
    """L = max(dir_z, 0): dome radiance proportional to elevation cosine."""

    def _radiance(self, directions):
        return np.maximum(directions[:, 2], 0.0)

    def describe(self):
        return "cosine-weighted dome: L = max(dir_z, 0)"


class RingLight(LightingModel):
    """L = 1 in the elevation annulus [lo_deg, hi_deg] above the horizon."""

    def __init__(self, lo_deg=30.0, hi_deg=60.0, occluder=None):
        super().__init__(occluder)
        if not 0.0 <= lo_deg < hi_deg <= 90.0:
            raise ValueError(
                "ring light needs 0 <= lo_deg < hi_deg <= 90, got %r..%r"
                % (lo_deg, hi_deg))
        self.lo_deg = float(lo_deg)
        self.hi_deg = float(hi_deg)

    def _radiance(self, directions):
        # Elevation angle above the horizon: asin(dir_z) for unit dirs.
        z = np.clip(directions[:, 2], -1.0, 1.0)
        elev = np.degrees(np.arcsin(z))
        return ((elev >= self.lo_deg) & (elev <= self.hi_deg)).astype(
            np.float64)

    def describe(self):
        return ("ring light: L = 1 for escape elevations in [%g, %g] "
                "degrees above the horizon, else 0"
                % (self.lo_deg, self.hi_deg))


class HeadShadow(LightingModel):
    """A dark cone about the view axis composed over any base model.

    L = 0 for directions within ``half_angle_deg`` of +Z (the observer's
    head blocks that light), else the base model's L. The base model's own
    occluder still applies outside the cone; the head-shadow cone test is
    purely angular.
    """

    def __init__(self, base, half_angle_deg=10.0):
        super().__init__(base.occluder)
        if not 0.0 <= half_angle_deg <= 90.0:
            raise ValueError("head shadow half-angle must be in [0, 90], "
                             "got %r" % (half_angle_deg,))
        self.base = base
        self.half_angle_deg = float(half_angle_deg)
        self._cos_cone = math.cos(math.radians(self.half_angle_deg))

    def in_cone(self, directions):
        """Bool mask: direction within the head-shadow cone about +Z."""
        directions = np.atleast_2d(np.asarray(directions, np.float64))
        return directions[:, 2] >= self._cos_cone

    def intensity(self, directions, origins=None):
        value = self.base.intensity(directions, origins)
        return np.where(self.in_cone(directions), 0.0, value)

    def describe(self):
        return ("%s, with an observer head shadow: L = 0 within %g degrees "
                "of the view axis" % (self.base.describe(),
                                      self.half_angle_deg))
