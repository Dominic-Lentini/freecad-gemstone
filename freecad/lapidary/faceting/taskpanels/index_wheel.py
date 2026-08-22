# SPDX-License-Identifier: LGPL-2.1-or-later
"""Clickable index-wheel widget (DESIGN.md section 4, item 2).

A circular index-gear diagram: one tick per tooth, index 0/N at 12 o'clock,
numbers increasing in the gear's handedness direction (counter-clockwise for
the GemCad convention, dir = +1, as resolved in the Phase 2 format notes).
Clicking a tooth toggles it; the current selection is exposed as a sorted
integer list (0 normalized to N, matching faceting.indexspec).

**Radial symmetry** (final-polish addition, KSP-ship-editor style): the
round button in the wheel's hub cycles through the symmetry folds the gear
supports — none, then every fold of 2..9 that divides the gear evenly
(``indexspec.symmetry_folds``; a non-divisor fold would land between
teeth). With a fold active, clicking a tooth toggles its whole symmetric
orbit at once, and the wheel shades the fold's sectors with alternating
contrast wedges running from the hub boundary out to just short of the
number labels. Text typed into the panel's index field is closed under the
same symmetry by the panel.
"""

import math

from PySide import QtCore, QtGui, QtWidgets

from freecad.lapidary.core.gemmath import DEFAULT_HANDEDNESS
from freecad.lapidary.faceting.indexspec import (
    mirror_indices, symmetry_folds, symmetry_orbit, symmetry_regions)

#: Radius of the central symmetry-toggle button, px.
_HUB_RADIUS = 24.0
#: Gap between the wedge shading's outer edge and the number labels, px.
_WEDGE_LABEL_GAP = 8.0


