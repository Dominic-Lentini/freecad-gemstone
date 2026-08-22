# SPDX-License-Identifier: LGPL-2.1-or-later
"""Oversized-box half-space cut construction (DESIGN.md section 2.1).

    Each tier's shape = (previous shape in the pipeline) minus the union of
    half-space cuts for every index in its list. Implementation: for each cut,
    construct an oversized box (>= 10x stock bounding diagonal) whose inner
    face lies on the facet plane with outward normal ``n``, and boolean-cut
    it. Do not use meshes anywhere in the modeling pipeline -- all geometry
    stays exact OpenCascade B-Rep so every facet is an analytic planar face
    with an exact normal.

This module imports FreeCAD's App side and Part only (no GUI); it runs under
FreeCADCmd headless.
"""

import FreeCAD
import Part

__all__ = ["OVERSIZE_FACTOR", "cutting_box", "cut_halfspace",
           "retain_halfspace"]

#: Minimum ratio of every box extent to the reference bounding diagonal.
OVERSIZE_FACTOR = 10.0


def _as_vector(v):
    if isinstance(v, FreeCAD.Vector):
        return FreeCAD.Vector(v)
    return FreeCAD.Vector(float(v[0]), float(v[1]), float(v[2]))


def cutting_box(normal, distance, ref_bbox, factor=OVERSIZE_FACTOR):
    """Build the oversized cutting box for the facet plane ``n . x = d``.

    The box occupies (a bounded, oversized chunk of) the discarded half-space
    ``n . x >= d``: its inner face lies exactly on the facet plane, so cutting
    the box from a solid retains ``n . x <= d`` and leaves a planar facet
    whose outward normal is exactly ``n``.

    ``normal``   -- facet plane unit normal (FreeCAD.Vector or 3-sequence).
    ``distance`` -- perpendicular plane distance from the origin, > 0.
    ``ref_bbox`` -- FreeCAD.BoundBox of the shape about to be cut; sizes the
                    box so it covers every point of that shape beyond the
                    plane. Extents are >= ``factor`` (default 10) times the
                    bounding diagonal per DESIGN.md section 2.1.

    Returns a Part solid (exact B-Rep box).
    """
    n = _as_vector(normal)
    if n.Length == 0:
        raise ValueError("cutting plane normal must be non-zero")
    n.normalize()
    d = float(distance)

    if not ref_bbox.isValid():
        raise ValueError("reference bounding box is invalid/empty")
    diag = ref_bbox.DiagonalLength
    if not diag > 0.0:
        raise ValueError("reference bounding box is degenerate (zero diagonal)")

    # Foot of the perpendicular from the origin: the box is centered laterally
    # on this point. Any point of the reference shape lies within
    # |center - foot| + diag/2 of it, so half-extents of factor*diag plus that
    # margin are guaranteed to cover the shape's entire slab beyond the plane.
    foot = n * d
    margin = (ref_bbox.Center - foot).Length
    half = factor * diag + margin

    box = Part.makeBox(2.0 * half, 2.0 * half, half)
    box.translate(FreeCAD.Vector(-half, -half, 0.0))
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), n)
    box.Placement = FreeCAD.Placement(foot, rotation).multiply(box.Placement)
    return box


def cut_halfspace(shape, normal, distance, factor=OVERSIZE_FACTOR):
    """Cut the half-space ``n . x > d`` away from ``shape``.

    Returns the boolean-cut result (which may be an empty shape if the cut
    annihilates the solid). The caller is responsible for the DESIGN.md
    section 3 failure handling (no-op and annihilation detection).
    """
    box = cutting_box(normal, distance, shape.BoundBox, factor)
    return shape.cut(box)


def retain_halfspace(shape, normal, distance, factor=OVERSIZE_FACTOR):
    """Intersect ``shape`` with the retained half-space ``n . x <= d``.

    Mathematically identical to :func:`cut_halfspace` (the box lies on the
    retained side, its inner face exactly on the plane, so the created facet
    has the exact outward normal ``n``), but formulated as a boolean
    ``common``. OpenCascade's cut has been observed to fail *silently*
    (returning its input) on certain operand pairs where common succeeds —
    see docs/dev-notes.md — so the pipeline uses this as the arbiter when a
    cut claims to have removed nothing.
    """
    n = _as_vector(normal)
    if n.Length == 0:
        raise ValueError("cutting plane normal must be non-zero")
    n.normalize()
    box = cutting_box(n.negative(), -float(distance), shape.BoundBox, factor)
    return shape.common(box)
