# SPDX-License-Identifier: LGPL-2.1-or-later
"""The OpticsStudy document object (DESIGN_OPTICS.md section 7).

A FEM-style saved study: a FeaturePython child of the Gem carrying the
input parameters and the stored results. **Executing a study is always
manual** — tracing takes seconds to minutes and must never run inside a
document recompute. What *does* run on recompute is the cheap staleness
check: the study stores a geometry fingerprint (hash of the sorted,
rounded plane set plus the input properties) and raises a visible
``Stale`` flag when the current geometry/material no longer matches the
stored results, like FEM results after a mesh change.

Recompute plumbing: the study keeps a hidden ``TipFeature`` link to the
pipeline tip, so editing any tier touches the study and re-runs the
staleness check (never the trace). When tiers are added or removed the tip
identity changes; execute() re-resolves the link so the next recompute
tracks the new tip (one recompute of lag, acceptable for a flag).

Importable headless; the ViewProvider is attached only when a GUI is up.
Result maps (brightness, window/leak classification, tilt montage, tilt
curve) are rendered by optics/imaging.py and embedded in the .FCStd via
``App::PropertyFileIncluded`` (verified 1.1 behavior: assigning a path
copies the file into the document's transient store and it survives
save/reload). Per-tier attribution is stored as parallel list properties
so the results dock and diagram overlay never need to re-trace.
"""

import hashlib
import os
import tempfile

import numpy as np

import FreeCAD

from freecad.lapidary.faceting import gem_feature
from freecad.lapidary.optics import lighting as _lighting
from freecad.lapidary.optics import materials as _materials
from freecad.lapidary.optics import metrics as _metrics
from freecad.lapidary.optics import tracer as _tracer
from freecad.lapidary.optics.polytope import PolytopeError, extract_polytope

__all__ = [
    "STUDY_SCHEMA_VERSION",
    "LIGHTING_MODELS",
    "OpticsStudyProxy",
    "make_study",
    "is_study",
    "find_studies",
    "study_material",
    "study_lighting",
    "is_results_sheet",
    "results_sheet_of",
    "geometry_fingerprint",
    "run_study",
]

STUDY_SCHEMA_VERSION = 1

LIGHTING_MODELS = ["Uniform hemisphere", "Cosine dome", "Ring light"]

CUSTOM_MATERIAL = "Custom"

WAVELENGTH_CHOICES = ["1", "3", "5"]    # sample counts; 3/5 used in Phase 4c


def is_study(obj):
    proxy = getattr(obj, "Proxy", None)
    return getattr(proxy, "Type", None) == "Lapidary::OpticsStudy"


def find_studies(gem):
    """The OpticsStudy children of a Gem, in group order."""
    return [o for o in gem.Group if is_study(o)]


