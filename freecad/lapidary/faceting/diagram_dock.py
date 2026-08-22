# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Lapidary_Diagram dock widget (DESIGN.md section 8).

A dockable live preview of the faceting diagram, plus SVG and PDF export.
The panel does no drawing of its own: it asks
:mod:`freecad.lapidary.faceting.diagram` for an SVG string and hands it to
Qt's renderer, exactly as DESIGN.md section 8 specifies ("the dock widget just
displays the SVG").

Live update: a FreeCAD document observer catches recomputes and restarts a
short single-shot timer, so a burst of changes (dragging a spinbox in the
FacetTier panel, or a reorder that recomputes a whole tail of tiers) redraws
once when it settles rather than once per recompute. Regeneration re-projects
the B-Rep, so it is worth debouncing.

GUI-only module: imported from the command, never from headless code.
"""

import os

import FreeCAD
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

try:  # FreeCAD's PySide shim does not always re-export the SVG modules.
    from PySide.QtSvg import QSvgRenderer
except ImportError:
    from PySide6.QtSvg import QSvgRenderer

from freecad.lapidary.faceting import diagram as diagram_pkg
from freecad.lapidary.faceting import gem_feature

__all__ = ["DiagramDock", "show_diagram_dock", "write_pdf"]

OBJECT_NAME = "LapidaryDiagramDock"

#: Redraw this long after the last recompute (milliseconds).
REFRESH_DELAY_MS = 250

PAGE_STYLES = [("A4 portrait", diagram_pkg.A4_PORTRAIT),
               ("Letter portrait", diagram_pkg.LETTER_PORTRAIT)]

LABEL_STYLES = [("Tier names (GemCad style)", diagram_pkg.LabelStyle.NAME),
                ("Names and angles", diagram_pkg.LabelStyle.NAME_ANGLE)]


def write_pdf(svg_text, size_mm, path):
    """Write an SVG string to a single-page PDF at its true millimetre size."""
    renderer = QSvgRenderer(QtCore.QByteArray(svg_text.encode("utf-8")))
    writer = QtGui.QPdfWriter(path)
    writer.setPageSize(QtGui.QPageSize(
        QtCore.QSizeF(size_mm[0], size_mm[1]), QtGui.QPageSize.Millimeter))
    writer.setPageMargins(QtCore.QMarginsF(0.0, 0.0, 0.0, 0.0))
    painter = QtGui.QPainter(writer)
    try:
        renderer.render(painter)
    finally:
        painter.end()


class _SvgCanvas(QtWidgets.QWidget):
    """Paints one SVG page, scaled to a chosen fraction of the viewport."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = QSvgRenderer()
        self._aspect = 210.0 / 297.0
        self._zoom = 1.0
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                           QtWidgets.QSizePolicy.Fixed)

    def set_svg(self, text, size_mm):
        self._renderer.load(QtCore.QByteArray(text.encode("utf-8")))
        if size_mm and size_mm[1]:
            self._aspect = float(size_mm[0]) / float(size_mm[1])
        self.relayout()

    def set_zoom(self, zoom):
        self._zoom = max(0.1, float(zoom))
        self.relayout()

    def relayout(self):
        """Size the page to the available width (times the zoom factor)."""
        viewport = self.parentWidget()
        available = viewport.width() - 4 if viewport is not None else 600
        width = max(80, int(available * self._zoom))
        self.setFixedSize(width, int(width / self._aspect) if self._aspect
                          else width)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        if self._renderer.isValid():
            self._renderer.render(painter, QtCore.QRectF(self.rect()))
        painter.end()


class _RecomputeObserver:
    """Bridges FreeCAD's document notifications to the dock's debounce timer.

    Kept deliberately dumb: it never touches Qt widgets directly, only asks
    the dock to schedule a refresh, so a notification arriving while the dock
    is being torn down cannot paint into a dead widget.
    """

    def __init__(self, dock):
        self.dock = dock

    def slotRecomputedDocument(self, _doc):
        self.dock.schedule_refresh()

    def slotDeletedDocument(self, _doc):
        self.dock.schedule_refresh()

    def slotActivateDocument(self, _doc):
        self.dock.schedule_refresh()

    def slotDeletedObject(self, _obj):
        self.dock.schedule_refresh()


