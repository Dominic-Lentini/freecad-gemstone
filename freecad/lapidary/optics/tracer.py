# SPDX-License-Identifier: LGPL-2.1-or-later
"""The vectorized reverse ray tracer (DESIGN_OPTICS.md section 4).

Direction: *reverse* tracing, from the observer. A view grid of parallel
rays (face-up along -Z toward the crown) is traced into the stone; tilt
rotates the grid and the lighting frame, never the geometry. Deterministic:
identical inputs give identical outputs bit-for-bit (pure numpy, no RNG).

Frames. The *stone frame* is the document frame (+Z crown). The *view
frame* has +Z pointing from the stone toward the observer; lighting models
are evaluated in the view frame. A tilt of ``tilt_deg`` about the azimuth
``tilt_azimuth_deg`` maps view-frame vectors into the stone frame by the
rotation ``M = Rz(az) @ Ry(tilt) @ Rz(-az)``; stone-frame escape directions
map back with the transpose.

Ray splitting with energy accounting. Each interface event spawns a
reflected and a refracted branch carrying R and 1-R of the parent's energy
(unpolarized Fresnel, R = (Rs + Rp) / 2, vector forms). On a *convex* stone
a branch that refracts out can never re-enter, so the escaping branch is
terminal and is accumulated immediately; only the internally reflected
branch continues. The "batch stack" is therefore a flat array of ray states
advanced one bounce per iteration — no recursion, no growth.

Energy ledger, per primary ray: ``delivered`` (escaped into the upward view
hemisphere, including the first-surface reflection), ``escaped`` (exited
downward, past the stone), ``pruned`` (dropped below MinEnergy or beyond
MaxDepth). delivered + escaped + pruned = 1 within float tolerance —
asserted by the test suite.

Pixel classification (window/leak map) is by dominant-energy destination:
LIT — the pixel's energy mostly returns from the lighting environment;
HEAD — mostly returns inside the observer head-shadow cone (contrast);
WINDOW — mostly exits the pavilion side into the background.

Per-tier attribution: branch energy is attributed to the tier of the
*first pavilion interaction* of its ray path (the entry event counts when
the entry face itself is a pavilion facet); energy that never touches a
pavilion facet lands in the "(none)" bucket.

Per-branch path length (DESIGN_OPTICS.md section 4, recorded from 4a,
consumed by 4c absorption): every branch carries the cumulative geometric
distance travelled *inside* the stone; an escaping branch's length is
final at escape (the first-surface reflection has length 0). Recorded as
the per-pixel energy-weighted sum over escaping branches plus the global
maximum.

Beer-Lambert absorption (Phase 4c, ``absorption_per_mm``, off by
default): an APPROXIMATE single-coefficient body-color model. Each
escaping branch is attenuated by ``exp(-alpha * path_length)`` at escape;
the absorbed remainder is tallied per pixel, extending the ledger to
delivered + escaped + pruned + absorbed = 1. Approximations, documented
deliberately: pruned branches are tallied unattenuated (their paths were
only partly travelled), and in-flight energy is not attenuated between
bounces — the coefficient is a body-color knob, not a spectrometer.

Fire support (Phase 4c): per pixel, the *highest-energy escaping branch
that travelled inside the stone* (path length > 0) has its view-frame
exit direction and energy recorded; the Lapidary Fire Index
(optics/fire.py) measures the angular spread of these directions between
the red and violet wavelength extremes. The first-surface reflection is
excluded by that path-length condition: it never refracts, so its
direction is identical at every wavelength — including it would only mix
achromatic spread-zero glints into a dispersion metric (observed: it
inverted the diamond-vs-quartz ordering on a design cut for R.I. 1.54,
where diamond's interior branches are TIR-shredded and the surface glint
outweighs them).

Pure numpy; importable headless; no FreeCAD imports.
"""

import math
import time
from dataclasses import dataclass, field

import numpy as np

from freecad.lapidary.optics.lighting import HeadShadow, UniformHemisphere

