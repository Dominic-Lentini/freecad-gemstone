# SPDX-License-Identifier: LGPL-2.1-or-later
"""Results-dock structural smoke tests (DESIGN_OPTICS.md section 8,
Phase 4b).

Same offscreen guard style as test_diagram_dock.py: guard on whether a
QApplication can actually be created, not on imports; destroy widgets
deterministically inside the test (deleteLater at interpreter exit
segfaults under FreeCADCmd).
"""

import os

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("FreeCADGui")
    try:
        from PySide import QtWidgets
        return (QtWidgets.QApplication.instance()
                or QtWidgets.QApplication([]))
    except Exception as err:
        pytest.skip("cannot create a QApplication here: %s" % err)


def _dispose(widget):
    from PySide import QtCore, QtWidgets
    widget.close()
    widget.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.DeferredDelete)
    QtWidgets.QApplication.processEvents()


@pytest.fixture
def srb_study(qt_app):
    from freecad.lapidary.optics import study_feature
    from test_pipeline import build_srb

    doc = FreeCAD.newDocument("optics_dock")
    try:
        gem, _stock, _tiers = build_srb(doc)
        study = study_feature.make_study(gem)
        study.GridResolution = 24
        study.TiltSteps = 2
        study.TiltMaxDeg = 10.0
        doc.recompute()
        study_feature.run_study(study)
        yield study
    finally:
        FreeCAD.closeDocument(doc.Name)


class TestResultsDock:
    def test_dock_shows_a_fresh_study(self, srb_study):
        from freecad.lapidary.optics.results_dock import OpticsResultsDock

        dock = OpticsResultsDock()
        try:
            dock.set_study(srb_study)
            assert srb_study.Label in dock._title.text()
            assert not dock._stale_banner.isVisibleTo(dock.widget())
            assert "Light return" in dock._headline.text()
            # Per-tier table: 7 tiers + the "(none)" row.
            assert dock._tier_table.rowCount() == 8
            # The stored maps render into pixmaps.
            shown = [key for key, (_c, image) in dock._maps.items()
                     if image.pixmap() is not None
                     and not image.pixmap().isNull()]
            assert "BrightnessMapFile" in shown
            assert "ClassificationMapFile" in shown
        finally:
            _dispose(dock)

    def test_dock_flags_a_stale_study(self, srb_study):
        from freecad.lapidary.optics.results_dock import OpticsResultsDock

        srb_study.HeadShadowDeg = 15.0
        srb_study.Document.recompute()
        assert srb_study.Stale
        dock = OpticsResultsDock()
        try:
            dock.set_study(srb_study)
            assert dock._stale_banner.isVisibleTo(dock.widget())
            # Old results stay visible behind the banner.
            assert "Light return" in dock._headline.text()
        finally:
            _dispose(dock)

    def test_dock_survives_no_study(self, qt_app):
        from freecad.lapidary.optics.results_dock import OpticsResultsDock

        dock = OpticsResultsDock()
        try:
            dock.set_study(None)
            assert "No study" in dock._title.text()
        finally:
            _dispose(dock)
