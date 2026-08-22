# SPDX-License-Identifier: LGPL-2.1-or-later
"""Generate faceting diagrams for every fixture design into ``build/diagrams``.

DESIGN.md section 9 makes the Phase 3 definition of done a *visual* one —
"diagram of imported classic design visually matches its published diagram" —
which no automated test can assert. This script produces the material for that
comparison: one SVG per fixture design, plus a ``name-labels.svg`` variant of
each in the GemCad-identical ``LabelStyle.NAME`` style and a
``angle-labels.svg`` variant carrying the angle annotations.

Run it with FreeCAD's bundled Python (see CLAUDE.md)::

    "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe" tools/generate_diagrams.py

Designs come from the gitignored ``reference/asc-samples`` tree when present
(see ``reference/README.md``); the scripted golden Standard Round Brilliant
from ``tests/test_pipeline.py`` is always generated, so the script is useful
even on a clean checkout.
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Repo root ahead of FreeCAD's Mod scan (CLAUDE.md, "the shadowing trap").
sys.path.insert(0, ROOT)
import FreeCAD  # noqa: E402

for _stale in [name for name in sys.modules if name.split(".")[0] == "freecad"]:
    del sys.modules[_stale]
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from freecad.lapidary.faceting import diagram  # noqa: E402
from freecad.lapidary.faceting.asc_io.document import design_to_gem  # noqa: E402
from freecad.lapidary.faceting.asc_io.parser import read_asc  # noqa: E402

OUT_DIR = os.path.join(ROOT, "build", "diagrams")
SAMPLES_DIR = os.path.join(ROOT, "reference", "asc-samples")

STYLES = [("", diagram.LabelStyle.NAME),
          ("-angle-labels", diagram.LabelStyle.NAME_ANGLE)]


def write_diagrams(gem, stem):
    """Write every label-style variant for one gem; returns the paths."""
    written = []
    for suffix, style in STYLES:
        svg = diagram.gem_diagram_svg(gem, label_style=style)
        if svg is None:
            print("  !! %s has no solid geometry; skipped" % stem)
            return written
        path = os.path.join(OUT_DIR, "%s%s.svg" % (stem, suffix))
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(svg)
        written.append(path)
    return written


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = FreeCAD.newDocument("diagrams")
    written = []

    # The scripted golden design (no reference material needed).
    import test_pipeline
    gem, _stock, _tiers = test_pipeline.build_srb(doc)
    print("golden Standard Round Brilliant")
    written += write_diagrams(gem, "golden-standard-round-brilliant")

    samples = sorted(glob.glob(os.path.join(SAMPLES_DIR, "*", "*.asc")))
    if not samples:
        print("(no reference/asc-samples present — skipping imported designs)")
    for path in samples:
        stem = "%s-%s" % (os.path.basename(os.path.dirname(path)),
                          os.path.splitext(os.path.basename(path))[0])
        print(stem)
        design = read_asc(path)
        if not design.tiers:
            print("  (no tiers in the file; skipped)")
            continue
        imported = design_to_gem(doc, design, label=stem,
                                 source_file=os.path.basename(path))
        doc.recompute()
        written += write_diagrams(imported, stem.lower())

    FreeCAD.closeDocument(doc.Name)
    print("\n%d files in %s:" % (len(written), OUT_DIR))
    for path in written:
        print("  %s" % os.path.relpath(path, ROOT).replace("\\", "/"))


if __name__ == "__main__":
    main()