__all__ = [
    "TraceCancelled",
    "TraceResult",
    "trace",
    "fresnel_unpolarized",
    "reflect",
    "view_rotation",
    "CLASS_MISS",
    "CLASS_LIT",
    "CLASS_WINDOW",
    "CLASS_HEAD",
]

#: Pixel classes of the window/leak classification map.
CLASS_MISS = 0     # primary ray misses the stone
CLASS_LIT = 1      # dominant energy returns from the lighting environment
CLASS_WINDOW = 2   # dominant energy exits the pavilion side (window/leak)
CLASS_HEAD = 3     # dominant energy returns inside the head-shadow cone

DEFAULT_MAX_DEPTH = 32
DEFAULT_MIN_ENERGY = 1e-3


class TraceCancelled(Exception):
    """Raised when the progress callback asks to stop."""


# ---------------------------------------------------------------------------
# Interface physics (vector forms; unit-tested against hand-computable cases)
# ---------------------------------------------------------------------------

def fresnel_unpolarized(n1, n2, cos_i):
    """Unpolarized Fresnel reflectance for incidence cosine(s) ``cos_i``.

    Returns ``(R, cos_t, tir)``: reflectance (1.0 under total internal
    reflection), transmission cosine (0 where TIR), and the TIR mask.
    ``R = (Rs + Rp) / 2`` from the standard per-polarization formulas:

        Rs = ((n1 cos_i - n2 cos_t) / (n1 cos_i + n2 cos_t))^2
        Rp = ((n1 cos_t - n2 cos_i) / (n1 cos_t + n2 cos_i))^2
    """
    cos_i = np.asarray(cos_i, np.float64)
    sin_t2 = (n1 / n2) ** 2 * (1.0 - cos_i ** 2)
    tir = sin_t2 >= 1.0
    cos_t = np.sqrt(np.clip(1.0 - sin_t2, 0.0, None))
    rs = ((n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)) ** 2
    rp = ((n1 * cos_t - n2 * cos_i) / (n1 * cos_t + n2 * cos_i)) ** 2
    R = np.where(tir, 1.0, 0.5 * (rs + rp))
    return R, cos_t, tir


def reflect(v, n):
    """Specular reflection of directions ``v`` about unit normals ``n``."""
    v = np.atleast_2d(v)
    n = np.atleast_2d(n)
    return v - 2.0 * np.sum(v * n, axis=1, keepdims=True) * n


def _refract_in(v, n_out, mu, cos_i, cos_t):
    """Refracted direction entering through a face with outward normal
    ``n_out`` (``v . n_out < 0``, ``cos_i = -v . n_out``), ``mu = n1/n2``."""
    return mu * v + ((mu * cos_i - cos_t)[:, None]) * n_out


def _refract_out(v, n_out, mu, cos_i, cos_t):
    """Refracted direction exiting through a face with outward normal
    ``n_out`` (``v . n_out > 0``, ``cos_i = v . n_out``), ``mu = n1/n2``."""
    return mu * v - ((mu * cos_i - cos_t)[:, None]) * n_out


