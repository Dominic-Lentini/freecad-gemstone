# SPDX-License-Identifier: LGPL-2.1-or-later
"""Facet plane math for the Lapidary workbench (DESIGN.md section 2.1, normative).

Pure Python + ``math`` only. This module must never import FreeCAD or any GUI
module; it is shared by the modeling pipeline, the .ASC I/O layer, and the
headless test suite.

Conventions (quoted from DESIGN.md):

    Gem Axis: the rotation axis shared by mast/dop in the physical process.
    Canonical axis is +Z. Crown side is +Z, pavilion side is -Z.

    Index Gear N: integer teeth count. Common: 96, 80, 77, 72, 64, 120.

    Index i: integer 0...N (N == 0). Determines azimuth of the facet normal.

    Angle theta: cutting angle in degrees, measured such that 0 deg = table
    (facet plane perpendicular to the gem axis) and 90 deg = girdle (facet
    plane parallel to the axis). This matches faceting-machine protractor
    convention and GemCad convention.

    Distance d: perpendicular distance (mm in-document; dimensionless on .ASC
    import) from the origin to the facet plane, along the facet normal.

    Cheater / Index Offset: signed fractional index offset applied to a tier.

Facet plane math (DESIGN.md section 2.1, verbatim)::

    phi = dir * 360 deg * (i + c) / N       # azimuth about +Z; dir = +-1 handedness flag, default +1
                                            # (RESOLVED in Phase 2: GemCad indices increase
                                            #  counter-clockwise viewed from the crown, so the default
                                            #  is +1; a negative .ASC gear reverses it. See
                                            #  faceting/asc_io/FORMAT_NOTES.md.)
    n = ( sin(theta)*cos(phi),  sin(theta)*sin(phi),  +cos(theta) )   if s = Crown
    n = ( sin(theta)*cos(phi),  sin(theta)*sin(phi),  -cos(theta) )   if s = Pavilion

    Sanity checks: theta=0 crown -> n = +Z (table). theta=90 -> n horizontal
    (girdle facet, identical for either side). Typical pavilion main
    theta ~ 41-43 deg -> normal points down-and-out. Dop transfer is exactly
    this sign flip of n_z -- it is a mirror through the girdle plane, not a
    rotation.

    The facet plane is { x : n . x = d } with d > 0. Cutting a facet retains
    the half-space n . x <= d.
"""

import math
from enum import Enum

__all__ = [
    "DEFAULT_HANDEDNESS",
    "Side",
    "side_sign",
    "azimuth_deg",
    "facet_normal",
    "facet_plane",
    "point_on_plane",
    "signed_distance",
    "is_retained",
]

#: Default value of the ``dir`` handedness flag from section 2.1. Resolved in
#: Phase 2 against the GemCad manual and sample .ASC files: GemCad's index
#: numbers increase counter-clockwise viewed from the crown (+Z), so the
#: default is +1. See faceting/asc_io/FORMAT_NOTES.md.
DEFAULT_HANDEDNESS = +1


class Side(Enum):
    """Working side of a facet tier (DESIGN.md section 2: enum {Crown, Pavilion})."""

    CROWN = "Crown"
    PAVILION = "Pavilion"


def _as_side(side):
    """Coerce ``side`` to a :class:`Side`. Accepts Side members or their
    string values ("Crown" / "Pavilion", case-insensitive)."""
    if isinstance(side, Side):
        return side
    if isinstance(side, str):
        try:
            return Side(side.capitalize())
        except ValueError:
            pass
    raise ValueError(
        "side must be Side.CROWN, Side.PAVILION, 'Crown' or 'Pavilion', got %r" % (side,)
    )


def side_sign(side):
    """Sign of the z-component of the facet normal: +1.0 for Crown, -1.0 for
    Pavilion. Dop transfer is exactly this sign flip of n_z."""
    return 1.0 if _as_side(side) is Side.CROWN else -1.0


def _check_gear(gear):
    if isinstance(gear, bool) or not isinstance(gear, int):
        raise ValueError("index gear must be an integer, got %r" % (gear,))
    if gear < 1:
        raise ValueError("index gear must be >= 1, got %r" % (gear,))
    return gear


def _check_handedness(handedness):
    if handedness not in (1, -1):
        raise ValueError("handedness (dir) must be +1 or -1, got %r" % (handedness,))
    return int(handedness)


def azimuth_deg(gear, index, index_offset=0.0, handedness=DEFAULT_HANDEDNESS):
    """Azimuth phi of the facet normal about +Z, in degrees.

    phi = dir * 360 * (i + c) / N, with gear ``N``, index ``i`` (canonically an
    integer 0...N, N == 0; real values are accepted), per-tier index offset
    (cheater) ``c`` (fractional indices allowed), and handedness flag
    ``dir`` = +-1 (default +1: GemCad convention, indices counter-clockwise
    viewed from the crown).

    The result is not wrapped into any particular range; callers that need a
    canonical range should reduce it modulo 360.
    """
    _check_gear(gear)
    return _check_handedness(handedness) * 360.0 * (float(index) + float(index_offset)) / gear


def facet_normal(angle_deg, gear, index, side=Side.CROWN, index_offset=0.0,
                 handedness=DEFAULT_HANDEDNESS):
    """Unit outward normal of a facet plane, as an (x, y, z) tuple.

    ``angle_deg`` is the cutting angle theta: 0 = table (plane perpendicular
    to the gem axis), 90 = girdle (plane parallel to the axis). ``side``
    selects the sign of n_z: +cos(theta) for Crown, -cos(theta) for Pavilion.
    """
    s = side_sign(side)
    theta = math.radians(float(angle_deg))
    phi = math.radians(azimuth_deg(gear, index, index_offset, handedness))
    sin_t = math.sin(theta)
    return (sin_t * math.cos(phi), sin_t * math.sin(phi), s * math.cos(theta))


def facet_plane(angle_deg, gear, index, distance, side=Side.CROWN, index_offset=0.0,
                handedness=DEFAULT_HANDEDNESS):
    """Facet plane { x : n . x = d } as an ((nx, ny, nz), d) pair, d > 0.

    ``distance`` is the perpendicular distance from the origin to the plane
    along the facet normal; it must be strictly positive (section 2.1).
    """
    d = float(distance)
    if not d > 0.0:
        raise ValueError("facet plane distance must be > 0, got %r" % (distance,))
    return facet_normal(angle_deg, gear, index, side, index_offset, handedness), d


def point_on_plane(normal, distance):
    """The foot of the perpendicular from the origin: the point d*n on the
    plane { x : n . x = d }."""
    d = float(distance)
    return (normal[0] * d, normal[1] * d, normal[2] * d)


def signed_distance(normal, distance, point):
    """Signed distance n . x - d of ``point`` from the plane { x : n . x = d }.

    Negative means the point lies inside the retained half-space, positive
    means it is cut away, zero means it lies exactly on the facet plane
    (``normal`` is assumed to be unit length).
    """
    return (normal[0] * point[0] + normal[1] * point[1] + normal[2] * point[2]
            - float(distance))


def is_retained(normal, distance, point, tol=1e-9):
    """True if ``point`` survives the cut: cutting a facet retains the
    half-space n . x <= d (within ``tol``)."""
    return signed_distance(normal, distance, point) <= tol