class OpticsStudyProxy:
    """Proxy for the OpticsStudy FeaturePython object."""

    Type = "Lapidary::OpticsStudy"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        def add(ptype, name, group, doc, default=None, hidden=False,
                read_only=False):
            if not hasattr(obj, name):
                obj.addProperty(ptype, name, group, doc)
                if default is not None:
                    setattr(obj, name, default)
                if hidden:
                    obj.setPropertyStatus(name, "Hidden")
                if read_only:
                    obj.setEditorMode(name, 1)

        # -- inputs ---------------------------------------------------------
        if not hasattr(obj, "MaterialPreset"):
            obj.addProperty("App::PropertyEnumeration", "MaterialPreset",
                            "Material", "Gem material preset (or Custom)")
            obj.MaterialPreset = ([CUSTOM_MATERIAL]
                                  + _materials.preset_names())
            obj.MaterialPreset = "Quartz"
        add("App::PropertyFloat", "RefractiveIndex", "Material",
            "Refractive index n_d at 589.3 nm (set by the preset; editable "
            "when the preset is Custom)", _materials.PRESETS["Quartz"].n_d)
        add("App::PropertyFloat", "Dispersion", "Material",
            "Gemological (Fraunhofer B-G) dispersion, n(430.8) - n(686.7)",
            _materials.PRESETS["Quartz"].dispersion)
        if not hasattr(obj, "LightingModel"):
            obj.addProperty("App::PropertyEnumeration", "LightingModel",
                            "Lighting", "Lighting environment model")
            obj.LightingModel = LIGHTING_MODELS
            obj.LightingModel = LIGHTING_MODELS[0]
        add("App::PropertyFloat", "RingLightLow", "Lighting",
            "Ring light: lower elevation bound (degrees above horizon)", 30.0)
        add("App::PropertyFloat", "RingLightHigh", "Lighting",
            "Ring light: upper elevation bound (degrees above horizon)", 60.0)
        add("App::PropertyFloat", "HeadShadowDeg", "Lighting",
            "Observer head-shadow cone half-angle in degrees (0 = off)", 0.0)
        add("App::PropertyInteger", "GridResolution", "Tracing",
            "View grid resolution per axis (the speed/quality dial)", 256)
        add("App::PropertyFloat", "TiltMaxDeg", "Tracing",
            "Tilt curve: maximum tilt angle (degrees)", 30.0)
        add("App::PropertyInteger", "TiltSteps", "Tracing",
            "Tilt curve: number of tilt samples from 0 to TiltMaxDeg", 7)
        add("App::PropertyInteger", "MaxDepth", "Tracing",
            "Maximum internal bounces per ray path", 32)
        add("App::PropertyFloat", "MinEnergy", "Tracing",
            "Branches below this energy fraction are pruned (tallied)", 1e-3)
        if not hasattr(obj, "Wavelengths"):
            obj.addProperty("App::PropertyEnumeration", "Wavelengths",
                            "Tracing", "Wavelength samples: 1 = brightness "
                            "only (d line); 3/5 add fire (Phase 4c)")
            obj.Wavelengths = WAVELENGTH_CHOICES
            obj.Wavelengths = "1"
        add("App::PropertyFloat", "AbsorptionPerMM", "Tracing",
            "Beer-Lambert absorption coefficient per mm of internal path "
            "(0 = off, the default). APPROXIMATE single-coefficient body "
            "color; see the tracer docstring.", 0.0)
        add("App::PropertyInteger", "SchemaVersion", "Study",
            "Property schema version (for migration)", STUDY_SCHEMA_VERSION,
            hidden=True)
        add("App::PropertyLink", "TipFeature", "Study",
            "Pipeline tip this study watches for staleness", hidden=True)

        # -- results --------------------------------------------------------
        add("App::PropertyFloat", "LightReturnPct", "Results",
            "Headline light return (brightness) percentage", read_only=True)
        add("App::PropertyFloat", "LeakPct", "Results",
            "Energy percentage exiting the pavilion side", read_only=True)
        add("App::PropertyFloat", "PrunedPct", "Results",
            "Energy percentage dropped by MinEnergy/MaxDepth",
            read_only=True)
        add("App::PropertyFloat", "FireIndex", "Results",
            "Lapidary Fire Index in degrees (0 when the study traced a "
            "single wavelength; see the summary for the definition)",
            read_only=True)
        add("App::PropertyFloatList", "WavelengthsNm", "Results",
            "Wavelength samples of the last run (nm)", read_only=True)
        add("App::PropertyFloatList", "WavelengthBrightness", "Results",
            "Brightness % per wavelength sample", read_only=True)
        add("App::PropertyFloatList", "TiltAngles", "Results",
            "Tilt curve sample angles (degrees)", read_only=True)
        add("App::PropertyFloatList", "TiltBrightness", "Results",
            "Tilt curve brightness % per sample angle", read_only=True)
        add("App::PropertyFloat", "MeanPathLength", "Results",
            "Energy-weighted mean internal path length (mm)",
            read_only=True)
        add("App::PropertyFloat", "MaxPathLength", "Results",
            "Longest escaping branch's internal path length (mm)",
            read_only=True)
        add("App::PropertyFloat", "RuntimeS", "Results",
            "Total trace runtime of the last run (seconds)", read_only=True)
        add("App::PropertyString", "ResultSummary", "Results",
            "Human-readable summary of the last run", read_only=True)
        add("App::PropertyStringList", "TierNames", "Results",
            "Per-tier attribution rows: tier labels (parallel lists)",
            read_only=True)
        add("App::PropertyFloatList", "TierReturnPct", "Results",
            "Per-tier attribution: returned % of incident energy",
            read_only=True)
        add("App::PropertyFloatList", "TierLeakPct", "Results",
            "Per-tier attribution: leaked % of incident energy",
            read_only=True)
        add("App::PropertyFileIncluded", "BrightnessMapFile", "Result Maps",
            "Brightness map PNG (embedded in the document)", read_only=True)
        add("App::PropertyFileIncluded", "ClassificationMapFile",
            "Result Maps", "Window/leak classification map PNG",
            read_only=True)
        add("App::PropertyFileIncluded", "TiltMapsFile", "Result Maps",
            "Tilt-series brightness maps PNG (one tile per tilt step)",
            read_only=True)
        add("App::PropertyFileIncluded", "TiltCurveFile", "Result Maps",
            "Brightness-vs-tilt curve plot PNG", read_only=True)
        add("App::PropertyFileIncluded", "SpreadMapFile", "Result Maps",
            "Fire spread map PNG (multi-wavelength runs only)",
            read_only=True)
        add("App::PropertyString", "Fingerprint", "Results",
            "Geometry+inputs fingerprint of the stored results", hidden=True)
        add("App::PropertyBool", "Stale", "Results",
            "True when geometry or inputs changed after the last run",
            read_only=True)

    def onChanged(self, obj, prop):
        # Selecting a preset copies its constants into the editable fields
        # and re-applies the preset's cosmetic viewport tint (presentation
        # only; see optics/appearance.py — never read by the tracer).
        if prop == "MaterialPreset" and not getattr(
                obj.Document, "Restoring", False):
            preset = _materials.PRESETS.get(obj.MaterialPreset)
            if preset is not None:
                if obj.RefractiveIndex != preset.n_d:
                    obj.RefractiveIndex = preset.n_d
                if obj.Dispersion != preset.dispersion:
                    obj.Dispersion = preset.dispersion
                from freecad.lapidary.optics.appearance import (
                    apply_material_appearance)
                apply_material_appearance(gem_feature.find_gem(obj), preset)

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def execute(self, obj):
        """Recompute = cheap staleness check only, never a trace."""
        gem = gem_feature.find_gem(obj)
        if gem is None:
            obj.Stale = True
            return
        tip = gem_feature.tip_feature(gem)
        if tip is not None and obj.TipFeature is not tip:
            obj.TipFeature = tip
        if not obj.Fingerprint:
            obj.Stale = True        # never run
            return
        obj.Stale = geometry_fingerprint(gem, obj) != obj.Fingerprint

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_study(gem, label="OpticsStudy"):
    """Create an OpticsStudy under ``gem``."""
    doc = gem.Document
    obj = doc.addObject("App::FeaturePython", "OpticsStudy")
    OpticsStudyProxy(obj)
    obj.Label = label
    gem.addObject(obj)
    tip = gem_feature.tip_feature(gem)
    if tip is not None:
        obj.TipFeature = tip
    obj.Stale = True
    _attach_view_provider(obj)
    # Initial cosmetic tint for the default preset (no-op headless).
    from freecad.lapidary.optics.appearance import apply_material_appearance
    apply_material_appearance(gem, _materials.PRESETS.get(obj.MaterialPreset))
    return obj