def view_rotation(tilt_deg, tilt_azimuth_deg=0.0):
    """View->stone rotation matrix ``Rz(az) @ Ry(tilt) @ Rz(-az)``."""
    t = math.radians(tilt_deg)
    a = math.radians(tilt_azimuth_deg)
    ct, st = math.cos(t), math.sin(t)
    ca, sa = math.cos(a), math.sin(a)
    ry = np.array([[ct, 0.0, st], [0.0, 1.0, 0.0], [-st, 0.0, ct]])
    rz = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rz.T


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class TraceResult:
    """Everything one trace run produced. Maps are (R, R) arrays indexed
    ``[iy, ix]`` with x, y the view-frame grid axes and the pixel centers
    spanning [-extent, extent] in both."""

    resolution: int
    extent: float
    tilt_deg: float
    tilt_azimuth_deg: float
    n_gem: float
    max_depth: int
    min_energy: float
    lighting_description: str

    hit_mask: np.ndarray = None
    brightness: np.ndarray = None      # sum(branch energy * L(exit dir))
    class_map: np.ndarray = None       # CLASS_* codes
    delivered: np.ndarray = None       # energy escaped upward, per pixel
    leaked: np.ndarray = None          # energy escaped downward, per pixel
    pruned: np.ndarray = None          # energy dropped, per pixel
    head_energy: np.ndarray = None     # upward energy inside the head cone
    #: sum(branch energy * internal path length) over escaping branches,
    #: per pixel (mm); divide by delivered+leaked for the pixel's
    #: energy-weighted mean internal path.
    path_length_sum: np.ndarray = None
    #: longest internal path of any escaping branch (mm).
    max_path_length: float = 0.0
    #: Beer-Lambert coefficient this run used (0 = absorption off) and
    #: the per-pixel energy it removed.
    absorption_per_mm: float = 0.0
    absorbed: np.ndarray = None
    #: per pixel: energy and view-frame direction of the highest-energy
    #: escaping branch (fire analysis input; energy 0 where none escaped).
    best_exit_energy: np.ndarray = None
    best_exit_dir: np.ndarray = None   # (R, R, 3)

    #: Per-tier energy sums over all primary rays; index T = "(none)"
    #: (energy that never had a pavilion interaction).
    tier_labels: tuple = ()
    tier_return: np.ndarray = None
    tier_leak: np.ndarray = None

    runtime_s: float = 0.0

    @property
    def num_hit(self):
        return int(np.sum(self.hit_mask))


# ---------------------------------------------------------------------------
# The tracer
# ---------------------------------------------------------------------------

