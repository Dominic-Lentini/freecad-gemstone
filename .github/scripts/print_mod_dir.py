# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run under FreeCADCmd: print this FreeCAD installation's user Mod directory
on a greppable marker line (FreeCADCmd prints banners around script output)."""
import os

import FreeCAD  # noqa: F401  (must run inside FreeCADCmd)

import sys

print("LAPIDARY_MOD_DIR=" + os.path.join(FreeCAD.getUserAppDataDir(), "Mod"))
sys.stdout.flush()
os._exit(0)