def _attach_view_provider(obj):
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        from freecad.lapidary.optics.viewproviders import (
            ViewProviderOpticsStudy)
        ViewProviderOpticsStudy(obj.ViewObject)


# ---------------------------------------------------------------------------
# Study inputs -> optics objects
# ---------------------------------------------------------------------------

def study_material(study):
    """The Material a study traces with (preset or custom values)."""
    preset = _materials.PRESETS.get(study.MaterialPreset)
    if (preset is not None and preset.n_d == study.RefractiveIndex
            and preset.dispersion == study.Dispersion):
        return preset
    return _materials.Material(
        "%s (custom)" % study.MaterialPreset, study.RefractiveIndex,
        study.Dispersion)


def study_lighting(study):
    """The lighting model a study traces with (with head shadow, if on)."""
    name = study.LightingModel
    if name == "Cosine dome":
        base = _lighting.CosineDome()
    elif name == "Ring light":
        base = _lighting.RingLight(study.RingLightLow, study.RingLightHigh)
    else:
        base = _lighting.UniformHemisphere()
    if study.HeadShadowDeg > 0.0:
        return _lighting.HeadShadow(base, study.HeadShadowDeg)
    return base


def _input_signature(study):
    """The input-property tuple that participates in the fingerprint."""
    return repr((
        round(study.RefractiveIndex, 9), round(study.Dispersion, 9),
        study.LightingModel, round(study.RingLightLow, 6),
        round(study.RingLightHigh, 6), round(study.HeadShadowDeg, 6),
        study.GridResolution, round(study.TiltMaxDeg, 6), study.TiltSteps,
        study.MaxDepth, study.MinEnergy, study.Wavelengths,
        # Added in 4c; extending the tuple flags pre-4c results stale
        # once, which is correct (they predate absorption support).
        round(study.AbsorptionPerMM, 9),
    ))


