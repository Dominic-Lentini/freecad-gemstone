# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lapidary optics module (DESIGN_OPTICS.md, Phase 4).

Analysis only: ray-traces finished gem geometry and writes reports. It never
feeds geometry back into the design pipeline (DESIGN.md section 6, binding).

Layout:

- ``polytope``  — convex-polytope extraction, validation, and the exact
  convex ray walk (pure numpy, importable without FreeCAD);
- ``materials`` — refractive index + dispersion presets, Cauchy expansion;
- ``lighting``  — lighting models and the frozen Occluder protocol;
- ``tracer``    — the vectorized reverse ray tracer;
- ``metrics``   — brightness / leakage / per-tier / tilt-curve numbers;
- ``study_feature`` — the OpticsStudy document object (needs FreeCAD);
- ``commands``  — GUI commands (needs FreeCADGui; never import headless).
"""