class DiagramDock(QtWidgets.QDockWidget):
    """Live faceting-diagram preview with SVG and PDF export."""

    def __init__(self, parent=None):
        super().__init__("Faceting Diagram", parent)
        self.setObjectName(OBJECT_NAME)
        self._gem = None
        self._svg = ""
        self._size_mm = (210.0, 297.0)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)

        self.setWidget(self._build_body())

        self._observer = None
        self._attach()

    # -- construction ----------------------------------------------------

    def _build_body(self):
        body = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(self._build_toolbar())

        self._status = QtWidgets.QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._scroll = QtWidgets.QScrollArea(body)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self._canvas = _SvgCanvas(self._scroll)
        self._scroll.setWidget(self._canvas)
        layout.addWidget(self._scroll, 1)
        return body

    def _build_toolbar(self):
        row = QtWidgets.QHBoxLayout()

        self._page_box = QtWidgets.QComboBox()
        for label, _style in PAGE_STYLES:
            self._page_box.addItem(label)
        self._page_box.setToolTip("Page size of the generated diagram")
        self._page_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self._page_box)

        self._label_box = QtWidgets.QComboBox()
        for label, _style in LABEL_STYLES:
            self._label_box.addItem(label)
        self._label_box.setToolTip("How much each tier's in-view label says")
        self._label_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self._label_box)

        self._elevation_box = QtWidgets.QCheckBox("Elevation")
        self._elevation_box.setChecked(True)
        self._elevation_box.setToolTip("Include the side elevation panel")
        self._elevation_box.toggled.connect(self.refresh)
        row.addWidget(self._elevation_box)

        self._optics_box = QtWidgets.QCheckBox("Optics tint")
        self._optics_box.setChecked(False)
        self._optics_box.setToolTip(
            "Tint each facet by its tier's light-return share from the "
            "gem's fresh optics study (Phase 4b overlay); off = the plain "
            "printable diagram")
        self._optics_box.toggled.connect(self.refresh)
        row.addWidget(self._optics_box)

        self._zoom_box = QtWidgets.QSpinBox()
        self._zoom_box.setRange(25, 400)
        self._zoom_box.setValue(100)
        self._zoom_box.setSuffix(" %")
        self._zoom_box.setToolTip("Preview zoom (100 % fits the panel width)")
        self._zoom_box.valueChanged.connect(
            lambda value: self._canvas.set_zoom(value / 100.0))
        row.addWidget(self._zoom_box)

        row.addStretch(1)
        svg_button = QtWidgets.QPushButton("Export SVG…")
        svg_button.clicked.connect(self.export_svg)
        row.addWidget(svg_button)
        pdf_button = QtWidgets.QPushButton("Export PDF…")
        pdf_button.clicked.connect(self.export_pdf)
        row.addWidget(pdf_button)
        return row

    # -- state -----------------------------------------------------------

    def _page_style(self):
        return PAGE_STYLES[max(0, self._page_box.currentIndex())][1]

    def _label_style(self):
        return LABEL_STYLES[max(0, self._label_box.currentIndex())][1]

    def set_gem(self, gem):
        """Pin the dock to a Gem (None = follow the active document)."""
        self._gem = gem
        self.refresh()

    def _target_gem(self):
        """The pinned gem if it is still alive, else the active document's
        single gem."""
        gem = self._gem
        if gem is not None:
            try:
                if gem.Document is not None and not gem.Removing:
                    return gem
            except (ReferenceError, AttributeError):
                pass       # the document or the object went away
            self._gem = None
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        gems = [obj for obj in doc.Objects if gem_feature.is_gem(obj)]
        return gems[0] if len(gems) == 1 else None

    # -- refresh ---------------------------------------------------------

    def schedule_refresh(self):
        """Ask for a redraw once the document settles (debounced)."""
        if not self.isVisible():
            return
        self._timer.start()

    def refresh(self):
        self._timer.stop()
        gem = self._target_gem()
        if gem is None:
            self._show_message(
                "Select a Gem to diagram, or create one with New Gem.")
            return
        try:
            diagram = diagram_pkg.build_diagram(
                gem, include_elevation=self._elevation_box.isChecked(),
                label_style=self._label_style())
        except Exception as err:      # never let a preview break the session
            FreeCAD.Console.PrintError(
                "Lapidary: could not build the diagram for %s: %s\n"
                % (gem.Label, err))
            self._show_message("Could not build the diagram; see the report "
                               "view.")
            return
        if diagram is None:
            self._show_message(
                "%s has no solid geometry to diagram yet." % gem.Label)
            return

        tier_tint = None
        if self._optics_box.isChecked():
            try:
                from freecad.lapidary.optics.overlay import tier_tint_for_gem
                tier_tint = tier_tint_for_gem(gem) or None
            except Exception as err:
                FreeCAD.Console.PrintWarning(
                    "Lapidary: optics overlay unavailable: %s\n" % err)
            if tier_tint is None:
                FreeCAD.Console.PrintWarning(
                    "Lapidary: no fresh optics study for %s — showing the "
                    "plain diagram.\n" % gem.Label)

        style = self._page_style()
        self._svg = diagram_pkg.render_svg(diagram, style=style,
                                           tier_tint=tier_tint)
        self._size_mm = diagram_pkg.page_size_mm(diagram, style=style)
        self._status.setText("")
        self._status.hide()
        self._canvas.set_svg(self._svg, self._size_mm)

    def _show_message(self, text):
        self._svg = ""
        self._status.setText(text)
        self._status.show()
        self._canvas.set_svg("", None)

    # -- export ----------------------------------------------------------

    def _default_path(self, extension):
        gem = self._target_gem()
        stem = (gem.DesignName or gem.Label) if gem is not None else "diagram"
        return os.path.join(os.path.expanduser("~"), stem + extension)

    def _require_svg(self):
        if not self._svg:
            FreeCAD.Console.PrintWarning(
                "Lapidary: there is no diagram to export yet.\n")
            return False
        return True

    def export_svg(self):
        if not self._require_svg():
            return
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export faceting diagram", self._default_path(".svg"),
            "SVG files (*.svg)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(self._svg)
        FreeCAD.Console.PrintMessage(
            "Lapidary: diagram written to %s\n" % path)

    def export_pdf(self):
        if not self._require_svg():
            return
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export faceting diagram", self._default_path(".pdf"),
            "PDF files (*.pdf)")
        if not path:
            return
        write_pdf(self._svg, self._size_mm, path)
        FreeCAD.Console.PrintMessage(
            "Lapidary: diagram written to %s\n" % path)

    # -- Qt events -------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._canvas.relayout()

    def showEvent(self, event):
        # Closing a QDockWidget with the window controls *hides* it rather
        # than deleting it, and show_diagram_dock() reuses the hidden
        # instance — so the observer detached by closeEvent must come back
        # here or a reopened dock would render once and never live-update.
        self._attach()
        super().showEvent(event)
        self.refresh()

    def closeEvent(self, event):
        self._detach()
        super().closeEvent(event)

    def _attach(self):
        """Register the document observer (idempotent)."""
        if self._observer is None:
            self._observer = _RecomputeObserver(self)
            FreeCAD.addDocumentObserver(self._observer)

    def _detach(self):
        self._timer.stop()
        if self._observer is not None:
            try:
                FreeCAD.removeDocumentObserver(self._observer)
            except Exception:
                pass
            self._observer = None


def show_diagram_dock(gem=None):
    """Show (creating or reusing) the diagram dock, pinned to ``gem``."""
    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, OBJECT_NAME)
    if dock is None:
        dock = DiagramDock(main_window)
        main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()
    dock.set_gem(gem)
    return dock
