# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stock habit registry (DESIGN.md section 2: extensible registry of rough
habits, always created with the center of mass at the document origin).

Built-in habits: cylinder, rectangular prism, hexagonal prism, octahedron,
dodecahedron, trigonal prism. All builders produce exact OpenCascade B-Rep
solids (no meshes) and the registry re-centers every result on its center of
mass, so the origin/mass-centering contract holds for third-party habits too.

App-side FreeCAD + Part only; runs under FreeCADCmd headless.
"""

import math
from collections import OrderedDict

import FreeCAD
import Part

__all__ = [
    "StockHabit",
    "register_habit",
    "get_habit",
    "habit_keys",
    "build_stock",
]

_PHI = (1.0 + math.sqrt(5.0)) / 2.0


class StockHabit:
    """A stock habit: a named parametric builder for a rough shape.

    ``params`` is an ordered list of ``(name, label, default_mm)`` tuples;
    ``builder`` is a callable taking the dimension values as keyword arguments
    (in mm) and returning a Part shape. The registry mass-centers the result.
    """

    def __init__(self, key, label, params, builder):
        self.key = key
        self.label = label
        self.params = list(params)
        self.builder = builder

    def defaults(self):
        return OrderedDict((name, default) for name, _label, default in self.params)

    def build(self, **dims):
        """Build the habit solid, mass-centered at the origin."""
        values = self.defaults()
        for name, value in dims.items():
            if name not in values:
                raise ValueError(
                    "habit %r has no dimension %r (has: %s)"
                    % (self.key, name, ", ".join(values)))
            values[name] = float(value)
        for name, value in values.items():
            if not value > 0.0:
                raise ValueError(
                    "habit %r dimension %s must be > 0, got %r"
                    % (self.key, name, value))
        shape = self.builder(**values)
        # Enforce the mass-centering contract regardless of how the builder
        # positioned the solid. The correction must be baked into the
        # *geometry* (transformGeometry), not into the shape's placement:
        # a FeaturePython recompute overwrites the assigned shape's placement
        # with the object's Placement property, so location-based translation
        # would be silently discarded (verified on FreeCAD 1.1, see
        # docs/dev-notes.md).
        com = shape.CenterOfMass
        if com.Length > 1e-12:
            matrix = FreeCAD.Matrix()
            matrix.move(com.negative())
            shape = shape.transformGeometry(matrix)
            # transformGeometry returns a generic Part.Shape; unwrap back to
            # the solid so callers keep a uniform interface.
            if len(shape.Solids) == 1:
                shape = shape.Solids[0]
        return shape


_REGISTRY = OrderedDict()


def register_habit(habit):
    """Register a StockHabit (extensible: later modules may add habits)."""
    _REGISTRY[habit.key] = habit
    return habit


def get_habit(key):
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError("unknown stock habit %r (known: %s)"
                       % (key, ", ".join(_REGISTRY)))


def habit_keys():
    return list(_REGISTRY)


def build_stock(key, dims=None):
    """Build a mass-centered stock solid for habit ``key``."""
    return get_habit(key).build(**(dims or {}))


# ---------------------------------------------------------------------------
# Built-in builders
# ---------------------------------------------------------------------------

def _regular_polygon_prism(circumradius, height, sides, phase_deg=0.0):
    """Prism over a regular polygon in the XY plane, extruded symmetrically
    about z=0 so the geometry is centered by construction (see
    StockHabit.build for why placement-based centering is not enough)."""
    points = []
    for k in range(sides):
        a = math.radians(phase_deg) + 2.0 * math.pi * k / sides
        points.append(FreeCAD.Vector(circumradius * math.cos(a),
                                     circumradius * math.sin(a),
                                     -height / 2.0))
    points.append(points[0])
    wire = Part.Wire(Part.makePolygon(points))
    face = Part.Face(wire)
    return face.extrude(FreeCAD.Vector(0.0, 0.0, height))


def _convex_solid(vertices, face_normals, tol=1e-9):
    """Exact B-Rep solid of a convex polyhedron given its vertices and one
    outward direction per face.

    For each direction, the face's vertices are those maximizing the dot
    product (within ``tol``), ordered counter-clockwise around the outward
    normal so every polygon winds consistently for shell sewing.
    """
    faces = []
    for direction in face_normals:
        n = FreeCAD.Vector(*direction)
        n.normalize()
        dots = [n.dot(FreeCAD.Vector(*v)) for v in vertices]
        top = max(dots)
        pts = [FreeCAD.Vector(*v) for v, dot in zip(vertices, dots)
               if top - dot <= tol * max(1.0, abs(top))]
        if len(pts) < 3:
            raise ValueError("face direction %s selects %d vertices; "
                             "expected a polygon" % (direction, len(pts)))
        center = FreeCAD.Vector()
        for p in pts:
            center += p
        center.multiply(1.0 / len(pts))
        # Right-handed in-plane basis (u, v, n) -> CCW sort is outward-facing.
        u = pts[0] - center
        u = (u - n * n.dot(u)).normalize()
        v = n.cross(u)
        pts.sort(key=lambda p: math.atan2(v.dot(p - center), u.dot(p - center)))
        pts.append(pts[0])
        faces.append(Part.Face(Part.Wire(Part.makePolygon(pts))))
    solid = Part.makeSolid(Part.makeShell(faces))
    if solid.Volume < 0.0:
        solid.reverse()
    return solid


def _build_cylinder(Diameter, Height):
    return Part.makeCylinder(Diameter / 2.0, Height,
                             FreeCAD.Vector(0.0, 0.0, -Height / 2.0))


def _build_box(Length, Width, Height):
    return Part.makeBox(Length, Width, Height,
                        FreeCAD.Vector(-Length / 2.0, -Width / 2.0,
                                       -Height / 2.0))


def _build_hex_prism(WidthAcrossFlats, Height):
    # Flats face +/-X at phase 0 with circumradius = across-flats / sqrt(3).
    circumradius = WidthAcrossFlats / math.sqrt(3.0)
    return _regular_polygon_prism(circumradius, Height, 6, phase_deg=30.0)


def _build_trigonal_prism(Side, Height):
    circumradius = Side / math.sqrt(3.0)
    return _regular_polygon_prism(circumradius, Height, 3, phase_deg=90.0)


def _build_octahedron(Size):
    # Size = distance between opposite vertices (they lie on the axes).
    a = Size / 2.0
    vertices = [(a, 0, 0), (-a, 0, 0), (0, a, 0), (0, -a, 0),
                (0, 0, a), (0, 0, -a)]
    normals = [(sx, sy, sz)
               for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
    return _convex_solid(vertices, normals)


def _build_dodecahedron(Size):
    # Size = distance between opposite faces (2 x inradius). Canonical
    # vertex set (+-1,+-1,+-1), (0,+-1/phi,+-phi) and cyclic permutations has
    # inradius phi^2 / sqrt(phi^2 + 1); scale so the inradius is Size/2.
    inradius_unit = _PHI ** 2 / math.sqrt(_PHI ** 2 + 1.0)
    s = (Size / 2.0) / inradius_unit
    inv = 1.0 / _PHI
    vertices = [(s * x, s * y, s * z)
                for x in (1, -1) for y in (1, -1) for z in (1, -1)]
    for a, b in [(inv, _PHI), (inv, -_PHI), (-inv, _PHI), (-inv, -_PHI)]:
        vertices.append((0.0, s * a, s * b))
        vertices.append((s * a, s * b, 0.0))
        vertices.append((s * b, 0.0, s * a))
    # Face directions: (0, +-phi, +-1) and cyclic permutations (12 faces).
    normals = []
    for a in (_PHI, -_PHI):
        for b in (1, -1):
            normals.append((0.0, a, b))
            normals.append((a, b, 0.0))
            normals.append((b, 0.0, a))
    return _convex_solid(vertices, normals)


register_habit(StockHabit(
    "Cylinder", "Cylinder",
    [("Diameter", "Diameter", 12.0), ("Height", "Height", 10.0)],
    _build_cylinder))
register_habit(StockHabit(
    "RectangularPrism", "Rectangular prism",
    [("Length", "Length", 14.0), ("Width", "Width", 10.0),
     ("Height", "Height", 8.0)],
    _build_box))
register_habit(StockHabit(
    "HexagonalPrism", "Hexagonal prism",
    [("WidthAcrossFlats", "Width across flats", 10.0),
     ("Height", "Height", 10.0)],
    _build_hex_prism))
register_habit(StockHabit(
    "Octahedron", "Octahedron",
    [("Size", "Vertex-to-vertex size", 12.0)],
    _build_octahedron))
register_habit(StockHabit(
    "Dodecahedron", "Dodecahedron",
    [("Size", "Face-to-face size", 12.0)],
    _build_dodecahedron))
register_habit(StockHabit(
    "TrigonalPrism", "Trigonal prism",
    [("Side", "Triangle side", 12.0), ("Height", "Height", 10.0)],
    _build_trigonal_prism))
