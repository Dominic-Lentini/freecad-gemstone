# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lapidary_FacetTier task panel (DESIGN.md section 4, item 2).

Side toggle (Crown/Pavilion), angle and cut-depth spinboxes, and index entry
in three synchronized forms: comma list (``3,21,27,45``), symmetric
shorthand (``96/8`` = every 12th tooth), and the clickable index-wheel
widget with its KSP-style radial-symmetry hub, plus rotate-pattern buttons
and a copy button that takes the index list from an earlier tier.

When the panel opens the 3D view moves to the **front view** (it no longer
flips with the side toggle), with the origin axes shown and a highlighted
radial line on the stock at the pattern's starting azimuth.

Cut depth and the **girdle height** are interchangeable inputs. The
height is where this tier's facet lands on the girdle line — the z at
which its plane crosses the girdle radius, positive above the girdle
plane and negative below — so crown height, pavilion depth and girdle
thickness can be designed against directly instead of reading a
normal-direction number. A 90° tier has no single such height, so the
box edits its radial plane distance there and the row label says so.
Editing either box rederives the other; the stored ``Distance`` property
is untouched and remains the DESIGN.md §2.1 plane distance that .ASC
interchange, ownership matching and the reports speak.

**Auto** replaces the earlier Pick and Meet buttons with one
selection-driven flow. It never fires on the dialled angle alone — the
picked element decides what happens (consume an existing selection, or
arm Selecting… and wait), validated against the stone's own girdle band
(see :meth:`FacetTierPanel._side_ok`):

  - **the stone's topmost vertex, Crown side**: dials the angle to 0
    and takes the shallowest depth that forms a table meet;
  - **any other vertex**: the index pattern rotates in the handedness
    direction onto the vertex's azimuth; depth = the shallowest value
    whose plane reaches the point (an on-axis vertex skips the
    rotation);
  - **edge**: same rotation onto the edge's azimuth; depth = the lowest
    value that removes the whole edge;
  - **facet**: angle, index and cut depth re-cut exactly that facet;
  - **girdle-parallel face** (vertical facet or the rough's wall):
    dials the angle to 90, copies the first patterned tier's indices
    (or keeps this tier's own on bare stock) and takes the minimum
    depth at which the chords close to a point around the stone;
  - **the working side's flat face**: the lowest depth at which every
    facet meets at the axis point ``(0, 0, z)`` of that face
    (:func:`~..tier_feature.auto_axis_depth`).

The dialled angle is only ever changed by a selection (topmost vertex,
girdle-parallel face, or matching a facet), never by the button itself.

The Auto calculations read the *actual current geometry* (real face and
vertex coordinates of the base solid), so a stone whose z-extent has
shifted after earlier tiers is measured as it is — no re-centering is
needed, and the modelling convention (facet planes referenced to the
document origin) is untouched.

**Live preview**, in two modes chosen by the *Cut preview* toggle:

* **outline** (default): the tier is *suppressed* — the 3D view shows
  the uncut stone — and the pending cut is drawn as an overlay: each
  facet plane clipped to the stone, a very faint fill with a sharp
  outline where the plane meets the surface (the saw kerf);
* **finished cut**: the tier is unsuppressed so the real cut geometry
  is what you see, and the kerf outline is hidden while the planes are
  in bounds.

Either way, planes that miss the stone are drawn as a floating patch
one girdle-width across, so an out-of-bounds cut reads as "out here"
without swamping the view. OK/Apply commit the tier and refresh the
real geometry; Cancel aborts the transaction.
"""

import math

import FreeCAD
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.lapidary.core import gemmath
from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.faceting.indexspec import (
    IndexSpecError, expand_symmetric, format_indices, parse_index_spec,
    rotate_indices)
from freecad.lapidary.faceting.taskpanels.index_wheel import IndexWheelWidget
from freecad.lapidary.faceting.tier_feature import (
    align_indices_to_azimuth, align_indices_to_index, auto_axis_depth,
    depth_through_point,
    depth_to_remove_edge, effective_gear, effective_normals,
    distance_for_girdle_height, face_tier_parameters, girdle_band,
    girdle_line_height, girdle_metrics, girdle_pattern_indices,
    is_girdle_face, meetpoint_depths, reference_distance)

#: A selected element must lie this far onto the working side (mm slack).
_SIDE_TOL = 1e-4


class _AzimuthMarker:
    """A highlighted radial line in the 3D view showing the starting azimuth
    of the tier's index pattern on the stock. Fails soft when no 3D view is
    available (e.g. offscreen smoke tests)."""

    def __init__(self):
        self._root = None
        self._coords = None
        self._scenegraph = None

    def attach(self):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            self._scenegraph = view.getSceneGraph()
            self._root = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = (1.0, 0.55, 0.0)
            style = coin.SoDrawStyle()
            style.lineWidth = 4
            self._coords = coin.SoCoordinate3()
            line = coin.SoLineSet()
            line.numVertices.setValue(2)
            self._root.addChild(color)
            self._root.addChild(style)
            self._root.addChild(self._coords)
            self._root.addChild(line)
            self._scenegraph.addChild(self._root)
        except Exception:
            self._root = None

    def update(self, azimuth_deg, length):
        if self._root is None or self._coords is None:
            return
        a = math.radians(azimuth_deg)
        x, y = length * math.cos(a), length * math.sin(a)
        self._coords.point.setValues(0, 2, [(0.0, 0.0, 0.0), (x, y, 0.0)])

    def detach(self):
        if self._root is not None and self._scenegraph is not None:
            try:
                self._scenegraph.removeChild(self._root)
            except Exception:
                pass
        self._root = None
        self._coords = None
        self._scenegraph = None


class _CutPreview:
    """The pending cut as a pivy overlay: the kerf slices where the cut
    planes pass through the stone, or a girdle-width plane patch when
    they miss it. Fails soft when no 3D view is available."""

    def __init__(self):
        self._root = None
        self._scenegraph = None

    def _ensure_root(self):
        if self._root is not None:
            return True
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            self._scenegraph = view.getSceneGraph()
            self._root = coin.SoSeparator()
            self._scenegraph.addChild(self._root)
            return True
        except Exception:
            self._root = None
            self._scenegraph = None
            return False

    def _clear_children(self):
        if self._root is not None:
            self._root.removeAllChildren()

    def show_slices(self, faces):
        """The cut planes clipped to the stone, drawn as OUTLINE ONLY:
        the sharp closed curve where each plane meets the stone's
        surface — the saw kerf. No fill at all: with the patch covering
        the whole cross-section the slice boundary lies entirely on the
        stone's surface, so the outline is exactly the kerf and nothing
        crosses the interior."""
        if not self._ensure_root():
            return
        try:
            from pivy import coin
            self._clear_children()
            for face in faces:
                sep = coin.SoSeparator()
                # Sharp outline only: the slice's boundary wires (the
                # kerf curve on the stone's surface).
                style = coin.SoDrawStyle()
                style.lineWidth = 3.5
                outline_color = coin.SoBaseColor()
                outline_color.rgb = (0.1, 0.95, 0.25)
                sep.addChild(style)
                sep.addChild(outline_color)
                for wire in face.Wires:
                    points = []
                    for edge in wire.OrderedEdges:
                        count = max(2, int(edge.Length / 0.5) + 1)
                        points.extend(edge.discretize(Number=count))
                    if len(points) < 2:
                        continue
                    line_coords = coin.SoCoordinate3()
                    line_coords.point.setValues(
                        0, len(points) + 1,
                        [(p.x, p.y, p.z) for p in points]
                        + [(points[0].x, points[0].y, points[0].z)])
                    line = coin.SoLineSet()
                    line.numVertices.setValue(len(points) + 1)
                    sep.addChild(line_coords)
                    sep.addChild(line)
                self._root.addChild(sep)
        except Exception:
            self.detach()

    def show_plane(self, corners):
        """One facet plane as a green outlined translucent quad."""
        if not self._ensure_root():
            return
        try:
            from pivy import coin
            self._clear_children()
            sep = coin.SoSeparator()
            material = coin.SoMaterial()
            material.diffuseColor = (0.15, 0.85, 0.25)
            material.transparency = 0.75
            coords = coin.SoCoordinate3()
            coords.point.setValues(
                0, len(corners), [tuple(c) for c in corners])
            quad = coin.SoFaceSet()
            quad.numVertices.setValue(len(corners))
            style = coin.SoDrawStyle()
            style.lineWidth = 3
            outline_color = coin.SoBaseColor()
            outline_color.rgb = (0.1, 0.9, 0.2)
            outline = coin.SoLineSet()
            outline.numVertices.setValue(len(corners) + 1)
            outline_coords = coin.SoCoordinate3()
            outline_coords.point.setValues(
                0, len(corners) + 1,
                [tuple(c) for c in corners] + [tuple(corners[0])])
            sep.addChild(material)
            sep.addChild(coords)
            sep.addChild(quad)
            sep.addChild(style)
            sep.addChild(outline_color)
            sep.addChild(outline_coords)
            sep.addChild(outline)
            self._root.addChild(sep)
        except Exception:
            self.detach()

    def clear(self):
        self._clear_children()

    def detach(self):
        if self._root is not None and self._scenegraph is not None:
            try:
                self._scenegraph.removeChild(self._root)
            except Exception:
                pass
        self._root = None
        self._scenegraph = None


def _front_view():
    """Move the 3D view to the front view with the origin axes shown (the
    stable frame the panel now always opens in; the camera no longer
    follows the side toggle)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        view.viewFront()
        view.setAxisCross(True)
        view.fitAll()
    except Exception:
        pass


class _SelectionObserver:
    """One-shot selection observer for the Auto button's Select… mode."""

    def __init__(self, callback):
        self.callback = callback

    def addSelection(self, doc, obj_name, sub, pos):
        self.callback(doc, obj_name, sub, pos)


class FacetTierPanel:
    """Task panel editing one FacetTier object under a live transaction."""

    def __init__(self, tier, is_new):
        self.tier = tier
        self.is_new = is_new
        # A brand-new cut grazes the stone when the angle is dialled (the
        # reference boundary changes with the angle); once a depth has
        # been dialled — typed, scrolled, distance-set or Auto-aimed —
        # angle edits keep that depth instead of resetting the plane.
        self._graze_on_angle = is_new
        self.doc = tier.Document
        self._updating = False

        gem = gem_feature.find_gem(tier)
        self._handedness = gem_feature.gem_handedness(gem)

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Facet Tier" if is_new else
                                 "Edit %s" % tier.Label)
        layout = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit(tier.TierName)
        self.name_edit.setPlaceholderText("e.g. P1 mains, Girdle, Table")
        form.addRow("Tier name", self.name_edit)

        side_box = QtWidgets.QWidget()
        side_layout = QtWidgets.QHBoxLayout(side_box)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.crown_radio = QtWidgets.QRadioButton("Crown")
        self.pavilion_radio = QtWidgets.QRadioButton("Pavilion")
        side_layout.addWidget(self.crown_radio)
        side_layout.addWidget(self.pavilion_radio)
        side_layout.addStretch(1)
        (self.crown_radio if tier.WorkingSide == "Crown"
         else self.pavilion_radio).setChecked(True)
        form.addRow("Working side", side_box)

        self.angle_spin = QtWidgets.QDoubleSpinBox()
        self.angle_spin.setRange(0.0, 120.0)
        self.angle_spin.setDecimals(2)
        self.angle_spin.setSingleStep(0.5)
        self.angle_spin.setSuffix(" \N{DEGREE SIGN}")
        self.angle_spin.setValue(tier.Angle.Value)
        self.angle_spin.setToolTip("0\N{DEGREE SIGN} = table, "
                                   "90\N{DEGREE SIGN} = girdle")
        form.addRow("Angle", self.angle_spin)

        depth_box = QtWidgets.QWidget()
        depth_layout = QtWidgets.QHBoxLayout(depth_box)
        depth_layout.setContentsMargins(0, 0, 0, 0)
        self.depth_spin = QtWidgets.QDoubleSpinBox()
        # Negative depths are legal: they place the plane outside the
        # reference boundary (a deliberate no-op), and clamping them here
        # would corrupt a distance typed into the box below that happens to
        # lie beyond the reference.
        self.depth_spin.setRange(-10000.0, 10000.0)
        self.depth_spin.setDecimals(3)
        self.depth_spin.setSingleStep(0.05)
        self.depth_spin.setSuffix(" mm")
        self.depth_spin.setValue(tier.CutDepth.Value)
        self.depth_spin.setToolTip(
            "Cut depth, measured inward from the boundary of the solid this "
            "tier cuts (its longest remaining radius about the gem axis); "
            "0 just grazes what is left of the stone")
        depth_layout.addWidget(self.depth_spin, 1)
        self.auto_button = QtWidgets.QToolButton()
        self.auto_button.setText("Auto")
        self.auto_button.setCheckable(True)
        self.auto_button.setToolTip(
            "Set the depth from a selection. Pick before or after "
            "clicking: a vertex (plane through it, indices rotated onto "
            "it; the stone's topmost crown vertex dials the angle to "
            "0° and takes the table meet), an edge (lowest depth "
            "that removes it), a facet (re-cut it exactly), a "
            "girdle-parallel face (dials 90° and closes the girdle "
            "chords to a point), or the working side's flat face (close "
            "it to a point on the axis).")
        depth_layout.addWidget(self.auto_button)
        form.addRow("Cut depth", depth_box)

        # Interchangeable with the depth: the two are geometrically tied by
        # distance = reference - depth, so a user can rough out by depth and
        # switch to exact plane distances for the finer crown tiers (or when
        # re-editing tier heights later). Editing either box rederives the
        # other.
        self.distance_spin = QtWidgets.QDoubleSpinBox()
        # Heights below the girdle plane are negative (a pavilion tier),
        # so this box has to span both signs.
        self.distance_spin.setRange(-10000.0, 10000.0)
        self.distance_spin.setDecimals(3)
        self.distance_spin.setSingleStep(0.05)
        self.distance_spin.setSuffix(" mm")
        self.distance_spin.setValue(tier.Distance.Value)
        self.distance_spin.setToolTip(
            "Where this tier's facet lands on the girdle line: the height "
            "above (crown) or below (pavilion) the girdle plane at which "
            "the facet plane crosses the girdle radius — so the "
            "crown height, pavilion depth and girdle thickness can be "
            "designed against directly.\n"
            "Interchangeable with the cut depth: editing either updates "
            "the other. A 90° girdle tier has no single height, so "
            "the box edits its radial plane distance instead (the label "
            "follows).")
        self.height_label = QtWidgets.QLabel("Girdle height")
        form.addRow(self.height_label, self.distance_spin)

        self.result_check = QtWidgets.QCheckBox("Show the finished cut")
        self.result_check.setToolTip(
            "Off: the stone stays uncut and the pending cut is outlined "
            "where the planes pass through it (the kerf).\n"
            "On: the cut is applied live — the outline is hidden while "
            "the planes are in bounds and you see the finished result "
            "before committing.")
        self.result_check.toggled.connect(self._result_mode_changed)
        form.addRow("Cut preview", self.result_check)

        self.offset_spin = QtWidgets.QDoubleSpinBox()
        self.offset_spin.setRange(-16.0, 16.0)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setValue(tier.IndexOffset)
        self.offset_spin.setToolTip("Cheater: fractional index offset")
        form.addRow("Index offset", self.offset_spin)

        gear = effective_gear(tier)
        index_box = QtWidgets.QWidget()
        index_layout = QtWidgets.QHBoxLayout(index_box)
        index_layout.setContentsMargins(0, 0, 0, 0)
        self.index_edit = QtWidgets.QLineEdit(
            format_indices(list(tier.Indices), gear))
        self.index_edit.setPlaceholderText(
            "3,21,27,45  |  %d/8 (symmetric)  |  empty = table" % gear)
        index_layout.addWidget(self.index_edit, 1)
        self.rotate_back = QtWidgets.QToolButton()
        self.rotate_back.setText("\N{ANTICLOCKWISE OPEN CIRCLE ARROW}")
        self.rotate_back.setToolTip(
            "Rotate the whole pattern one tooth backward")
        self.rotate_forward = QtWidgets.QToolButton()
        self.rotate_forward.setText("\N{CLOCKWISE OPEN CIRCLE ARROW}")
        self.rotate_forward.setToolTip(
            "Rotate the whole pattern one tooth forward")
        index_layout.addWidget(self.rotate_back)
        index_layout.addWidget(self.rotate_forward)
        self.mirror_ns = QtWidgets.QToolButton()
        self.mirror_ns.setText("↔")
        self.mirror_ns.setToolTip(
            "Mirror across the north-south axis: copy every selected "
            "tooth to its east-west counterpart (the pattern keeps both "
            "sides)")
        self.mirror_ew = QtWidgets.QToolButton()
        self.mirror_ew.setText("↕")
        self.mirror_ew.setToolTip(
            "Mirror across the east-west axis: copy every selected "
            "tooth to its north-south counterpart (the pattern keeps "
            "both sides)")
        index_layout.addWidget(self.mirror_ns)
        index_layout.addWidget(self.mirror_ew)
        self.copy_button = QtWidgets.QToolButton()
        self.copy_button.setText("Copy\N{HORIZONTAL ELLIPSIS}")
        self.copy_button.setToolTip(
            "Copy the index list from an earlier tier of this gem")
        self.copy_button.setPopupMode(
            QtWidgets.QToolButton.InstantPopup)
        self._copy_menu = QtWidgets.QMenu(self.copy_button)
        self._copy_menu.aboutToShow.connect(self._fill_copy_menu)
        self.copy_button.setMenu(self._copy_menu)
        index_layout.addWidget(self.copy_button)
        # Breathing room: the index entry belongs with the wheel below it,
        # not with the numeric cut settings above.
        spacer = QtWidgets.QWidget()
        spacer.setFixedHeight(14)
        form.addRow(spacer)
        form.addRow("Indices", index_box)

        # Clear sits in the top-right of the wheel's area: emptying the
        # pattern by hand means remembering you can wipe the text box,
        # which people miss and start un-clicking teeth one at a time.
        clear_row = QtWidgets.QHBoxLayout()
        clear_row.setContentsMargins(0, 0, 0, 0)
        clear_row.addStretch(1)
        self.clear_button = QtWidgets.QToolButton()
        self.clear_button.setText("Clear")
        self.clear_button.setToolTip(
            "Clear the index list (an empty list means one axial facet — "
            "the table)")
        self.clear_button.clicked.connect(lambda: self._set_indices([]))
        clear_row.addWidget(self.clear_button)
        layout.addLayout(clear_row)

        self.wheel = IndexWheelWidget(gear, self._handedness)
        self.wheel.setIndices(list(tier.Indices))
        layout.addWidget(self.wheel, 1)

        # Live stone measurements: the figures a designer cuts against,
        # refreshed with the preview instead of waiting behind the Stone
        # Report command (the Gem carries the same numbers as read-only
        # properties, so they also show in the tree).
        self.stats_label = QtWidgets.QLabel("")
        self.stats_label.setWordWrap(True)
        self.stats_label.setToolTip(
            "Measurements of the stone as this tier currently cuts it, "
            "as percentages of the girdle width. The Gem object carries "
            "the same figures; Stone Report prints the full sheet.")
        layout.addWidget(self.stats_label)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Live preview wiring: any change -> apply to the object -> redraw
        # the pending-cut overlay (the tier itself stays suppressed).
        self.name_edit.editingFinished.connect(self._apply)
        self.crown_radio.toggled.connect(self._apply)
        # Spin edits debounce through a single-shot timer: a scroll
        # wheel or held arrow emits valueChanged for every transient
        # value, and recomputing the document per tick makes the wheel
        # feel glued down. Only the value at rest triggers the rebuild.
        self._apply_timer = QtCore.QTimer(self.form)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(200)
        self._apply_timer.timeout.connect(self._apply)
        self.angle_spin.valueChanged.connect(self._angle_edited)
        self.depth_spin.valueChanged.connect(self._depth_edited)
        self.distance_spin.valueChanged.connect(self._distance_edited)
        self.offset_spin.valueChanged.connect(self._apply_soon)
        self.index_edit.textEdited.connect(self._indices_from_text)
        self.rotate_back.clicked.connect(lambda: self._rotate_pattern(-1))
        self.rotate_forward.clicked.connect(lambda: self._rotate_pattern(+1))
        self.mirror_ns.clicked.connect(
            lambda: self.wheel.mirrorIndices("ns"))
        self.mirror_ew.clicked.connect(
            lambda: self.wheel.mirrorIndices("ew"))
        self.wheel.indicesChanged.connect(self._indices_from_wheel)
        self.wheel.symmetryChanged.connect(self._symmetry_changed)
        self.auto_button.toggled.connect(self._auto_toggled)

        self._select_observer = None

        # While the panel is open the tier is suppressed: the 3D view shows
        # the uncut base solid and the pending cut is drawn as the green
        # overlay instead. OK/Apply restore (and so cut) it.
        self._entered_suppressed = tier.Suppressed
        tier.Suppressed = True

        self._marker = _AzimuthMarker()
        self._marker.attach()
        self._preview = _CutPreview()
        _front_view()
        self._apply()

    # -- index entry synchronization ----------------------------------------

    def _gear(self):
        return effective_gear(self.tier)

    def _indices_from_text(self):
        if self._updating:
            return
        try:
            indices = parse_index_spec(self.index_edit.text(), self._gear())
        except IndexSpecError as err:
            self.index_edit.setStyleSheet(
                "QLineEdit { border: 1px solid red; }")
            self.status_label.setText(str(err))
            return
        # With a symmetry fold active, text entry is symmetric too: the
        # typed teeth are closed under the fold (the wheel shows the full
        # set; the text is left as typed while the user is typing).
        if self.wheel.symmetry() > 1:
            indices = expand_symmetric(indices, self._gear(),
                                       self.wheel.symmetry())
        self.index_edit.setStyleSheet("")
        self._updating = True
        try:
            self.wheel.setIndices(indices)
        finally:
            self._updating = False
        self._apply()

    def _indices_from_wheel(self):
        if self._updating:
            return
        self._updating = True
        try:
            self.index_edit.setStyleSheet("")
            self.index_edit.setText(
                format_indices(self.wheel.indices(), self._gear()))
        finally:
            self._updating = False
        self._apply()

    def _result_mode_changed(self, _checked):
        """Cut preview off = outline the kerf on the uncut stone; on =
        apply the cut live and show the finished result."""
        self._sync_suppression()
        self._apply()

    def _sync_suppression(self):
        """The tier is suppressed exactly while the outline preview is
        showing; the finished-cut preview unsuppresses it so the real
        geometry is what the user sees."""
        want = not self.result_check.isChecked()
        if self.tier.Suppressed != want:
            self.tier.Suppressed = want
            try:
                self.doc.recompute()
            except Exception:
                pass

    def _angle_edited(self, _value):
        """On a *new* cut (no depth dialled yet) an angle edit moves the
        plane to the new angle's reference boundary (depth 0, grazing
        the stone) so the plane never lands arbitrarily deep. Once the
        user has dialled a depth — typed, scrolled, distance-set or
        Auto-aimed — the operation is underway and angle edits keep that
        depth, swinging the existing plane instead of resetting it."""
        if self._updating:
            return
        if self._graze_on_angle:
            self._updating = True
            try:
                self.depth_spin.setValue(0.0)
            finally:
                self._updating = False
        self._apply_soon()

    def _depth_edited(self, _value):
        if self._updating:
            return
        self._graze_on_angle = False   # a dialled depth starts the operation
        self._apply_soon()

    def _symmetry_changed(self, fold):
        self.status_label.setText(
            "Radial symmetry off." if fold < 2 else
            "%d-fold radial symmetry: clicks and typed indices toggle "
            "all %d symmetric teeth." % (fold, fold))

    def _rotate_pattern(self, teeth):
        indices = rotate_indices(self.wheel.indices(), self._gear(), teeth)
        self._set_indices(indices)

    def _fill_copy_menu(self):
        """Populate the copy-indices menu with the tiers *before* this one in
        the pipeline (later tiers cannot sensibly be a source while this tier
        is being cut)."""
        self._copy_menu.clear()
        gem = gem_feature.find_gem(self.tier)
        earlier = []
        if gem is not None:
            for feature in gem_feature.pipeline_features(gem):
                if feature == self.tier:
                    break
                if gem_feature.is_tier(feature):
                    earlier.append(feature)
        if not earlier:
            action = self._copy_menu.addAction("(no earlier tiers)")
            action.setEnabled(False)
            return
        for feature in earlier:
            indices = list(feature.Indices)
            summary = format_indices(indices, self._gear()) or "Table"
            if len(summary) > 28:
                summary = summary[:25] + "\N{HORIZONTAL ELLIPSIS}"
            action = self._copy_menu.addAction(
                "%s \N{EM DASH} %.2f\N{DEGREE SIGN} \N{EM DASH} %s"
                % (feature.TierName or feature.Label,
                   feature.Angle.Value, summary))
            action.triggered.connect(
                lambda checked=False, i=indices: self._set_indices(i))

    def _set_indices(self, indices):
        self._updating = True
        try:
            self.wheel.setIndices(indices)
            self.index_edit.setStyleSheet("")
            self.index_edit.setText(format_indices(
                self.wheel.indices(), self._gear()))
        finally:
            self._updating = False
        self._apply()

    # -- interchangeable depth/distance input --------------------------------

    def _display_distance(self):
        """The plane distance implied by the dialled depth. Computed here
        because the suppressed tier's execute (which normally rederives
        Distance) does not run during preview."""
        try:
            return reference_distance(self.tier) - self.depth_spin.value()
        except Exception:
            return self.tier.Distance.Value

    def _girdle_radius(self):
        """The girdle radius the height reading is measured at, or None."""
        shape = self._base_shape()
        if shape is None:
            return None
        metrics = girdle_metrics(shape)
        return None if metrics is None else metrics[0]

    def _display_height(self):
        """(value, is_height) for the box: the height at which this tier's
        facet crosses the girdle line, or the raw plane distance when that
        is undefined (a 90-degree tier, or no measurable girdle)."""
        distance = self._display_distance()
        radius = self._girdle_radius()
        if radius is not None:
            height = girdle_line_height(self.tier, radius, distance)
            if height is not None:
                return height, True
        return distance, False

    def _sync_distance_box(self):
        """Reflect the dialled depth in the height box, and keep the row
        label honest about which of the two readings it is showing."""
        value, is_height = self._display_height()
        self._updating = True
        try:
            self.distance_spin.setValue(value)
            self.height_label.setText(
                "Girdle height" if is_height else "Plane distance")
        finally:
            self._updating = False

    def _distance_edited(self, value):
        """The user typed a girdle height (or, for a 90-degree tier, a
        plane distance): convert to the plane distance and hand that to
        the feature, whose onChanged rederives CutDepth at full precision.

        The feature property is set directly rather than routed through
        the depth box because the box's 3-decimal display would quantize
        the derived depth — the point of this input is that the number
        the user typed lands exactly.
        """
        if self._updating:
            return
        self._graze_on_angle = False
        distance = value
        radius = self._girdle_radius()
        if radius is not None:
            converted = distance_for_girdle_height(self.tier, radius, value)
            if converted is not None:
                distance = converted
        self.tier.Distance = distance    # onChanged derives CutDepth
        self._updating = True
        try:
            self.depth_spin.setValue(self.tier.CutDepth.Value)
        finally:
            self._updating = False
        self._apply_soon()

    # -- the Auto button ------------------------------------------------------

    def _auto_toggled(self, armed):
        if not armed:
            self._disarm_select()
            self.auto_button.setText("Auto")
            return
        self._apply()
        # Auto never fires on the dialled angle alone: the *selection*
        # decides, and the selection is also what sets the angle in the
        # two special cases — a girdle-parallel face dials 90 and runs
        # the girdle flow, the stone's topmost crown vertex dials 0 and
        # runs the table flow.
        selection = getattr(Gui, "Selection", None)
        if selection is None:
            self.status_label.setText(
                "Auto needs the 3D view for a selection; there is no "
                "selection service in this session.")
            self.auto_button.setChecked(False)
            return
        # FreeCAD idiom: select first, then the command. A subshape
        # already selected when Auto is clicked is used immediately —
        # no second click required.
        try:
            picked = [(s.DocumentName, s.ObjectName, name)
                      for s in selection.getSelectionEx()
                      for name in s.SubElementNames]
        except Exception:
            picked = []
        if picked:
            self._auto_selected(*picked[0], (0.0, 0.0, 0.0))
            return
        selection.clearSelection()
        self._select_observer = _SelectionObserver(self._auto_selected)
        selection.addObserver(self._select_observer)
        self.auto_button.setText("Selecting\N{HORIZONTAL ELLIPSIS}")
        self.status_label.setText(
            "Select a vertex (plane through it), an edge (remove it), or "
            "a face — a facet to re-cut, a girdle-parallel face, or the "
            "%s flat face to close it to a point. Auto again cancels."
            % self.tier.WorkingSide.lower())

    def _pick_error(self, message):
        """An invalid Auto selection: status line plus a console error."""
        self.status_label.setText(message)
        FreeCAD.Console.PrintError("Lapidary: %s\n" % message)

    def _auto_table(self):
        """Angle 0 = a table: snap to the shallowest depth that forms a
        meet on the current stone (the table cut sized from the current
        dimensions)."""
        candidates = meetpoint_depths(self.tier)
        if not candidates:
            self.status_label.setText(
                "No usable table meet on the current stone; set the "
                "depth by hand.")
            FreeCAD.Console.PrintWarning(
                "Lapidary: no usable table meet on the current stone.\n")
            return
        self.depth_spin.setValue(candidates[0])
        self.status_label.setText(
            "Auto table: depth %.3f mm, the shallowest cut that forms a "
            "meet on the current stone." % candidates[0])

    def _disarm_select(self):
        if self._select_observer is not None:
            try:
                Gui.Selection.removeObserver(self._select_observer)
            except Exception:
                pass
            self._select_observer = None

    def _side_ok(self, zmin, zmax):
        """Is the selection on the working side of the *stone's girdle*?

        Measured against the girdle band of the current base solid
        (:func:`~..tier_feature.girdle_band`), not against z = 0: the
        origin is where the stock was centred at creation and stays put
        as tiers are cut, so it drifts away from the girdle and made
        this check misclassify elements on a worked stone.

        Girdle elements belong to neither side and are legitimate
        targets for both — a pavilion cut may reach up to the top of the
        band, a crown cut down to its bottom. When the band cannot be
        measured, or spans the whole stone (raw rough, which has no
        crown/pavilion differentiation yet), nothing is blocked.
        """
        shape = self._base_shape()
        band = girdle_band(shape) if shape is not None else None
        if band is None:
            return True
        z_low, z_high = band
        tol = _SIDE_TOL + 1e-6 * (shape.BoundBox.DiagonalLength or 1.0)
        if self.tier.WorkingSide == "Pavilion":
            return zmax <= z_high + tol
        return zmin >= z_low - tol

    def _auto_selected(self, doc_name, obj_name, sub, _pos):
        """Handle one pick — then disarm, valid or not.

        Strictly single-shot: an invalid pick used to leave Select…
        silently armed, so a later ordinary click in the 3D view fired
        the automation "out of nowhere". Now any pick consumes the armed
        state; the status message says how to try again.
        """
        self.auto_button.setChecked(False)       # disarms via _auto_toggled
        try:
            doc = FreeCAD.getDocument(doc_name)
            element = doc.getObject(obj_name).Shape.getElement(sub)
        except Exception:
            self._pick_error(
                "Invalid selection: select a vertex, edge or face in the "
                "3D view (not the tree) — click Auto to try again.")
            return
        sub = str(sub)
        self._graze_on_angle = False     # Auto aims a depth: op underway
        if sub.startswith("Vertex"):
            self._auto_vertex(element.Point)
        elif sub.startswith("Edge"):
            self._auto_edge(element)
        elif sub.startswith("Face"):
            self._auto_face(element)
        else:
            self._pick_error(
                "Invalid selection (%s): select a vertex, edge or face "
                "on the stone — click Auto to try again." % sub)
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass

    def _auto_vertex(self, point):
        if not self._side_ok(point.z, point.z):
            self._pick_error(
                "Invalid selection: that vertex is %s the stone's girdle, "
                "not on the %s side; pick on the working side."
                % ("above" if self.tier.WorkingSide == "Pavilion"
                   else "below", self.tier.WorkingSide.lower()))
            return False
        shape = self._base_shape()
        if (self.tier.WorkingSide == "Crown" and shape is not None
                and point.z >= shape.BoundBox.ZMax - _SIDE_TOL):
            # The stone's topmost vertex: unambiguous table intent. The
            # selection sets the angle (to 0) — the one way Auto ever
            # touches it besides matching a facet — then takes the
            # shallowest depth that forms a meet.
            if abs(self.angle_spin.value()) > 1e-9:
                self._updating = True
                try:
                    self.angle_spin.setValue(0.0)
                finally:
                    self._updating = False
            self._apply()
            self._auto_table()
            return True
        if math.hypot(point.x, point.y) < 1e-6:
            # Any other on-axis vertex has no azimuth to rotate onto:
            # keep the pattern and put the plane through the point.
            depth = depth_through_point(self.tier, point)
            if depth <= 0.0:
                self._pick_error(
                    "Invalid selection: that point lies outside the "
                    "reference boundary; depth unchanged.")
                return True
            self.depth_spin.setValue(depth)
            self.status_label.setText(
                "Auto: depth %.3f mm puts the facet plane through the "
                "on-axis vertex." % depth)
            return True
        azimuth = math.degrees(math.atan2(point.y, point.x))
        self._set_indices(align_indices_to_azimuth(self.tier, azimuth))
        depth = depth_through_point(self.tier, point)
        if depth <= 0.0:
            self._pick_error(
                "Invalid selection: that point lies outside the "
                "reference boundary; depth unchanged.")
            return True
        self.depth_spin.setValue(depth)
        self.status_label.setText(
            "Auto: indices rotated onto the vertex; depth %.3f mm puts "
            "the facet plane through it." % depth)
        return True

    def _auto_edge(self, edge):
        bb = edge.BoundBox
        if not self._side_ok(bb.ZMin, bb.ZMax):
            self._pick_error(
                "Invalid selection: that edge is not on the %s side of "
                "the stone's girdle; pick on the working side."
                % self.tier.WorkingSide.lower())
            return False
        com = edge.CenterOfMass
        if math.hypot(com.x, com.y) > 1e-6:
            azimuth = math.degrees(math.atan2(com.y, com.x))
            self._set_indices(align_indices_to_azimuth(self.tier, azimuth))
        depth = depth_to_remove_edge(self.tier, edge)
        if depth <= 0.0:
            self._pick_error(
                "Invalid selection: that edge lies outside the reference "
                "boundary; depth unchanged.")
            return True
        self.depth_spin.setValue(depth)
        self.status_label.setText(
            "Auto: indices rotated onto the edge; depth %.3f mm is the "
            "lowest cut that removes it entirely." % depth)
        return True

    def _auto_face(self, face):
        # Girdle flow first: a face parallel to the gem axis (a vertical
        # facet or the raw rough's cylindrical wall) belongs to the girdle
        # band, not to either side, so it bypasses the side validation.
        if is_girdle_face(face):
            return self._auto_girdle()
        bb = face.BoundBox
        if not self._side_ok(bb.ZMin, bb.ZMax):
            self._pick_error(
                "Invalid selection: that face is not on the %s side of "
                "the stone's girdle; pick on the working side."
                % self.tier.WorkingSide.lower())
            return False
        try:
            import Part
            if (isinstance(face.Surface, Part.Plane)
                    and abs(face.normalAt(0, 0).z) > 1.0 - 1e-6
                    and abs(self.angle_spin.value()) > 1e-9):
                # The working side's flat face, with a sloped angle
                # dialled: the explicit way to ask for the close-to-a-
                # point automation (it no longer fires unasked).
                depth = auto_axis_depth(self.tier)
                if depth is None or depth <= 0.0:
                    self._pick_error(
                        "Invalid selection: this tier's planes cannot "
                        "close that face to a point (the depth would "
                        "annihilate the stone).")
                    return True
                self.depth_spin.setValue(depth)
                self.status_label.setText(
                    "Auto: depth %.3f mm closes the selected flat face "
                    "to a point on the axis." % depth)
                return True
            side, angle, index, distance = face_tier_parameters(
                face, self._gear(), self._handedness)
        except ValueError as err:
            self._pick_error("Invalid selection: %s" % err)
            return False
        self._updating = True
        try:
            (self.crown_radio if side == "Crown"
             else self.pavilion_radio).setChecked(True)
            self.angle_spin.setValue(angle)
        finally:
            self._updating = False
        # A picked face only ever matches ONE facet of a symmetric
        # pattern; replacing the whole array with that single index would
        # silently collapse a pattern the user already built. If a
        # pattern exists, it is carried — rotated so one of its facets
        # lands exactly on the picked face — the same way a vertex or
        # edge pick aligns the pattern instead of overwriting it. Only an
        # empty array (no pattern yet) is seeded from the picked facet.
        if self.tier.Indices:
            self._set_indices(align_indices_to_index(self.tier, index))
        else:
            self._set_indices([index] if index else [])
        # Distance -> CutDepth via the feature's onChanged (full precision).
        self.tier.Distance = distance
        self._updating = True
        try:
            self.depth_spin.setValue(self.tier.CutDepth.Value)
        finally:
            self._updating = False
        self._apply()
        self.status_label.setText(
            "Auto: matched the selected facet \N{EM DASH} %s %.2f"
            "\N{DEGREE SIGN} at index %s, plane distance %.3f mm."
            % (side.lower(), angle, index or "0", distance))
        return True

    def _auto_girdle(self):
        """The girdle-auto flow: the tier is (or becomes) a 90-degree
        girdle. The index array copies the first patterned tier's — or
        keeps this tier's own on bare stock, where the girdle is cut
        first — and the depth is the minimum at which the chords close to
        a point: the shallowest meet, where adjacent flats first touch
        and the girdle outline closes."""
        indices = girdle_pattern_indices(self.tier)
        if not indices:
            self.status_label.setText(
                "Girdle auto needs an index pattern: set indices on this "
                "tier (or cut the mains first).")
            FreeCAD.Console.PrintWarning(
                "Lapidary: girdle auto found no index pattern to "
                "follow.\n")
            return True
        if abs(self.angle_spin.value() - 90.0) > 1e-9:
            self._updating = True
            try:
                self.angle_spin.setValue(90.0)
            finally:
                self._updating = False
        self._set_indices(indices)      # applies angle + indices
        candidates = meetpoint_depths(self.tier)
        if not candidates:
            self.status_label.setText(
                "Girdle set to 90\N{DEGREE SIGN} with the first tier's "
                "indices, but no meet depth could be computed; set the "
                "depth by hand.")
            return True
        self.depth_spin.setValue(candidates[0])
        self.status_label.setText(
            "Auto girdle: 90\N{DEGREE SIGN}, indices from the first "
            "tier, depth %.3f mm \N{EM DASH} the minimum at which the "
            "chords close to a point around the stone." % candidates[0])
        return True

    # -- live preview --------------------------------------------------------

    def _marker_length(self):
        shape = None
        base = getattr(self.tier, "BaseFeature", None)
        if base is not None and not base.Shape.isNull():
            shape = base.Shape
        if shape is None:
            return 10.0
        bb = shape.BoundBox
        return 0.62 * max(bb.XLength, bb.YLength)

    def _update_marker(self):
        indices = self.wheel.indices()
        start = min(indices) if indices else 0
        azimuth = gemmath.azimuth_deg(
            self._gear(), start, self.offset_spin.value(), self._handedness)
        self._marker.update(azimuth, self._marker_length())

    def _base_shape(self):
        base = getattr(self.tier, "BaseFeature", None)
        if base is None or base.Shape.isNull():
            return None
        return base.Shape

    @staticmethod
    def _plane_corners(normal, distance, half):
        """The corners of a square patch of the plane n.x = d."""
        foot = normal * distance
        axis_u = FreeCAD.Vector(0, 0, 1).cross(normal)
        if axis_u.Length < 1e-9:
            axis_u = FreeCAD.Vector(1, 0, 0)
        axis_u.normalize()
        axis_v = normal.cross(axis_u)
        return [foot + axis_u * s + axis_v * t
                for s, t in ((-half, -half), (half, -half),
                             (half, half), (-half, half))]

    def _update_preview(self):
        """Redraw the pending-cut overlay; returns a status fragment.

        The overlay is the *cut planes clipped to the stone*: each facet
        plane is intersected with the base solid and only the resulting
        slice is highlighted — a faint fill with a sharp outline at the
        stone's surface. When no plane touches the stone, the first
        facet's plane is shown floating at full size instead.
        """
        import Part

        shape = self._base_shape()
        if shape is None:
            self._preview.clear()
            return "no base solid yet"
        distance = self._display_distance()
        normals = effective_normals(self.tier)
        # Two patch sizes for two jobs. The *slice* patch must cover the
        # stone's whole cross-section, or common() clips the slice at the
        # patch edge and those straight clip chords get drawn as if they
        # were kerf outline (the crisscross seen on a 42-degree tier when
        # this used the girdle radius - a steep slice is wider than the
        # girdle). The *floating* patch, drawn only when the planes miss,
        # is girdle-sized so it reads as "out here" without swamping the
        # view.
        metrics = girdle_metrics(shape)
        girdle_half = (metrics[0] if metrics is not None
                       else 0.5 * shape.BoundBox.DiagonalLength)
        half = 0.75 * shape.BoundBox.DiagonalLength
        slices = []
        if distance > 1e-9:
            for normal_tuple in normals:
                normal = FreeCAD.Vector(*normal_tuple)
                corners = self._plane_corners(normal, distance, half)
                try:
                    patch = Part.Face(Part.makePolygon(
                        corners + [corners[0]]))
                    piece = shape.common(patch)
                except Exception:
                    continue
                slices.extend(f for f in piece.Faces if f.Area > 1e-9)
        if slices:
            if self.result_check.isChecked():
                # Finished-cut preview: the real geometry already shows
                # the result, so the kerf outline would only clutter it.
                self._preview.clear()
                return ("cutting: showing the finished result (%d slice%s "
                        "in bounds)"
                        % (len(slices), "" if len(slices) == 1 else "s"))
            self._preview.show_slices(slices)
            return ("cutting: %d slice%s highlighted where the planes "
                    "pass through the stone"
                    % (len(slices), "" if len(slices) == 1 else "s"))
        # The planes miss the stone: show the first facet plane instead.
        normal = FreeCAD.Vector(*normals[0]) if normals else \
            FreeCAD.Vector(0, 0, 1)
        corners = self._plane_corners(normal, distance, girdle_half)
        self._preview.show_plane([(c.x, c.y, c.z) for c in corners])
        return "plane misses the stone (shown at the first index)"

    def _update_stats(self):
        """Show the current stone measurements above the status line."""
        gem = gem_feature.find_gem(self.tier)
        shape = None if gem is None else gem_feature.final_shape(gem)
        if shape is None:
            self.stats_label.setText("")
            return
        try:
            from freecad.lapidary.faceting import reports
            report = reports.compute_report(shape)
        except Exception:
            self.stats_label.setText("")
            return

        def pct(key):
            value = report.get(key)
            return "—" if value is None else "%.1f %%" % value

        self.stats_label.setText(
            "W %.2f mm · L/W %.3f · depth %s · crown %s "
            "· girdle %s · pavilion %s · table %s "
            "· %d facets"
            % (report["width"], report["lw_ratio"], pct("depth_pct"),
               pct("crown_pct"), pct("girdle_pct"), pct("pavilion_pct"),
               pct("table_pct"), report["facet_count"]))

    def _apply_soon(self, *_args):
        """Debounced apply for spin-driven edits: restart the timer so
        only the final value of a scroll or key-repeat burst recomputes."""
        if self._updating:
            return
        self._apply_timer.start()

    def _apply(self, *_args):
        if self._updating:
            return
        self._apply_timer.stop()   # a direct apply supersedes any pending one
        tier = self.tier
        tier.TierName = self.name_edit.text()
        tier.WorkingSide = ("Crown" if self.crown_radio.isChecked()
                            else "Pavilion")
        tier.Angle = self.angle_spin.value()
        # Only push the depth box's value when the user actually moved it:
        # after a distance edit the feature holds a full-precision depth the
        # 3-decimal box can only approximate, and writing the rounded value
        # back would shift the typed distance by a tenth of a micron.
        if abs(self.depth_spin.value() - tier.CutDepth.Value) > 5e-4:
            tier.CutDepth = self.depth_spin.value()
        tier.IndexOffset = self.offset_spin.value()
        tier.Indices = self.wheel.indices()
        try:
            self.doc.recompute()
        except Exception as err:  # keep the panel alive on bad geometry
            self.status_label.setText(str(err))
            return
        self._update_marker()
        self._sync_distance_box()
        self._update_stats()
        fragment = self._update_preview()
        self.status_label.setText(
            "plane distance %.3f mm \N{EM DASH} %s"
            % (self._display_distance(), fragment))

    # -- task panel protocol -------------------------------------------------

    @staticmethod
    def _button_value(button):
        # PySide6 standard buttons are Flag enums whose int() needs .value;
        # FreeCAD hands the clicked id over as a plain int already.
        return int(getattr(button, "value", button))

    def getStandardButtons(self):
        return self._button_value(QtWidgets.QDialogButtonBox.Ok
                                  | QtWidgets.QDialogButtonBox.Apply
                                  | QtWidgets.QDialogButtonBox.Cancel)

    def clicked(self, button):
        if self._button_value(button) == self._button_value(
                QtWidgets.QDialogButtonBox.Apply):
            self.apply_tier()

    def _close(self):
        self._apply_timer.stop()   # never fire into a closed panel
        self._disarm_select()
        self._marker.detach()
        self._preview.detach()
        Gui.Control.closeDialog()

    def _commit(self):
        """Sync, unsuppress, name and commit the tier under edit; remember
        its side as the gem's active side. Unsuppressing is what turns the
        green preview into the real cut — the "new job" the refreshed live
        view shows."""
        self._apply()
        self.tier.Suppressed = self._entered_suppressed
        if self.tier.TierName and self.tier.Label.startswith("FacetTier"):
            self.tier.Label = self.tier.TierName
        gem = gem_feature.find_gem(self.tier)
        if gem is not None:
            gem.ActiveSide = self.tier.WorkingSide
        self.doc.commitTransaction()
        self.doc.recompute()
        self._preview.clear()

    def apply_tier(self):
        """Commit the current tier but keep the panel open: creating a fresh
        follow-on tier when this panel was creating one, or reopening the
        edit transaction when it was editing an existing tier."""
        from freecad.lapidary.faceting.tier_feature import make_tier

        self._commit()
        if not self.is_new:
            self.doc.openTransaction("Edit facet tier")
            self._entered_suppressed = self.tier.Suppressed
            self._sync_suppression()
            self.doc.recompute()
            self._apply()
            self.status_label.setText("Applied \N{EM DASH} still editing "
                                      "%s." % self.tier.Label)
            return
        committed = self.tier.TierName or self.tier.Label
        gem = gem_feature.find_gem(self.tier)
        self.doc.openTransaction("Add facet tier")
        self.tier = make_tier(
            gem, angle=self.angle_spin.value(),
            depth=self.depth_spin.value(),
            indices=self.wheel.indices(),
            side=("Crown" if self.crown_radio.isChecked() else "Pavilion"),
            index_offset=self.offset_spin.value())
        self._entered_suppressed = False
        self._sync_suppression()
        self.name_edit.setText("")               # a new tier needs a new name
        self.doc.recompute()
        self._apply()
        self._graze_on_angle = True      # the follow-on tier is a new cut
        self.status_label.setText(
            "%s applied \N{EM DASH} now cutting a new tier." % committed)

    def accept(self):
        self._commit()
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()  # removes a new/un-applied tier or
        self.doc.recompute()         # reverts an edit since the last Apply
        self._close()
        return True


def _show_panel(panel):
    if Gui.Control.activeDialog():
        FreeCAD.Console.PrintWarning(
            "Lapidary: another task panel is already open\n")
        panel._marker.detach()
        panel._preview.detach()
        try:
            panel.tier.Suppressed = panel._entered_suppressed
        except Exception:
            pass
        return False
    Gui.Control.showDialog(panel)
    return True


def open_tier_editor(tier):
    """Re-edit an existing tier (tree double-click / setEdit)."""
    tier.Document.openTransaction("Edit facet tier")
    if not _show_panel(FacetTierPanel(tier, is_new=False)):
        tier.Document.abortTransaction()
        return False
    return True


def default_indices(gear):
    """Default index pattern for a fresh tier: 8-fold mains when the gear
    allows it, else the single tooth N. (An empty list would be interpreted
    as one axial index-0 facet — surprising as a silent default.)"""
    if gear >= 8 and gear % 8 == 0:
        step = gear // 8
        return list(range(step, gear + 1, step))
    return [gear]


def open_new_tier(gem):
    """Create a tier with sensible defaults and open the panel on it."""
    from freecad.lapidary.faceting.tier_feature import make_tier

    doc = gem.Document
    doc.openTransaction("Add facet tier")
    tier = make_tier(gem, angle=42.0, depth=0.5,
                     indices=default_indices(gem.IndexGear),
                     side=gem.ActiveSide)
    doc.recompute()
    if not _show_panel(FacetTierPanel(tier, is_new=True)):
        doc.abortTransaction()
        doc.recompute()
        return False
    return True