def geometry_fingerprint(gem, study):
    """Hash of the sorted, rounded (n, d, tier-id) plane set plus the
    study's input properties (DESIGN_OPTICS.md section 7)."""
    try:
        poly = extract_polytope(gem)
    except PolytopeError as err:
        return "invalid: %s" % err
    planes = np.column_stack([
        np.round(poly.normals, 9), np.round(poly.dists, 6),
        poly.tier_ids.astype(np.float64)])
    # Normalize signed zeros: round() yields -0.0 from tiny negatives, and
    # B-Rep reload can flip that sign — equal numbers, different bytes
    # (verified: this alone broke fingerprint stability across save/load).
    planes = planes + 0.0
    order = np.lexsort(planes.T)
    digest = hashlib.sha1()
    digest.update(planes[order].tobytes())
    digest.update(_input_signature(study).encode("utf-8"))
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Running a study (manual; callable headless)
# ---------------------------------------------------------------------------

class ResultsSheetProxy:
    """Proxy for the results-sheet object: a tree handle for the study's
    stored results. Double-clicking it opens the results dock; it carries
    no geometry of its own (the numbers and maps live on the study)."""

    Type = "Lapidary::OpticsResultsSheet"

    def __init__(self, obj):
        obj.Proxy = self
        if not hasattr(obj, "Study"):
            obj.addProperty("App::PropertyLink", "Study", "Results",
                            "The optics study whose results this opens")

    def onDocumentRestored(self, obj):
        pass

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_results_sheet(obj):
    proxy = getattr(obj, "Proxy", None)
    return getattr(proxy, "Type", None) == "Lapidary::OpticsResultsSheet"


def results_sheet_of(study):
    """The study's results-sheet object, or None."""
    for obj in study.Document.Objects:
        if is_results_sheet(obj) and getattr(obj, "Study", None) is study:
            return obj
    return None


def _ensure_results_sheet(study):
    """Create the study's results-sheet tree object if it is missing."""
    sheet = results_sheet_of(study)
    if sheet is not None:
        return sheet
    obj = study.Document.addObject("App::FeaturePython", "ResultsSheet")
    ResultsSheetProxy(obj)
    obj.Study = study
    obj.Label = "Results"
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        from freecad.lapidary.optics.viewproviders import (
            ViewProviderResultsSheet)
        ViewProviderResultsSheet(obj.ViewObject)
    return obj


