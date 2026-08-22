# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run the test suite from inside FreeCADCmd.

Fallback for environments where FreeCAD is not importable from the plain
Python interpreter (`freecadcmd tests/run_headless.py`). FreeCADCmd may
swallow SystemExit and drop stdout written near exit (verified locally), so
the exit status is written to ``pytest_exit.txt`` in the repo root for the
caller to check.

The process exits via ``os._exit`` rather than ``sys.exit``: once the suite
has run and the exit status is on disk, nothing of value happens after this
script, and letting FreeCADCmd tear down Qt (with a QApplication and widgets
created by the dock tests still around) segfaults inside QWidget destruction
on the CI runners — turning a green suite into a red job. Same reasoning as
``.github/scripts/verify_install.py``.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

rc = pytest.main(["-v", "tests"])
with open(os.path.join(ROOT, "pytest_exit.txt"), "w") as stream:
    stream.write("%d\n" % rc)
sys.stdout.flush()
sys.stderr.flush()
os._exit(rc)
