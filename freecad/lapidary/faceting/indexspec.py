# SPDX-License-Identifier: LGPL-2.1-or-later
"""Index-list entry parsing for facet tiers (DESIGN.md section 4, item 2).

Pure Python (no FreeCAD, no GUI) so the parsing rules are testable with plain
pytest. The FacetTier task panel feeds user text through here; the index-wheel
widget and the Indices property both speak plain integer lists.

Accepted forms:

* Comma list: ``3,21,27,45``. Separators may be commas, whitespace, or
  dashes (printed faceting diagrams commonly use dash-separated lists like
  ``03-09-15-21``).
* Symmetric shorthand: ``96/8`` = 8 evenly spaced teeth on a 96 gear (every
  12th tooth), anchored on tooth N. The numerator must equal the tier's
  effective gear and must be evenly divisible by the count. Shifting the
  whole pattern to another starting tooth is done visually (the panel's
  rotate-pattern buttons and index wheel), not by a numeric field.
* Empty string: the empty list — DESIGN.md section 3 allows an empty index
  list to mean "single axial facet" (the table).

Indices are normalized to the range 1..N with N standing in for 0 (index N
is the same tooth as index 0), deduplicated, and sorted.
"""

import re

__all__ = ["parse_index_spec", "format_indices", "rotate_indices",
           "mirror_indices",
           "symmetry_folds", "symmetry_orbit", "symmetry_regions",
           "expand_symmetric", "IndexSpecError"]

_SHORTHAND_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_SEPARATOR_RE = re.compile(r"[,\s\-]+")


class IndexSpecError(ValueError):
    """Raised when an index entry string cannot be parsed."""


def _normalize(index, gear):
    """Map an index in 0..N onto 1..N (N stands in for 0)."""
    wrapped = index % gear
    return gear if wrapped == 0 else wrapped


def parse_index_spec(text, gear):
    """Parse an index entry string into a sorted list of unique indices.

    ``gear`` is the tier's effective index gear N.
    """
    if gear < 1:
        raise IndexSpecError("index gear must be >= 1, got %r" % (gear,))
    if text is None:
        return []
    text = text.strip()
    if not text:
        return []

    m = _SHORTHAND_RE.match(text)
    if m:
        total, count = int(m.group(1)), int(m.group(2))
        if total != gear:
            raise IndexSpecError(
                "shorthand %d/%d does not match the tier's index gear %d"
                % (total, count, gear))
        if count < 1 or total % count != 0:
            raise IndexSpecError(
                "shorthand %d/%d: %d does not divide evenly into %d"
                % (total, count, count, total))
        step = total // count
        indices = [_normalize(j * step, gear) for j in range(count)]
        return sorted(set(indices))

    indices = []
    for token in _SEPARATOR_RE.split(text):
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            raise IndexSpecError("invalid index %r in %r" % (token, text))
        if value < 0 or value > gear:
            raise IndexSpecError(
                "index %d out of range 0..%d" % (value, gear))
        indices.append(_normalize(value, gear))
    return sorted(set(indices))


def rotate_indices(indices, gear, teeth):
    """Rotate a whole index pattern by ``teeth`` gear teeth (positive or
    negative), wrapping around the gear. Used by the panel's rotate-pattern
    buttons to shift e.g. a mains pattern onto the break positions."""
    if gear < 1:
        raise IndexSpecError("index gear must be >= 1, got %r" % (gear,))
    return sorted({_normalize(int(i) + int(teeth), gear) for i in indices})


def mirror_indices(indices, gear, axis):
    """The mirror image of an index pattern across a wheel axis, sorted.

    ``axis="ns"`` reflects across the vertical north-south axis (through
    tooth N and tooth N/2): ``t -> N - t``, swapping east and west.
    ``axis="ew"`` reflects across the horizontal east-west axis:
    ``t -> N/2 - t``, swapping north and south. On an odd gear the
    east-west image lands between teeth and snaps to the nearest one,
    the same compromise as a non-divisor symmetry fold. The mapping is
    handedness-independent: flipping the count direction flips both a
    tooth and its image. Union the result with the original to *copy*
    a pattern from one side to the other.
    """
    if gear < 1:
        raise IndexSpecError("index gear must be >= 1, got %r" % (gear,))
    if axis not in ("ns", "ew"):
        raise IndexSpecError("mirror axis must be 'ns' or 'ew', got %r"
                             % (axis,))
    pivot = 0.0 if axis == "ns" else gear / 2.0
    return sorted({_normalize(int(round(pivot - i)), gear)
                   for i in indices})


def symmetry_folds(gear):
    """The radial-symmetry folds the index wheel offers: 1 (none) and
    every fold from 2 to 9, for any gear.

    A fold that does not divide the gear evenly (5, 7 or 9 on a 96
    gear) places its ideal copies *between* teeth; the orbit snaps each
    copy to the nearest tooth (:func:`symmetry_orbit`), the same
    compromise a faceter makes cutting a 5-fold design on a gear built
    for eights — the pattern is near-symmetric, quantized to the gear.
    Folds that do divide the gear stay exact.
    """
    if gear < 1:
        raise IndexSpecError("index gear must be >= 1, got %r" % (gear,))
    return list(range(1, 10))


def symmetry_regions(fold):
    """How many alternating contrast regions the index wheel shades for a
    symmetry ``fold``.

    Alternating shading only closes consistently around a circle when the
    region count is even, so an **odd** fold takes ``2 * fold`` regions
    and an even fold takes ``fold``. With one region centred on each pole
    that reads correctly either way: 3-fold gets 6 regions (every pole
    shaded, the gaps light), while 4-fold gets 4 (alternate poles
    shaded). An odd fold shaded in ``fold`` regions would butt two shaded
    wedges together at the wrap-around and misrepresent the symmetry.
    """
    if fold < 1:
        raise IndexSpecError("symmetry fold must be >= 1, got %r" % (fold,))
    if fold == 1:
        return 0                      # no symmetry: nothing to shade
    return fold if fold % 2 == 0 else 2 * fold


def symmetry_orbit(index, gear, fold):
    """The ``fold`` symmetric copies of one tooth, sorted, normalized to
    1..N. Ideal copies sit every gear/fold teeth; each is rounded to the
    nearest integer tooth, so divisor folds are exact and non-divisor
    folds (5, 7, 9 on a 96 gear) are the gear-quantized approximation.
    Coincident rounded copies deduplicate."""
    if fold < 1:
        raise IndexSpecError(
            "symmetry fold must be >= 1, got %r" % (fold,))
    step = gear / float(fold)
    return sorted({_normalize(int(round(index + k * step)), gear)
                   for k in range(fold)})


def expand_symmetric(indices, gear, fold):
    """Close an index list under ``fold``-fold radial symmetry (the union
    of every index's orbit), sorted."""
    closed = set()
    for index in indices:
        closed.update(symmetry_orbit(index, gear, fold))
    return sorted(closed)


def format_indices(indices, gear=96):
    """Format an index list GemCad-printout style: zero-padded, dash-separated
    (``03-09-15-21``). Returns an empty string for the empty list."""
    width = max(2, len(str(gear)))
    return "-".join("%0*d" % (width, i) for i in indices)
