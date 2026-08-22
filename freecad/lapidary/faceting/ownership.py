# SPDX-License-Identifier: LGPL-2.1-or-later
"""Face-to-tier ownership resolution (needed by the Phase 3 diagram).

Mechanism (documented also in tier_feature.py and docs/dev-notes.md):
OpenCascade boolean operations do not carry user tags across, so instead of
tagging faces we *record the exact analytic planes* each tier cut with (its
``CutNormals`` / ``CutDistances`` hidden output properties, refreshed every
recompute) and re-associate faces of the final B-Rep by plane matching. This
is robust because DESIGN.md section 2.1 mandates exact planar B-Rep faces
throughout: a facet's plane parameters survive every downstream boolean
unchanged, to floating-point precision.

Attribution rule: a face belongs to the *most-downstream* pipeline feature
whose recorded plane matches the face's plane. If two tiers ever cut the
exact same plane, the later cut re-created the face, so the later tier wins.
Faces matching no tier (e.g. remaining rough) belong to the Stock.

GUI-free; runs headless.
"""

import Part

from freecad.lapidary.faceting import gem_feature

__all__ = ["face_plane", "classify_faces", "classify_faces_with_index",
           "faces_of_tier"]

#: A face matches a recorded cut plane when the normals agree to within this
#: (1 - dot) tolerance and the plane distances to within DISTANCE_TOL mm.
NORMAL_TOL = 1e-9
DISTANCE_TOL = 1e-6


def face_plane(face):
    """The oriented plane of a planar face as (outward normal Vector, d).

    Returns None for non-planar faces. ``normalAt`` accounts for the face's
    orientation (verified against FreeCAD 1.1; see docs/dev-notes.md), so the
    returned normal is the solid's outward normal.
    """
    if not isinstance(face.Surface, Part.Plane):
        return None
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    # CenterOfMass of a planar face lies on its plane.
    return normal, normal.dot(face.CenterOfMass)


def _match_slot(plane, normals, distances):
    """Position of the recorded cut matching ``plane``, or None.

    The slot is an index into the tier's ``CutNormals`` / ``CutDistances``,
    which are recorded in the order of the tier's effective index list — so
    the slot identifies *which gear tooth* cut the face, not merely which
    tier (see :func:`tier_index_of_slot`).
    """
    normal, d = plane
    for slot, (cut_normal, cut_d) in enumerate(zip(normals, distances)):
        if 1.0 - normal.dot(cut_normal) < NORMAL_TOL and abs(d - cut_d) < DISTANCE_TOL:
            return slot
    return None


def tier_index_of_slot(tier, slot):
    """The gear tooth a tier's ``slot``-th recorded cut was made at.

    Mirrors ``tier_feature.execute``: the cuts are recorded in the order of
    ``list(tier.Indices) or [0]`` (an empty index list means one single axial
    facet — the table).
    """
    indices = list(tier.Indices) or [0]
    return indices[slot] if 0 <= slot < len(indices) else None


def classify_faces_with_index(gem):
    """Attribute every face of the gem's final B-Rep to a pipeline feature
    *and* to the gear tooth it was cut at.

    Returns a list, parallel to ``final_shape(gem).Faces``, of
    ``(owner, index)`` pairs: ``owner`` is a FacetTier, or the Stock for
    unmatched/non-planar faces (with ``index`` None). Returns [] when the gem
    has no final shape.
    """
    shape = gem_feature.final_shape(gem)
    if shape is None:
        return []
    features = gem_feature.pipeline_features(gem)
    stock = features[0] if features and gem_feature.is_stock(features[0]) else None
    tiers = [f for f in features if gem_feature.is_tier(f)]

    owners = []
    for face in shape.Faces:
        plane = face_plane(face)
        owner, index = stock, None
        if plane is not None:
            for tier in reversed(tiers):  # most-downstream tier wins
                slot = _match_slot(plane, tier.CutNormals, tier.CutDistances)
                if slot is not None:
                    owner, index = tier, tier_index_of_slot(tier, slot)
                    break
        owners.append((owner, index))
    return owners


def classify_faces(gem):
    """Attribute every face of the gem's final B-Rep to a pipeline feature.

    Returns a list, parallel to ``final_shape(gem).Faces``, of the owning
    document objects (a FacetTier, or the Stock for unmatched/non-planar
    faces). Returns [] when the gem has no final shape.
    """
    return [owner for owner, _index in classify_faces_with_index(gem)]


def faces_of_tier(gem, tier):
    """Indices (into ``final_shape(gem).Faces``) of the faces owned by
    ``tier`` (or by the Stock, if the Stock object is passed)."""
    return [i for i, owner in enumerate(classify_faces(gem)) if owner is tier]