def trace(poly, n_gem, lighting=None, resolution=256, tilt_deg=0.0,
          tilt_azimuth_deg=0.0, max_depth=DEFAULT_MAX_DEPTH,
          min_energy=DEFAULT_MIN_ENERGY, batch_size=16384, progress=None,
          extent=None, absorption_per_mm=0.0):
    """Trace the full view grid through ``poly`` and return a TraceResult.

    ``poly``: an optics.polytope.Polytope; ``n_gem``: refractive index at
    the traced wavelength; ``lighting``: an optics.lighting model evaluated
    in the view frame (default UniformHemisphere). ``progress``, when given,
    is called between batches (and between bounce iterations) with the done
    fraction in [0, 1]; returning False cancels the run via TraceCancelled.
    ``extent`` overrides the half-width of the view grid (defaults to the
    polytope's bounding radius, which covers the silhouette at any tilt).
    """
    t_start = time.perf_counter()
    if lighting is None:
        lighting = UniformHemisphere()
    if n_gem <= 1.0:
        raise ValueError("gem refractive index must exceed 1, got %r" % n_gem)
    R = int(resolution)
    if R < 2:
        raise ValueError("resolution must be >= 2")

    rot = view_rotation(tilt_deg, tilt_azimuth_deg)   # view -> stone
    r_bound = poly.bounding_radius()
    half = float(extent) if extent is not None else r_bound
    eps = 1e-7 * r_bound

    # Pixel-center grid in the view frame; origins above the stone.
    coords = (np.arange(R) + 0.5) / R * (2.0 * half) - half
    xs, ys = np.meshgrid(coords, coords)              # [iy, ix]
    origins_view = np.stack(
        [xs.ravel(), ys.ravel(), np.full(R * R, 2.0 * r_bound + half)], axis=1)
    dir_view = np.array([0.0, 0.0, -1.0])
    origins = origins_view @ rot.T                    # rows: M @ o_view
    v0 = np.broadcast_to(rot @ dir_view, (R * R, 3)).copy()

    num_tiers = len(poly.tier_labels)
    face_tier = np.where(poly.tier_ids >= 0, poly.tier_ids, num_tiers)
    face_is_pav = np.array(
        [poly.tier_sides[t] == "Pavilion" if 0 <= t < num_tiers else False
         for t in poly.tier_ids])

    # Accumulators (flattened pixels).
    P = R * R
    brightness = np.zeros(P)
    delivered = np.zeros(P)
    leaked = np.zeros(P)
    pruned = np.zeros(P)
    head_energy = np.zeros(P)
    path_sum = np.zeros(P)
    max_path = np.zeros(1)             # array so deposit() can mutate it
    absorbed = np.zeros(P)
    best_e = np.zeros(P)
    best_dir = np.zeros((P, 3))
    alpha = float(absorption_per_mm)
    if alpha < 0.0:
        raise ValueError("absorption_per_mm must be >= 0, got %r" % alpha)
    hit_flat = np.zeros(P, dtype=bool)
    tier_return = np.zeros(num_tiers + 1)
    tier_leak = np.zeros(num_tiers + 1)

    is_head = (lambda d: lighting.in_cone(d)) if isinstance(
        lighting, HeadShadow) else (lambda d: np.zeros(len(d), dtype=bool))

    def deposit(pix, energy, exit_dirs_stone, exit_points, first_pav,
                path_lengths):
        """Terminal branches: query lighting, fill every accumulator.

        ``pix`` entries are unique within one call (one branch per primary
        ray per interface event), so plain fancy-index accumulation is
        safe; the tier sums use bincount because ``first_pav`` repeats.
        Lighting and its occluder are evaluated entirely in the view frame
        (both directions and origins) — the frozen Occluder contract.
        """
        if alpha > 0.0:
            # Beer-Lambert at escape (approximate; see module docstring).
            attenuated = energy * np.exp(-alpha * path_lengths)
            absorbed[pix] += energy - attenuated
            energy = attenuated
        dirs_view = exit_dirs_stone @ rot             # rot^T applied to rows
        L = lighting.intensity(dirs_view, origins=exit_points @ rot)
        brightness[pix] += energy * L
        # Fire input: best *dispersable* branch only (path > 0) — the
        # achromatic first-surface reflection is excluded, see docstring.
        better = (energy > best_e[pix]) & (path_lengths > 0.0)
        if np.any(better):
            idx = pix[better]
            best_e[idx] = energy[better]
            best_dir[idx] = dirs_view[better]
        up = dirs_view[:, 2] > 0.0
        e_up = np.where(up, energy, 0.0)
        e_down = energy - e_up
        delivered[pix] += e_up
        leaked[pix] += e_down
        head = up & is_head(dirs_view)
        head_energy[pix] += np.where(head, energy, 0.0)
        path_sum[pix] += energy * path_lengths
        if len(path_lengths):
            max_path[0] = max(max_path[0], float(np.max(path_lengths)))
        # Index-assign, not "+=": rebinding a closure name is a SyntaxError
        # trap; slice-accumulation mutates the outer arrays in place.
        tier_return[:] += np.bincount(first_pav, weights=e_up,
                                      minlength=num_tiers + 1)
        tier_leak[:] += np.bincount(first_pav, weights=e_down,
                                    minlength=num_tiers + 1)

    batches = range(0, P, int(batch_size))
    n_batches = len(batches)
    for b_i, start in enumerate(batches):
        sl = slice(start, min(start + int(batch_size), P))
        o = origins[sl]
        v = v0[sl]
        pix_all = np.arange(sl.start, sl.stop)

        hit, t_in, face_in = poly.entry_hits(o, v)
        hit_flat[pix_all] = hit
        if not np.any(hit):
            continue
        pix = pix_all[hit]
        o, v, t_in, face_in = o[hit], v[hit], t_in[hit], face_in[hit]
        p_hit = o + t_in[:, None] * v
        n = poly.normals[face_in]
        cos_i = -np.sum(v * n, axis=1)
        R0, cos_t, _tir = fresnel_unpolarized(1.0, n_gem, cos_i)

        # First pavilion interaction: the entry event itself, when the
        # entry face is a pavilion facet.
        first_pav = np.full(len(pix), num_tiers, dtype=np.intp)
        pav_entry = face_is_pav[face_in]
        first_pav[pav_entry] = face_tier[face_in[pav_entry]]

        # First-surface (external) reflection branch: terminal, and it
        # never travels inside — path length 0.
        deposit(pix, R0, reflect(v, n), p_hit, first_pav,
                np.zeros(len(pix)))

        # Refracted branch continues inside.
        e = 1.0 - R0
        v = _refract_in(v, n, 1.0 / n_gem, cos_i, cos_t)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        o = p_hit - eps * n
        depth = np.ones(len(pix), dtype=np.int32)
        pathlen = np.zeros(len(pix))       # cumulative internal distance

        # Prune before the first internal event too (a grazing entry can
        # leave less than MinEnergy inside) so the ledger stays exact.
        alive = e >= min_energy
        if not np.all(alive):
            np.add.at(pruned, pix[~alive], e[~alive])
            pix, o, v, e, depth, first_pav, pathlen = (
                pix[alive], o[alive], v[alive], e[alive], depth[alive],
                first_pav[alive], pathlen[alive])

        while len(pix):
            if progress is not None:
                frac = (b_i + float(depth[0]) / (max_depth + 1)) / n_batches
                if progress(min(frac, 1.0)) is False:
                    raise TraceCancelled()
            t_out, face = poly.exit_hits(o, v)
            p_hit = o + t_out[:, None] * v
            n = poly.normals[face]
            pathlen = pathlen + t_out      # directions are unit length

            newly_pav = (first_pav == num_tiers) & face_is_pav[face]
            first_pav[newly_pav] = face_tier[face[newly_pav]]

            cos_i = np.sum(v * n, axis=1)
            Rf, cos_t, tir = fresnel_unpolarized(n_gem, 1.0, cos_i)

            esc = ~tir
            if np.any(esc):
                exit_dir = _refract_out(
                    v[esc], n[esc], n_gem, cos_i[esc], cos_t[esc])
                exit_dir /= np.linalg.norm(exit_dir, axis=1, keepdims=True)
                deposit(pix[esc], e[esc] * (1.0 - Rf[esc]), exit_dir,
                        p_hit[esc], first_pav[esc], pathlen[esc])

            # Internally reflected branch continues for everyone.
            e = e * Rf
            v = reflect(v, n)
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            o = p_hit - eps * n
            depth += 1

            alive = (e >= min_energy) & (depth < max_depth)
            dead = ~alive
            if np.any(dead):
                np.add.at(pruned, pix[dead], e[dead])
            pix, o, v, e, depth, first_pav, pathlen = (
                pix[alive], o[alive], v[alive], e[alive], depth[alive],
                first_pav[alive], pathlen[alive])
        if progress is not None:
            if progress((b_i + 1.0) / n_batches) is False:
                raise TraceCancelled()

    # Classification by dominant destination (LIT excludes head returns).
    lit_energy = delivered - head_energy
    class_flat = np.full(P, CLASS_MISS, dtype=np.int8)
    stacked = np.stack([lit_energy, leaked, head_energy])
    winner = np.argmax(stacked, axis=0)
    codes = np.array([CLASS_LIT, CLASS_WINDOW, CLASS_HEAD], dtype=np.int8)
    class_flat[hit_flat] = codes[winner[hit_flat]]

    shape = (R, R)
    return TraceResult(
        resolution=R, extent=half, tilt_deg=float(tilt_deg),
        tilt_azimuth_deg=float(tilt_azimuth_deg), n_gem=float(n_gem),
        max_depth=int(max_depth), min_energy=float(min_energy),
        lighting_description=lighting.describe(),
        hit_mask=hit_flat.reshape(shape),
        brightness=brightness.reshape(shape),
        class_map=class_flat.reshape(shape),
        delivered=delivered.reshape(shape),
        leaked=leaked.reshape(shape),
        pruned=pruned.reshape(shape),
        head_energy=head_energy.reshape(shape),
        path_length_sum=path_sum.reshape(shape),
        max_path_length=float(max_path[0]),
        absorption_per_mm=alpha,
        absorbed=absorbed.reshape(shape),
        best_exit_energy=best_e.reshape(shape),
        best_exit_dir=best_dir.reshape(shape + (3,)),
        tier_labels=tuple(poly.tier_labels) + ("(none)",),
        tier_return=tier_return,
        tier_leak=tier_leak,
        runtime_s=time.perf_counter() - t_start,
    )