def run_study(study, progress=None):
    """Execute the study and store its results in the document.

    ``progress(fraction) -> bool`` is called throughout; returning False
    cancels via TraceCancelled (results are left untouched, study stays
    stale). Raises PolytopeError with an actionable message when the gem
    cannot be traced.
    """
    gem = gem_feature.find_gem(study)
    if gem is None:
        raise PolytopeError(
            "%s is not inside a Gem; create studies with "
            "Lapidary_OpticsStudy." % study.Label)
    poly = extract_polytope(gem)
    material = study_material(study)
    light = study_lighting(study)
    n_d = material.n(_materials.WAVELENGTH_D)

    trace_kwargs = dict(
        resolution=study.GridResolution, max_depth=study.MaxDepth,
        min_energy=study.MinEnergy,
        absorption_per_mm=study.AbsorptionPerMM)

    fire_samples = (0 if study.Wavelengths == "1"
                    else int(study.Wavelengths))
    steps = 1 + max(int(study.TiltSteps), 0) + (1 if fire_samples else 0)

    def stage_progress(stage, span=1.0):
        if progress is None:
            return None
        return lambda frac: progress((stage + frac * span) / steps)

    result = _tracer.trace(poly, n_d, light,
                           progress=stage_progress(0), **trace_kwargs)

    tilt_angles = np.linspace(0.0, float(study.TiltMaxDeg),
                              max(int(study.TiltSteps), 0))
    tilt_values = []
    tilt_results = []
    runtime = result.runtime_s
    for i, tilt in enumerate(tilt_angles):
        if tilt == 0.0:
            # The face-up trace above is exactly the tilt-0 sample.
            tilt_values.append(_metrics.brightness_pct(result))
            tilt_results.append(result)
            continue
        tilt_result = _tracer.trace(
            poly, n_d, light, tilt_deg=float(tilt),
            progress=stage_progress(1 + i), **trace_kwargs)
        tilt_values.append(_metrics.brightness_pct(tilt_result))
        tilt_results.append(tilt_result)
        runtime += tilt_result.runtime_s

    fire_result = None
    if fire_samples:
        from freecad.lapidary.optics import fire as _fire
        fire_result = _fire.fire_analysis(
            poly, material, lighting=light,
            wavelengths=_fire.wavelength_samples(fire_samples),
            progress=stage_progress(steps - 1), **trace_kwargs)
        runtime += sum(r.runtime_s for r in fire_result.results)

    study.LightReturnPct = _metrics.brightness_pct(result)
    study.LeakPct = _metrics.leak_pct(result)
    study.PrunedPct = _metrics.pruned_pct(result)
    study.MeanPathLength = _metrics.mean_path_length(result)
    study.MaxPathLength = result.max_path_length
    study.TiltAngles = [float(t) for t in tilt_angles]
    study.TiltBrightness = [float(v) for v in tilt_values]
    study.RuntimeS = float(runtime)
    summary = _metrics.summary_text(result, material)
    if study.AbsorptionPerMM > 0.0:
        summary += ("\n\nAbsorption (APPROXIMATE single-coefficient "
                    "Beer-Lambert body color): alpha = %g per mm, "
                    "%.1f %% of incident energy absorbed."
                    % (study.AbsorptionPerMM,
                       100.0 * float(np.mean(
                           result.absorbed[result.hit_mask]))
                       if result.num_hit else 0.0))
    if tilt_values:
        summary += "\n\nTilt curve (deg -> brightness %):\n" + "\n".join(
            "  %5.1f -> %5.1f" % (t, v)
            for t, v in zip(tilt_angles, tilt_values))

    if fire_result is not None:
        from freecad.lapidary.optics.fire import FIRE_DEFINITION
        study.FireIndex = fire_result.fire_index
        study.WavelengthsNm = [float(w)
                               for w in fire_result.wavelengths_nm]
        study.WavelengthBrightness = [
            float(v) for v in fire_result.brightness_by_wavelength]
        summary += ("\n\nFire: Lapidary Fire Index = %.3f deg\n%s\n"
                    "Per-wavelength brightness:\n%s" % (
                        fire_result.fire_index, FIRE_DEFINITION,
                        "\n".join("  %.1f nm -> %5.1f %%" % (w, v)
                                  for w, v in zip(
                                      fire_result.wavelengths_nm,
                                      fire_result.brightness_by_wavelength))))
    else:
        study.FireIndex = 0.0
        study.WavelengthsNm = []
        study.WavelengthBrightness = []
    study.ResultSummary = summary

    rows = _metrics.tier_table(result)
    study.TierNames = [r["tier"] for r in rows]
    study.TierReturnPct = [r["return_pct"] for r in rows]
    study.TierLeakPct = [r["leak_pct"] for r in rows]

    _store_maps(study, result, tilt_results, tilt_angles, tilt_values,
                fire_result)

    _ensure_results_sheet(study)

    study.Fingerprint = geometry_fingerprint(gem, study)
    study.Stale = False
    return result


#: PropertyFileIncluded property -> file name written by run_study.
MAP_PROPERTIES = {
    "BrightnessMapFile": "brightness.png",
    "ClassificationMapFile": "classification.png",
    "TiltMapsFile": "tilt_maps.png",
    "TiltCurveFile": "tilt_curve.png",
    "SpreadMapFile": "fire_spread.png",
}


def _store_maps(study, result, tilt_results, tilt_angles, tilt_values,
                fire_result=None):
    """Render the result maps and embed them via PropertyFileIncluded.

    Assigning a path to a PropertyFileIncluded copies the file into the
    document's transient store (verified on 1.1), so the temp directory
    can be discarded immediately afterwards.
    """
    from freecad.lapidary.optics import imaging
    maps = imaging.render_study_maps(
        result, tilt_results=tilt_results, tilt_angles=list(tilt_angles),
        tilt_values=list(tilt_values), fire_result=fire_result)
    with tempfile.TemporaryDirectory(prefix="lapidary_maps_") as tmp:
        for prop, filename in MAP_PROPERTIES.items():
            data = maps.get(filename)
            if data is None:
                continue
            path = os.path.join(tmp, filename)
            with open(path, "wb") as stream:
                stream.write(data)
            setattr(study, prop, path)
