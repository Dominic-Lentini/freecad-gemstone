# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pytest bootstrap: make the repository's own package win over any installed
copy of the addon (the "shadowing trap" documented in CLAUDE.md).

``import FreeCAD`` eagerly imports every addon under the user's Mod directory
during startup, so a stale installed Lapidary can already be bound in
``sys.modules`` before any test runs. Defense in depth, per CLAUDE.md:

1. put the repo root at the front of ``sys.path`` BEFORE importing FreeCAD;
2. import FreeCAD here (once, early), then purge any ``freecad.*`` modules it
   eagerly bound so they re-resolve from the repo;
3. re-assert the repo root at position 0 afterwards.

Harmless under plain pytest without FreeCAD installed.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

while ROOT in sys.path:
    sys.path.remove(ROOT)
sys.path.insert(0, ROOT)

try:
    import FreeCAD  # noqa: F401  (side effect: extends sys.path, imports Mod addons)
except ImportError:
    pass

for stale in [name for name in sys.modules if name.split(".")[0] == "freecad"]:
    del sys.modules[stale]
while ROOT in sys.path:
    sys.path.remove(ROOT)
sys.path.insert(0, ROOT)
