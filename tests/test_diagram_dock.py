# SPDX-License-Identifier: LGPL-2.1-or-later
"""Smoke tests for the Lapidary_Diagram dock widget (DESIGN.md section 8).

The dock is GUI code, but everything worth testing about it works offscreen:
whether it finds its gem, produces an SVG, debounces refreshes, and writes SVG
and PDF files. Following ``docs/dev-notes.md`` these are guarded on
*behaviour* (can a QApplication actually be created?) rather than on whether
``FreeCADGui`` imports — it always does, even headless.

Run under FreeCAD's bundled Python with ``QT_QPA_PLATFORM=offscreen`` set by
the fixture below.
"""

import os

import pytest

FreeCAD = pytest.importorskip("FreeCAD")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    """A QApplication, or skip the module if this build cannot make one."""
    pytest.importorskip("FreeCADGui")   # registers FreeCAD's PySide shim
    try:
        from PySide import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    except Exception as err:            # no Qt platform plugin available
        pytest.skip("cannot create a QApplication here: %s" % err)
    return app


def _dispose(dock):
    """Destroy a dock deterministically, *now*.

    ``deleteLater`` alone posts a DeferredDelete event that would sit in the
    queue until something spins the event loop — at worst QApplication
    teardown at interpreter exit, where destroying a Python-backed QWidget
    segfaults under FreeCADCmd (seen on CI). Flushing the event here keeps
    widget destruction inside the test that created the widget.
    """
    from PySide import QtCore, QtWidgets
    dock._detach()
    dock.close()
    dock.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.DeferredDelete)
    QtWidgets.QApplication.processEvents()


@pytest.fixture(scope="module")
def dock_and_gem(qt_app):
    from freecad.lapidary.faceting import diagram_dock

    from test_pipeline import build_srb

    doc = FreeCAD.newDocument("diagram_dock")
    dock = None
    try:
        gem, _stock, _tiers = build_srb(doc)
        dock = diagram_dock.DiagramDock()
        dock.set_gem(gem)
        yield dock, gem
    finally:
        if dock is not None:
            _dispose(dock)
        FreeCAD.closeDocument(doc.Name)


class TestDiagramDock:
    def test_builds_the_diagram_for_its_gem(self, dock_and_gem):
        dock, _gem = dock_and_gem
        assert dock._svg.startswith("<?xml")
        assert "Standard Round Brilliant" in dock._svg

    def test_page_size_matches_the_rendered_svg(self, dock_and_gem):
        """The PDF export sets its page from this, so the two must agree."""
        dock, _gem = dock_and_gem
        width, height = dock._size_mm
        assert 'width="%gmm"' % width in dock._svg
        assert 'height="%gmm"' % height in dock._svg

    def test_options_change_the_output(self, dock_and_gem):
        dock, _gem = dock_and_gem
        assert '<g id="view-elevation">' in dock._svg
        dock._elevation_box.setChecked(False)       # triggers refresh
        assert '<g id="view-elevation">' not in dock._svg
        dock._elevation_box.setChecked(True)
        assert '<g id="view-elevation">' in dock._svg

        dock._label_box.setCurrentIndex(1)          # names and angles
        assert "40.68°" in dock._svg
        dock._label_box.setCurrentIndex(0)

    def test_letter_page_option(self, dock_and_gem):
        dock, _gem = dock_and_gem
        dock._page_box.setCurrentIndex(1)
        assert 'width="215.9mm"' in dock._svg
        assert dock._size_mm[0] == pytest.approx(215.9)
        dock._page_box.setCurrentIndex(0)
        assert 'width="210mm"' in dock._svg

    def test_refresh_is_debounced(self, dock_and_gem):
        """A burst of recompute notifications must coalesce into one redraw:
        regeneration re-projects the whole B-Rep."""
        dock, _gem = dock_and_gem
        dock.setVisible(True)
        try:
            for _ in range(5):
                dock.schedule_refresh()
            assert dock._timer.isActive()           # queued, not yet run
            assert dock._timer.isSingleShot()
        finally:
            dock.setVisible(False)
        dock._timer.stop()

    def test_hidden_dock_does_not_schedule_work(self, dock_and_gem):
        dock, _gem = dock_and_gem
        dock.setVisible(False)
        dock._timer.stop()
        dock.schedule_refresh()
        assert not dock._timer.isActive()

    def test_falls_back_to_the_documents_single_gem(self, dock_and_gem):
        dock, gem = dock_and_gem
        dock.set_gem(None)
        assert dock._target_gem() is gem            # the only gem in the doc
        dock.set_gem(gem)

    def test_reports_a_gem_without_geometry(self, qt_app):
        from freecad.lapidary.faceting import diagram_dock, gem_feature

        doc = FreeCAD.newDocument("dock_empty")
        dock = None
        try:
            gem = gem_feature.make_gem(doc, label="Empty")
            dock = diagram_dock.DiagramDock()
            dock.set_gem(gem)
            assert dock._svg == ""
            assert "no solid geometry" in dock._status.text()
        finally:
            if dock is not None:
                _dispose(dock)
            FreeCAD.closeDocument(doc.Name)

    def test_detach_removes_the_document_observer(self, qt_app):
        from freecad.lapidary.faceting import diagram_dock

        dock = diagram_dock.DiagramDock()
        assert dock._observer is not None
        dock._detach()
        assert dock._observer is None
        dock._detach()          # idempotent
        _dispose(dock)


class TestExport:
    def test_exports_svg(self, dock_and_gem, tmp_path):
        dock, _gem = dock_and_gem
        path = tmp_path / "diagram.svg"
        path.write_text(dock._svg, encoding="utf-8")
        assert path.read_text(encoding="utf-8").startswith("<?xml")

    def test_writes_a_pdf_at_true_size(self, dock_and_gem, tmp_path):
        from freecad.lapidary.faceting import diagram_dock

        dock, _gem = dock_and_gem
        path = tmp_path / "diagram.pdf"
        diagram_dock.write_pdf(dock._svg, dock._size_mm, str(path))
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        assert len(data) > 2000            # real content, not an empty page