class IndexWheelWidget(QtWidgets.QWidget):
    """Circular gear diagram; clicking teeth toggles them (symmetrically
    when a symmetry fold is active)."""

    indicesChanged = QtCore.Signal()
    symmetryChanged = QtCore.Signal(int)

    def __init__(self, gear=96, handedness=DEFAULT_HANDEDNESS, parent=None):
        super().__init__(parent)
        self._gear = int(gear)
        self._handedness = -1 if int(handedness) < 0 else 1
        self._selected = set()
        self._symmetry = 1
        self.setMinimumSize(230, 230)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)
        self.setToolTip(
            "Click teeth to toggle them.\n"
            "Index 0/%d is at 12 o'clock.\n"
            "The hub button cycles radial symmetry (right-click cycles back); with a fold active, "
            "each click toggles the whole symmetric set." % self._gear)

    # -- model ---------------------------------------------------------------

    def gear(self):
        return self._gear

    def setGear(self, gear):
        gear = max(1, int(gear))
        if gear != self._gear:
            self._gear = gear
            self._selected = {i for i in self._selected if i <= gear}
            if self._symmetry not in symmetry_folds(gear):
                self._symmetry = 1
                self.symmetryChanged.emit(1)
            self.update()

    def setHandedness(self, handedness):
        value = -1 if int(handedness) < 0 else 1
        if value != self._handedness:
            self._handedness = value
            self.update()

    def indices(self):
        return sorted(self._selected)

    def setIndices(self, indices):
        normalized = set()
        for i in indices:
            wrapped = int(i) % self._gear
            normalized.add(self._gear if wrapped == 0 else wrapped)
        if normalized != self._selected:
            self._selected = normalized
            self.update()

    def symmetry(self):
        """The active fold: 1 = none."""
        return self._symmetry

    def setSymmetry(self, fold):
        fold = int(fold)
        if fold not in symmetry_folds(self._gear):
            fold = 1
        if fold != self._symmetry:
            self._symmetry = fold
            self.symmetryChanged.emit(fold)
            self.update()

    def cycleSymmetry(self, step=1):
        folds = symmetry_folds(self._gear)
        here = folds.index(self._symmetry) if self._symmetry in folds else 0
        self.setSymmetry(folds[(here + step) % len(folds)])

    def mirrorIndices(self, axis):
        """Union the selection with its mirror image across a wheel axis.

        ``axis="ns"`` mirrors across the vertical north-south axis
        (copying each selected tooth to its east-west counterpart,
        t -> N - t); ``axis="ew"`` mirrors across the horizontal
        east-west axis (copying north to south and back,
        t -> N/2 - t). Both are pure unions, so mirroring is the same
        operation whichever side holds the pattern. On an odd gear the
        east-west mirror lands between teeth and snaps to the nearest
        one, the same compromise as a non-divisor symmetry fold. The
        mapping is handedness-independent: flipping the count direction
        flips both the tooth and its image."""
        mirrored = set(mirror_indices(
            self._selected, self._gear, axis))
        if not mirrored <= self._selected:
            self._selected |= mirrored
            self.update()
            self.indicesChanged.emit()

    # -- geometry ------------------------------------------------------------

    def _center_radius(self):
        w, h = self.width(), self.height()
        return QtCore.QPointF(w / 2.0, h / 2.0), min(w, h) / 2.0 - 18.0

    def _tooth_angle(self, index):
        """Screen position angle of a tooth, radians from 12 o'clock, screen
        clockwise positive. Handedness -1 (GemCad) counts clockwise."""
        turn = 2.0 * math.pi * (index % self._gear) / self._gear
        return turn if self._handedness == -1 else -turn

    def _tooth_pos(self, index, radius, center):
        a = self._tooth_angle(index)
        return QtCore.QPointF(center.x() + radius * math.sin(a),
                              center.y() - radius * math.cos(a))

    def _index_at(self, pos):
        center, _radius = self._center_radius()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        if math.hypot(dx, dy) < _HUB_RADIUS:
            return None
        screen = math.atan2(dx, -dy)  # 0 at 12 o'clock, clockwise positive
        turn = screen if self._handedness == -1 else -screen
        index = int(round(turn / (2.0 * math.pi) * self._gear)) % self._gear
        return self._gear if index == 0 else index

    def _in_hub(self, pos):
        center, _radius = self._center_radius()
        return math.hypot(pos.x() - center.x(),
                          pos.y() - center.y()) < _HUB_RADIUS

    # -- events --------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._in_hub(event.pos()):
            # Left click cycles the fold up, right click back down.
            self.cycleSymmetry(
                -1 if event.button() == QtCore.Qt.RightButton else 1)
            super().mousePressEvent(event)
            return
        index = self._index_at(event.pos())
        if index is not None:
            orbit = set(symmetry_orbit(index, self._gear, self._symmetry))
            if index in self._selected:
                self._selected -= orbit
            else:
                self._selected |= orbit
            self.update()
            self.indicesChanged.emit()
        super().mousePressEvent(event)

    # -- painting ------------------------------------------------------------

    def _draw_symmetry_wedges(self, painter, center, radius):
        """Alternating contrast regions for the active fold, from the hub
        boundary out to just short of the number labels.

        The region count comes from ``indexspec.symmetry_regions``: an
        even fold takes ``fold`` regions (alternate poles shaded), an odd
        fold takes ``2 * fold`` (every pole shaded, the gaps light).
        Alternating shading only closes around a circle over an even
        count, so an odd fold drawn in ``fold`` regions butts two shaded
        wedges together at the wrap-around and misreads as a different
        symmetry.
        """
        regions = symmetry_regions(self._symmetry)
        if regions < 2:
            return
        outer = radius - 16.0 - _WEDGE_LABEL_GAP   # labels sit at r - 16
        if outer <= _HUB_RADIUS:
            return
        shade = self.palette().color(QtGui.QPalette.WindowText)
        rect_outer = QtCore.QRectF(center.x() - outer, center.y() - outer,
                                   2 * outer, 2 * outer)
        rect_hub = QtCore.QRectF(
            center.x() - _HUB_RADIUS, center.y() - _HUB_RADIUS,
            2 * _HUB_RADIUS, 2 * _HUB_RADIUS)
        span_deg = 360.0 / regions
        signed_span = span_deg if self._handedness == -1 else -span_deg
        painter.setPen(QtCore.Qt.NoPen)
        for k in range(regions):
            # Centre region 0 on tooth 0: start half a region "before" it,
            # counting in the gear's own direction, so a shaded region
            # always sits on a symmetry pole.
            start_screen = math.degrees(self._tooth_angle(0)) \
                + (k - 0.5) * signed_span
            color = QtGui.QColor(shade)
            color.setAlpha(26 if k % 2 == 0 else 10)
            path = QtGui.QPainterPath()
            # Qt angles: degrees counter-clockwise from 3 o'clock; screen
            # angle t (clockwise from 12 o'clock) maps to 90 - t.
            qt_start = 90.0 - start_screen
            qt_span = -signed_span
            path.arcMoveTo(rect_outer, qt_start)
            path.arcTo(rect_outer, qt_start, qt_span)
            path.arcTo(rect_hub, qt_start + qt_span, -qt_span)
            path.closeSubpath()
            painter.fillPath(path, color)

    def _draw_hub(self, painter, center):
        palette = self.palette()
        fg = palette.color(QtGui.QPalette.WindowText)
        accent = palette.color(QtGui.QPalette.Highlight)
        active = self._symmetry >= 2
        painter.setPen(QtGui.QPen(accent if active else fg,
                                  2.0 if active else 1.2))
        fill = palette.color(QtGui.QPalette.Button)
        painter.setBrush(fill)
        painter.drawEllipse(center, _HUB_RADIUS - 2.0, _HUB_RADIUS - 2.0)
        painter.setBrush(QtCore.Qt.NoBrush)
        label = "%d\N{MULTIPLICATION SIGN}" % self._symmetry \
            if active else "1\N{MULTIPLICATION SIGN}"
        font = painter.font()
        font.setBold(active)
        painter.setFont(font)
        painter.setPen(QtGui.QPen(accent if active else fg, 1))
        metrics = QtGui.QFontMetricsF(font)
        rect = metrics.boundingRect(label)
        painter.drawText(QtCore.QPointF(center.x() - rect.width() / 2.0,
                                        center.y() + rect.height() / 3.0),
                         label)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        palette = self.palette()
        fg = palette.color(QtGui.QPalette.WindowText)
        accent = palette.color(QtGui.QPalette.Highlight)
        center, radius = self._center_radius()

        self._draw_symmetry_wedges(painter, center, radius)

        painter.setPen(QtGui.QPen(fg, 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

        label_every = max(1, self._gear // 12)
        font = painter.font()
        font.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
        painter.setFont(font)
        metrics = QtGui.QFontMetricsF(font)

        for i in range(1, self._gear + 1):
            major = i % label_every == 0
            inner = radius - (7.0 if major else 4.0)
            p_out = self._tooth_pos(i, radius, center)
            p_in = self._tooth_pos(i, inner, center)
            selected = i in self._selected
            pen = QtGui.QPen(accent if selected else fg,
                             2.5 if selected else 1.0)
            painter.setPen(pen)
            painter.drawLine(p_in, p_out)
            if selected:
                painter.setBrush(accent)
                painter.drawEllipse(self._tooth_pos(i, radius + 5.0, center),
                                    3.0, 3.0)
                painter.setBrush(QtCore.Qt.NoBrush)
            if major:
                painter.setPen(QtGui.QPen(fg, 1))
                p_text = self._tooth_pos(i, radius - 16.0, center)
                text = str(i)
                rect = metrics.boundingRect(text)
                painter.drawText(QtCore.QPointF(
                    p_text.x() - rect.width() / 2.0,
                    p_text.y() + rect.height() / 3.0), text)

        self._draw_hub(painter, center)
        painter.end()
