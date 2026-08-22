# SPDX-License-Identifier: LGPL-2.1-or-later
"""GemCad .ASC parser (pure Python; format facts in FORMAT_NOTES.md).

Two layers:

* :func:`parse_asc` — faithful record-level parse of the text into an
  :class:`AscDesign` (raw signed gear, raw fractional/negative indices,
  per-facet names, cutting-instruction texts, verbatim header/footnote
  lines). Continuation lines (leading whitespace) are joined to the current
  ``a`` record, which the reference C# reader gets wrong — see FORMAT_NOTES.
* :func:`design_tier_specs` — normalization onto the DESIGN.md section 3
  tier model: angle sign -> working side, integer gear offset rebased into
  the indices, fractional indices grouped into sub-tiers sharing one
  IndexOffset, indices normalized to 1..N (N standing in for 0).
"""

import math
import re
from dataclasses import dataclass, field

__all__ = [
    "AscParseError",
    "AscFacet",
    "AscTier",
    "AscDesign",
    "TierSpec",
    "parse_asc",
    "read_asc",
    "design_tier_specs",
]

_FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


class AscParseError(ValueError):
    """Raised for a structurally invalid .ASC file."""

    def __init__(self, message, line_number=None):
        if line_number is not None:
            message = "line %d: %s" % (line_number, message)
        super().__init__(message)
        self.line_number = line_number


@dataclass
class AscFacet:
    """One facet of a tier record: raw index token value + optional name."""

    index: float
    name: str = ""


@dataclass
class AscTier:
    """One ``a`` record, faithful to the file."""

    angle: float                 # signed; negative = pavilion
    distance: float              # center-to-facet, design units
    facets: list = field(default_factory=list)          # [AscFacet]
    instructions: list = field(default_factory=list)    # ["G ..." texts]


@dataclass
class AscDesign:
    """A parsed .ASC file."""

    gear: int = 96               # signed; sign = index direction
    gear_offset: float = 0.0     # in teeth
    symmetry_folds: int = 1
    symmetry_mirror: str = "y"   # verbatim flag token
    refractive_index: float = None
    headers: list = field(default_factory=list)
    footnotes: list = field(default_factory=list)
    tiers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _parse_facet_items(tokens, tier, line_number, warnings):
    """Scan the item tokens of an ``a`` record (or continuation) line.

    Numbers are facet indices; ``n <tok>`` names the preceding facet;
    ``G`` starts a cutting-instruction that extends to the end of the line.
    Any other token also ends index parsing (matching the reference reader's
    tolerance) but is recorded as a warning.
    """
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token == "n":
            if position + 1 >= len(tokens):
                raise AscParseError("'n' with no name token", line_number)
            if not tier.facets:
                raise AscParseError("'n %s' with no preceding index"
                                    % tokens[position + 1], line_number)
            tier.facets[-1].name = tokens[position + 1]
            position += 2
        elif token == "G":
            text = " ".join(tokens[position + 1:])
            tier.instructions.append(text)
            return
        elif _FLOAT_RE.match(token):
            tier.facets.append(AscFacet(float(token)))
            position += 1
        else:
            text = " ".join(tokens[position:])
            tier.instructions.append(text)
            warnings.append(
                "line %d: unrecognized token %r treated as cutting "
                "instructions" % (line_number, token))
            return


