# Lapidary — a faceting workbench for FreeCAD

Lapidary is a FreeCAD workbench for designing faceted gemstones with
GemCad-comparable capability: parametric facet tiers driven by index gear,
angle and index list; live 3D preview; dop transfer between pavilion and
crown; GemCad `.ASC` import/export; and printable 2D faceting diagrams.

**Status: 0.2.0.** You can model a stone, exchange it with GemCad, print a
diagram, and ray-trace the finished design:

- **Parametric pipeline** — Gem / Stock / FacetTier features, six stock habits
  (cylinder, rectangular/hexagonal/trigonal prisms, octahedron, dodecahedron)
  **or any FreeCAD Part/Body solid as custom rough** (re-centered on its
  volume centroid), half-space facet cutting in exact OpenCascade B-Rep, tip
  semantics with drag-reorder, delete and suppress.
- **Task panels** with a live pending-cut preview — bright kerf outlines
  where the cut planes cross the stone, or the facet plane itself when the
  cut misses — a clickable index wheel with KSP-style radial symmetry (any
  fold 1-9, snapped to the gear), a selection-driven **Auto** that aims the
  cut at a picked vertex, edge or face, and Apply to commit a tier and start
  the next without leaving the form.
- **GemCad `.ASC` import and export** that retains geometric
  fidelity
- **2D faceting diagram** — a live dockable diagram with crown,
  pavilion and elevation views, index-gear ring, tier table and stone data;
  exportable as SVG or PDF, and embeddable in the cutting sheet.
- **Cutting sheet and stone report** — ordered cutting instructions as
  printable HTML, and measurements (L/W, depth %, crown/pavilion %, table %,
  girdle thickness, facet count).
- **Optics studies** — a ray-trace reporting module: light return,
  windowing/leakage and per-tier attribution with in-document result maps,
  tilt curves, an interactive single-ray path visual, multi-wavelength fire
  analysis, optional approximate absorption, and a Render-workbench material
  card export


The live faceting diagram dock beside the 3D view, its facets tinted by light return.

![diagram dock](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/diagram-dock.png)

**Facet Tier** mid-edit: the index wheel with 8-fold symmetry active, the pending cut previewed as bright kerf outlines where the planes cross the stone.

![facet tier panel](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/facet-tier-panel.png)

The same panel at a depth that misses the stone — the facet plane itself is drawn instead of a kerf.

![facet tier plane](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/facet-tier-plane.png)

**Auto** armed and waiting: the vertex, edge or face you pick aims the cut.

![auto select](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/auto-select.png)

**New Gem**

![custom rough](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/custom-rough.png)

The **Optics Results** dock after a three-wavelength run: brightness, window/leak and fire-spread maps with the per-tier table.

![optics results](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/optics-results.png)

**Trace Ray** — one picked ray fanned into its wavelength-coloured branch tree inside the stone.

![trace ray](https://github.com/Dominic-Lentini/freecad-gemstone/raw/main/docs/images/trace-ray.png)


## Requirements

- **FreeCAD 1.1 or newer** for the workbench (its GUI is written against
  PySide6, which FreeCAD 1.0 does not ship).

## Commands

| Command | What it does |
|---|---|
| **New Gem** | Launches a wizard to create a new piece of rough from an existing part body or generates one using form parameters: dimensions, index gear, and handedness
| **Facet Tier** | Add a tier: working side, angle, cut depth — typed, or set by **Auto** (close a flat face to the axis, or select a vertex/edge/face to aim the cut, or a face parallel to the axis for an auto girdle: 90°, the first tier's indices, and the depth where the chords close to a point) — and index list with radial symmetry; the pending cut previews as bright kerf outlines (or a green plane when it misses), and Apply cuts tier after tier. *note*: Auto function is kind of buggy, but it does work pretty well in my testing for girdles and meet points along the Z axis.
| **Flip Stone (Dop Transfer)** | Mirror the whole stone through the girdle plane — every tier's working side flips with its plane distance preserved; the fix for cutting a side with the wrong radio selected | 
| **Import ASC** / **Export ASC** | GemCad `.ASC` interchange |
| **Faceting Diagram** | Live 2D diagram dock; export SVG or PDF |
| **Cutting Sheet** | Printable cutting instructions, optionally with the diagram |
| **Stone Report** | L/W, depth %, crown/pavilion %, table %, girdle, facet count — includes the optics section when a study exists |
| **Optics Study** / **Run Optics Study** | Create and execute a ray-trace study: material, lighting, grid, tilt, wavelengths, absorption |
| **Optics Results** | Dock with brightness / window-leak / tilt / fire-spread maps, headline numbers and the per-tier table |
| **Trace Ray** | Pick a point on the stone and trace its branch tree into RayTrace objects under the study — wavelength-colored, editable and deletable in the tree |
| **Export Render Material** | Write a Render-workbench .FCMat glass card from the tracer's own constants |

## Development

The full suite (including the modeling pipeline and the diagram's projection)
needs FreeCAD's bundled Python. On Windows:

```bash
run_tests.cmd
```

To regenerate the fixture diagrams for visual comparison against published
faceting diagrams:

```bash
python tools/generate_diagrams.py
```

CI runs the core files on plain CPython, then installs FreeCAD 1.1.x
and 1.0.x headless from conda-forge, runs the suite under each, and verifies
the addon installs and its metadata loads under `FreeCADCmd`
(see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

## License

LGPL-2.1-or-later — see [LICENSE](LICENSE).
