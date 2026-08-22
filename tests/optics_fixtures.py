# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared FreeCAD-free fixture polytopes for the optics test suite.

The SRB here is the same published Standard Round Brilliant as
``test_pipeline.py`` (facettieren.ch printout: angles for R.I. 1.54, gear
96, 73 facets) with the same distance derivations — duplicated instead of
imported because ``test_pipeline`` skips at import time without FreeCAD,
and the optics fixtures must build from pure plane math anywhere.

The wedge and prism are the closed-form analytic fixtures of
DESIGN_OPTICS.md section 10; their derivations live in the tests that use
them.
"""

import math

import numpy as np

from freecad.lapidary.core import gemmath
from freecad.lapidary.optics.polytope import NO_TIER, Polytope

GEAR = 96
W = 10.0                       # target girdle width (mm); everything scales
R16 = W / 2.0                  # girdle 16-gon corner radius
D_GIRDLE = R16 * math.cos(math.pi / 16.0)   # 16-gon apothem = plane distance
GIRDLE_TOP = +0.015 * W        # girdle band 0.030 W, centered on the origin
GIRDLE_BOTTOM = -0.015 * W
PAVILION_DEPTH = 0.427 * W     # published P/W
CROWN_HEIGHT = 0.150 * W       # published C/W
CULET_Z = GIRDLE_BOTTOM - PAVILION_DEPTH
TABLE_Z = GIRDLE_TOP + CROWN_HEIGHT

A_G1, A_P1, A_P2 = 90.00, 42.00, 40.50
A_C1, A_C2, A_C3 = 40.68, 33.46, 22.89

IDX16 = list(range(3, 96, 6))              # 03-09-15-...-93
IDX8_MAINS = list(range(12, 97, 12))       # 96-12-24-...-84 (96 = index 0)
IDX8_STARS = list(range(6, 91, 12))        # 06-18-30-...-90


def _rad(deg):
    return math.radians(deg)


# Distance derivations: identical to test_pipeline.py (commented there).
D_P1 = math.sin(_rad(A_P1)) * D_GIRDLE - math.cos(_rad(A_P1)) * GIRDLE_BOTTOM
D_P2 = -math.cos(_rad(A_P2)) * CULET_Z
D_C1 = math.sin(_rad(A_C1)) * D_GIRDLE + math.cos(_rad(A_C1)) * GIRDLE_TOP
D_C2 = math.sin(_rad(A_C2)) * R16 + math.cos(_rad(A_C2)) * GIRDLE_TOP
D_T = TABLE_Z
_CORNER_R = (D_C2 - math.cos(_rad(A_C2)) * TABLE_Z) / math.sin(_rad(A_C2))
D_C3 = (math.sin(_rad(A_C3)) * math.cos(_rad(22.5)) * _CORNER_R
        + math.cos(_rad(A_C3)) * TABLE_Z)

#: (tier name, side, angle, distance, indices) — indices [] = single facet.
SRB_TIERS = [
    ("G1 girdle", "Pavilion", A_G1, D_GIRDLE, IDX16),
    ("P1 breaks", "Pavilion", A_P1, D_P1, IDX16),
    ("P2 mains", "Pavilion", A_P2, D_P2, IDX8_MAINS),
    ("C1 breaks", "Crown", A_C1, D_C1, IDX16),
    ("C2 bezels", "Crown", A_C2, D_C2, IDX8_MAINS),
    ("C3 stars", "Crown", A_C3, D_C3, IDX8_STARS),
    ("Table", "Crown", 0.0, D_T, []),
]


def srb_polytope():
    """The published SRB as a 73-plane Polytope with tier attribution."""
    normals, dists, tier_ids, labels, sides = [], [], [], [], []
    for tier_id, (name, side, angle, distance, indices) in enumerate(
            SRB_TIERS):
        labels.append(name)
        sides.append(side)
        for index in (indices or [0]):
            normals.append(gemmath.facet_normal(angle, GEAR, index, side))
            dists.append(distance)
            tier_ids.append(tier_id)
    return Polytope(np.array(normals), np.array(dists),
                    np.array(tier_ids, dtype=np.intp),
                    tuple(labels), tuple(sides))


def slab_polytope(half_thickness=0.5, half_width=2.0):
    """A flat slab (box "gem") for the textbook normal-incidence series."""
    n = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], dtype=np.float64)
    d = np.array([half_width, half_width, half_width, half_width,
                  half_thickness, half_thickness])
    return Polytope(n, d)


def prism_polytope():
    """A right-angle isoceles prism, hypotenuse at 45 degrees.

    Cross-section in (x, z): vertices (-1, 1), (1, 1), (1, -1); faces are
    the top z = 1 (entry), the leg x = 1, and the hypotenuse x + z = 0
    (outward normal (-1, 0, -1)/sqrt(2)); closed by y = +-1 walls.
    """
    s = 1.0 / math.sqrt(2.0)
    n = np.array([[0, 0, 1], [1, 0, 0], [-s, 0, -s],
                  [0, 1, 0], [0, -1, 0]], dtype=np.float64)
    d = np.array([1.0, 1.0, 0.0, 1.0, 1.0])
    return Polytope(n, d)


def wedge_polytope(pavilion_angle_deg, table_z=0.2, pav_distance=0.5,
                   half_width=1.0):
    """A two-facet wedge pavilion under a table — the windowing fixture.

    Faces: table z = table_z (Crown tier 0), two pavilion planes with
    normals (+-sin a, 0, -cos a) at distance ``pav_distance`` (Pavilion
    tier 1), closed by y = +-half_width walls (no tier). A ray straight
    down through the table meets a pavilion facet at incidence angle a.
    """
    a = math.radians(pavilion_angle_deg)
    n = np.array([
        [0.0, 0.0, 1.0],
        [math.sin(a), 0.0, -math.cos(a)],
        [-math.sin(a), 0.0, -math.cos(a)],
        [0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0],
    ])
    d = np.array([table_z, pav_distance, pav_distance,
                  half_width, half_width])
    tier_ids = np.array([0, 1, 1, NO_TIER, NO_TIER], dtype=np.intp)
    return Polytope(n, d, tier_ids, ("Table", "Pavilion wedge"),
                    ("Crown", "Pavilion"))


def as_reference_input(poly):
    """A Polytope's arrays as the plain-Python inputs of
    tests/reference_tracer.py (data conversion, not shared logic)."""
    planes = [((float(n[0]), float(n[1]), float(n[2])), float(d))
              for n, d in zip(poly.normals, poly.dists)]
    num_tiers = len(poly.tier_labels)
    is_pav = [bool(0 <= t < num_tiers
                   and poly.tier_sides[t] == "Pavilion")
              for t in poly.tier_ids]
    face_tier = [int(t) if 0 <= t < num_tiers else num_tiers
                 for t in poly.tier_ids]
    return planes, is_pav, face_tier, num_tiers
