# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run under FreeCADCmd with the addon installed in the user Mod directory.

Verifies that `import freecad.gemstone` works, that the workbench metadata
(package.xml) loads through FreeCAD's own Metadata parser, and that the GUI
entry point at least byte-compiles. FreeCADCmd does not reliably propagate a
nonzero exit status from script exceptions, so this script reports via
os._exit explicitly.
"""
import os
import py_compile
import sys
import traceback


def main():
    import FreeCAD as App

    print("FreeCAD version:", ".".join(App.Version()[0:3]))

    # 1. The namespace package imports headless.
    import freecad.gemstone
    from freecad.gemstone import version
    from freecad.gemstone.core import gemmath

    print("freecad.gemstone", version.__version__, "from", freecad.gemstone.__file__)

    # 2. gemmath sanity under FreeCAD's Python.
    n = gemmath.facet_normal(0.0, 96, 0, gemmath.Side.CROWN)
    assert abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12 and abs(n[2] - 1.0) < 1e-12, n

    # 3. Workbench metadata loads through FreeCAD's package.xml parser.
    addon_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(freecad.gemstone.__file__))))
    package_xml = os.path.join(addon_dir, "package.xml")
    assert os.path.isfile(package_xml), "package.xml not found at " + package_xml
    md = App.Metadata(package_xml)
    assert md.Name == "Lapidary", md.Name
    assert md.Version == version.__version__, (str(md.Version), version.__version__)
    content = md.Content
    assert "workbench" in content and len(content["workbench"]) == 1, content
    wb = content["workbench"][0]
    print("workbench metadata:", md.Name, md.Version, "classname:", wb.Classname)
    assert wb.Classname == "LapidaryWorkbench", wb.Classname

    # 4. The declared icon exists.
    icon = os.path.join(addon_dir, md.Icon)
    assert os.path.isfile(icon), "workbench icon missing: " + icon

    # 5. init_gui.py needs FreeCADGui to import, but it must at least compile.
    init_gui = os.path.join(addon_dir, "freecad", "gemstone", "init_gui.py")
    py_compile.compile(init_gui, doraise=True)

    print("GEMSTONE_VERIFY_OK")


try:
    main()
except BaseException:
    traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