def parse_asc(text):
    """Parse .ASC text into an :class:`AscDesign`."""
    design = AscDesign()
    current_tier = None
    seen_banner = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue

        # Continuation of a wrapped ``a`` record: leading whitespace.
        if raw_line[0] in " \t":
            if current_tier is None:
                design.warnings.append(
                    "line %d: continuation line with no open facet record "
                    "ignored" % line_number)
                continue
            _parse_facet_items(raw_line.split(), current_tier, line_number,
                               design.warnings)
            continue

        parts = raw_line.split()
        keyword = parts[0]

        if keyword == "GemCad":
            seen_banner = True
            current_tier = None
        elif keyword == "g":
            if len(parts) < 2:
                raise AscParseError("malformed gear line", line_number)
            try:
                design.gear = int(float(parts[1]))
                design.gear_offset = float(parts[2]) if len(parts) > 2 else 0.0
            except ValueError:
                raise AscParseError("malformed gear line %r" % raw_line,
                                    line_number)
            if design.gear == 0:
                raise AscParseError("index gear must be non-zero", line_number)
            current_tier = None
        elif keyword == "y":
            if len(parts) < 2:
                raise AscParseError("malformed symmetry line", line_number)
            try:
                design.symmetry_folds = int(parts[1])
            except ValueError:
                raise AscParseError("malformed symmetry line %r" % raw_line,
                                    line_number)
            design.symmetry_mirror = parts[2] if len(parts) > 2 else ""
            current_tier = None
        elif keyword == "I":
            try:
                design.refractive_index = float(parts[1])
            except (IndexError, ValueError):
                raise AscParseError("malformed refractive-index line %r"
                                    % raw_line, line_number)
            current_tier = None
        elif keyword == "H":
            design.headers.append(raw_line[2:].rstrip())
            current_tier = None
        elif keyword == "F":
            design.footnotes.append(raw_line[2:].rstrip())
            current_tier = None
        elif keyword == "a":
            if len(parts) < 3:
                raise AscParseError("malformed facet record %r" % raw_line,
                                    line_number)
            try:
                angle = float(parts[1])
                distance = float(parts[2])
            except ValueError:
                raise AscParseError("malformed facet record %r" % raw_line,
                                    line_number)
            current_tier = AscTier(angle=angle, distance=distance)
            design.tiers.append(current_tier)
            _parse_facet_items(parts[3:], current_tier, line_number,
                               design.warnings)
        else:
            design.warnings.append("line %d: unknown record type %r ignored"
                                   % (line_number, keyword))
            current_tier = None

    if not seen_banner:
        design.warnings.append("no 'GemCad 5.0' banner line found")
    return design


def read_asc(path):
    """Parse an .ASC file from disk."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as stream:
        return parse_asc(stream.read())


# ---------------------------------------------------------------------------
# Normalization onto the DESIGN.md section 3 tier model
# ---------------------------------------------------------------------------

@dataclass
class TierSpec:
    """One FacetTier-shaped tier derived from an ``a`` record."""

    angle: float                 # magnitude, degrees
    side: str                    # "Crown" / "Pavilion"
    distance: float              # design units (imported 1:1 as mm)
    indices: list                # sorted ints in 1..N (N stands in for 0)
    index_offset: float          # shared fractional part (cheater)
    name: str                    # first facet name in the record
    instructions: list           # verbatim G texts


def _side_of(angle):
    # The sign encodes the working side (manual: "negative for pavilion
    # facets"); copysign catches a hypothetical "-0.0" culet record.
    return "Pavilion" if math.copysign(1.0, angle) < 0 else "Crown"


def design_tier_specs(design):
    """Normalize a parsed design into :class:`TierSpec` tiers.

    * The integer part of the gear offset is rebased into the indices
      (``i' = (i - offset) mod N``); a fractional offset part (never observed,
      see FORMAT_NOTES) folds into each tier's IndexOffset.
    * A record mixing different fractional index parts is split into one spec
      per distinct fraction, in order of first appearance.
    * Records with no indices (not observed) become a single axial facet
      (empty index list, matching the section 3 table convention).
    """
    gear = abs(design.gear)
    offset_int = math.floor(design.gear_offset)
    offset_frac = design.gear_offset - offset_int

    specs = []
    for tier in design.tiers:
        if tier.distance < 0.0:
            raise AscParseError(
                "negative facet distance %g (UNVERIFIED culet form, see "
                "FORMAT_NOTES.md) is not supported" % tier.distance)
        side = _side_of(tier.angle)
        angle = abs(tier.angle)
        if not tier.facets:
            specs.append(TierSpec(angle, side, tier.distance, [], 0.0, "",
                                  list(tier.instructions)))
            continue

        groups = {}   # rounded fraction -> [(int index 1..N, name)]
        order = []
        for facet in tier.facets:
            value = (facet.index - offset_int) % gear
            fraction = value - math.floor(value)
            if fraction > 1.0 - 1e-9:   # float noise at the next tooth
                fraction = 0.0
                value = math.ceil(value) % gear
            key = round(fraction, 6)
            whole = int(math.floor(value)) % gear
            whole = gear if whole == 0 else whole
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((whole, facet.name))

        for key in order:
            members = groups[key]
            name = next((n for _i, n in members if n), "")
            indices = sorted({i for i, _n in members})
            specs.append(TierSpec(
                angle, side, tier.distance, indices,
                round(key - offset_frac, 9), name,
                list(tier.instructions)))
    return specs
