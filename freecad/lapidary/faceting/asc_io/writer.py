# SPDX-License-Identifier: LGPL-2.1-or-later
"""GemCad .ASC writer (pure Python; format facts in FORMAT_NOTES.md).

Serializes an :class:`~.parser.AscDesign` back to .ASC text. Long facet
records are wrapped at the DOS-era 79-character limit with continuation
lines starting with a space, exactly the form observed in real files;
cutting instructions are emitted as ``G``-to-end-of-line texts.
"""

from freecad.lapidary.faceting.asc_io.parser import AscDesign

__all__ = ["format_asc", "write_asc"]

_MAX_LINE = 79


def _format_number(value):
    """Compact float format for index values: ints without a decimal point,
    fractions trimmed (1.57 not 1.570000)."""
    if abs(value - round(value)) < 1e-9:
        return "%d" % round(value)
    text = "%.6f" % value
    return text.rstrip("0").rstrip(".")


def _wrap_record(first_tokens, more_tokens):
    """Join tokens into lines of at most _MAX_LINE chars; wrapped lines get
    a leading space (continuation marker, see FORMAT_NOTES)."""
    lines = []
    current = list(first_tokens)
    for token in more_tokens:
        candidate_len = len(" ".join(current)) + 1 + len(token)
        if current and candidate_len > _MAX_LINE:
            lines.append(" ".join(current))
            current = ["", token]      # leading "" -> leading space on join
        else:
            current.append(token)
    lines.append(" ".join(current))
    return lines


def format_asc(design):
    """Serialize an AscDesign to .ASC text."""
    lines = ["GemCad 5.0"]
    offset = design.gear_offset
    offset_text = ("%.1f" % offset) if offset == int(offset) else "%g" % offset
    lines.append("g %d %s" % (design.gear, offset_text))
    lines.append("y %d %s" % (design.symmetry_folds,
                              design.symmetry_mirror or "y"))
    if design.refractive_index is not None:
        lines.append("I %g" % design.refractive_index)
    for header in design.headers[:4]:
        lines.append(("H %s" % header).rstrip())

    for tier in design.tiers:
        tokens = []
        for facet in tier.facets:
            tokens.append(_format_number(facet.index))
            if facet.name:
                tokens.append("n")
                tokens.append(facet.name)
        record_lines = _wrap_record(
            ["a", "%.6f" % tier.angle, "%.8f" % tier.distance], tokens)
        # Cutting instructions: G extends to end of line, so each text gets
        # the end of the last line if it fits, else its own continuation.
        for text in tier.instructions:
            suffix = ("G %s" % text).rstrip()
            if len(record_lines[-1]) + 1 + len(suffix) <= _MAX_LINE:
                record_lines[-1] += " " + suffix
            else:
                record_lines.append(" " + suffix)
        lines.extend(record_lines)

    for footnote in design.footnotes[:4]:
        lines.append(("F %s" % footnote).rstrip())
    return "\n".join(lines) + "\n"


def write_asc(design, path):
    """Write an AscDesign to a file."""
    text = format_asc(design)
    with open(path, "w", encoding="utf-8", newline="\r\n") as stream:
        stream.write(text)
    return text
