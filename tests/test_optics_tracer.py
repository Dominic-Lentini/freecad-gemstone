# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tracer physics invariants and closed-form analytic fixtures
(DESIGN_OPTICS.md section 10).

Every expected number is either hand-computable (Fresnel cases) or derived
in a comment as a closed form (slab series, right-angle prism, windowing
wedge) — never a recorded output of the tracer itself. No FreeCAD needed.
"""

import math

import numpy as np
import pytest

import optics_fixtures as fx
from freecad.lapidary.optics import lighting, metrics
from freecad.lapidary.optics import tracer as tr


QUARTZ_N = 1.54       # the SRB design's target R.I.


# ---------------------------------------------------------------------------
# Fresnel unit tests against hand-computable cases
# ---------------------------------------------------------------------------

class TestFresnel:
    def test_normal_incidence(self):
        # R = ((n1 - n2) / (n1 + n2))^2 -> (0.5 / 2.5)^2 = 0.04 for 1 -> 1.5.
        R, cos_t, tir = tr.fresnel_unpolarized(1.0, 1.5, np.array([1.0]))
        assert R[0] == pytest.approx(0.04, abs=1e-12)
        assert cos_t[0] == pytest.approx(1.0)
        assert not tir[0]

    def test_brewster_angle_kills_rp(self):
        # At theta_B = atan(n2/n1), Rp = 0, so R = Rs / 2. Rs at Brewster:
        # with n1=1, n2=1.5: theta_B = 56.31 deg, theta_t = 90 - theta_B;
        # Rs = ((cos_i * n1 - n2 cos_t)/(cos_i * n1 + n2 cos_t))^2 —
        # computed longhand below rather than asserted from memory.
        n1, n2 = 1.0, 1.5
        theta_b = math.atan(n2 / n1)
        cos_i = math.cos(theta_b)
        sin_t = (n1 / n2) * math.sin(theta_b)
        cos_t = math.sqrt(1.0 - sin_t ** 2)
        rs = ((n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)) ** 2
        R, _cos_t, _tir = tr.fresnel_unpolarized(n1, n2, np.array([cos_i]))
        assert R[0] == pytest.approx(rs / 2.0, abs=1e-12)

    def test_reflectance_approaches_one_at_the_critical_angle(self):
        # The approach is sqrt-shaped (R ~ 1 - c*sqrt(theta_c - theta)),
        # so assert monotone growth toward 1 and near-1 very close in.
        n1, n2 = 1.5, 1.0
        theta_c = math.asin(n2 / n1)
        offsets = np.array([1e-2, 1e-4, 1e-6, 1e-9])
        R, _cos_t, tir = tr.fresnel_unpolarized(
            n1, n2, np.cos(theta_c - offsets))
        assert not np.any(tir)
        assert np.all(np.diff(R) > 0.0)
        assert R[-1] > 0.999

    def test_tir_at_and_beyond_the_critical_angle(self):
        n1, n2 = 1.5, 1.0
        theta_c = math.asin(n2 / n1)
        cos_at = math.cos(theta_c)
        cos_beyond = math.cos(theta_c + 0.2)
        R, _cos_t, tir = tr.fresnel_unpolarized(
            n1, n2, np.array([cos_at, cos_beyond]))
        assert bool(tir[0]) and bool(tir[1])
        assert R[0] == 1.0 and R[1] == 1.0

    def test_reflectance_bounded(self):
        rng = np.random.default_rng(7)
        cos_i = rng.uniform(0.0, 1.0, 256)
        for n1, n2 in ((1.0, 1.54), (1.54, 1.0), (1.0, 2.417), (2.417, 1.0)):
            R, _c, _t = tr.fresnel_unpolarized(n1, n2, cos_i)
            assert np.all((R >= 0.0) & (R <= 1.0))


# ---------------------------------------------------------------------------
# Energy conservation
# ---------------------------------------------------------------------------

class TestEnergyLedger:
    @pytest.mark.parametrize("n_gem", [1.54, 1.76, 2.417])
    def test_delivered_plus_escaped_plus_pruned_is_one(self, n_gem):
        result = tr.trace(fx.srb_polytope(), n_gem, resolution=32)
        hits = result.hit_mask
        assert result.num_hit > 300     # the SRB fills most of the grid
        total = (result.delivered + result.leaked + result.pruned)[hits]
        assert np.allclose(total, 1.0, atol=1e-9)

    def test_tier_sums_match_the_ledger(self):
        result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32)
        assert float(np.sum(result.tier_return)) == pytest.approx(
            float(np.sum(result.delivered)), abs=1e-9)
        assert float(np.sum(result.tier_leak)) == pytest.approx(
            float(np.sum(result.leaked)), abs=1e-9)


# ---------------------------------------------------------------------------
# Closed-form analytic fixtures
# ---------------------------------------------------------------------------

class TestSlabSeries:
    def test_normal_incidence_geometric_series(self):
        """Box gem at normal incidence: with R the single-surface normal
        reflectance and T = 1 - R, the ray bounces vertically between the
        two horizontal faces losing T of the remainder at each surface:

            transmitted (down) = T^2 (1 + R^2 + R^4 + ...) = T^2 / (1-R^2)
            reflected (up)     = R + T^2 R (1 + R^2 + ...) = R + T^2 R/(1-R^2)

        (sum = 1). Asserted against those expressions, not recorded values.
        """
        n = 1.5
        R0 = ((n - 1.0) / (n + 1.0)) ** 2                # 0.04 for n = 1.5
        T0 = 1.0 - R0
        expect_down = T0 ** 2 / (1.0 - R0 ** 2)
        expect_up = R0 + T0 ** 2 * R0 / (1.0 - R0 ** 2)
        assert expect_down + expect_up == pytest.approx(1.0, abs=1e-15)

        result = tr.trace(fx.slab_polytope(), n, resolution=16,
                          max_depth=64, min_energy=1e-12)
        hits = result.hit_mask
        assert np.any(hits)
        assert np.allclose(result.leaked[hits], expect_down, atol=1e-9)
        assert np.allclose(result.delivered[hits], expect_up, atol=1e-9)
        assert np.all(result.pruned[hits] < 1e-9)
        # Uniform hemisphere: brightness = upward energy exactly.
        assert np.allclose(result.brightness[hits], expect_up, atol=1e-9)

    def test_normal_incidence_path_length_series(self):
        """Path-length accumulator closed form for the same slab: with
        thickness t, the k-th downward escape travelled (2k+1)t, the k-th
        upward internal escape (2k+2)t, and the external reflection 0. So
        the per-pixel energy-weighted path sum is

            sum(e_i * L_i) = T^2 t [ sum R^{2k}(2k+1) + R sum R^{2k}(2k+2) ]

        and with x = R^2: sum x^k (2k+1) = 2x/(1-x)^2 + 1/(1-x),
        sum x^k (2k+2) = 2x/(1-x)^2 + 2/(1-x).
        """
        n = 1.5
        t = 1.0                          # slab thickness = 2 * half_thickness
        R0 = ((n - 1.0) / (n + 1.0)) ** 2
        T0 = 1.0 - R0
        x = R0 ** 2
        s_odd = 2.0 * x / (1.0 - x) ** 2 + 1.0 / (1.0 - x)
        s_even = 2.0 * x / (1.0 - x) ** 2 + 2.0 / (1.0 - x)
        expect_sum = T0 ** 2 * t * (s_odd + R0 * s_even)

        result = tr.trace(fx.slab_polytope(half_thickness=t / 2.0), n,
                          resolution=16, max_depth=64, min_energy=1e-12)
        hits = result.hit_mask
        # Tolerance: the epsilon nudge (~3e-7 mm here) shifts each bounce
        # point slightly, and the discrepancy accumulates over the ~40
        # bounces the 1e-12 energy floor allows — 1e-5 mm covers it.
        assert np.allclose(result.path_length_sum[hits], expect_sum,
                           atol=1e-5)
        # All escaping energy is 1 per pixel, so the metric equals the sum.
        assert metrics.mean_path_length(result) == pytest.approx(
            expect_sum, abs=1e-5)
        # The longest escaping branch is bounded by depth * thickness and
        # is at least the straight-through pass.
        assert t <= result.max_path_length <= 64 * t


class TestRightAnglePrism:
    def test_golden_bounce_sequence(self):
        """Hand-derived path for n > sqrt(2): straight down through the top
        face (undeviated), 45 deg incidence on the hypotenuse -> TIR
        (sin 45 = 0.707 > 1/1.6 = 0.625), reflected to +X, exits the leg
        face at normal incidence traveling exactly (1, 0, 0)."""
        poly = fx.prism_polytope()
        n_gem = 1.6
        o = np.array([[0.5, 0.0, 5.0]])
        v = np.array([[0.0, 0.0, -1.0]])
        hit, t_in, face_in = poly.entry_hits(o, v)
        assert bool(hit[0]) and face_in[0] == 0          # top face
        p = o + t_in[:, None] * v                        # (0.5, 0, 1)
        # Normal incidence: enters undeviated.
        t1, f1 = poly.exit_hits(p - 1e-9 * poly.normals[0], v)
        assert f1[0] == 2                                # hypotenuse
        cos_i = np.sum(v * poly.normals[f1], axis=1)
        assert cos_i[0] == pytest.approx(1.0 / math.sqrt(2.0))
        _R, _ct, tir = tr.fresnel_unpolarized(n_gem, 1.0, cos_i)
        assert bool(tir[0])                              # 45 deg > theta_c
        p1 = (p - 1e-9 * poly.normals[0]) + t1[:, None] * v
        v2 = tr.reflect(v, poly.normals[f1])
        assert v2[0] == pytest.approx([1.0, 0.0, 0.0])
        t2, f2 = poly.exit_hits(p1 - 1e-9 * poly.normals[f1[0]], v2)
        assert f2[0] == 1                                # leg x = 1
        cos_i2 = np.sum(v2 * poly.normals[f2], axis=1)
        assert cos_i2[0] == pytest.approx(1.0)           # normal incidence
        _R2, _ct2, tir2 = tr.fresnel_unpolarized(n_gem, 1.0, cos_i2)
        assert not bool(tir2[0])                         # exits at (1, 0, 0)

    def test_closed_form_energy_split(self):
        """Every interior path repeats the period (hypotenuse TIR, leg
        exit, hypotenuse TIR, top exit). With R the normal-incidence
        reflectance and E0 = 1 - R the energy refracted in:

            leg exits (horizontal, not upward)   = E0 (1-R) sum R^{2k}
                                                 = E0 / (1 + R)
            top exits (straight up)              = E0 R (1-R) / (1 - R^2)
                                                 = E0 R / (1 + R)
            delivered = R + E0 R / (1 + R);  leaked = E0 / (1 + R).
        """
        n_gem = 1.6
        R0 = ((n_gem - 1.0) / (n_gem + 1.0)) ** 2
        E0 = 1.0 - R0
        expect_delivered = R0 + E0 * R0 / (1.0 + R0)
        expect_leaked = E0 / (1.0 + R0)
        assert expect_delivered + expect_leaked == pytest.approx(1.0)

        poly = fx.prism_polytope()
        result = tr.trace(poly, n_gem, resolution=32, max_depth=64,
                          min_energy=1e-12)
        # Interior pixels only: stay away from edges and corners.
        R = result.resolution
        coords = (np.arange(R) + 0.5) / R * 2 * result.extent - result.extent
        xs, ys = np.meshgrid(coords, coords)
        interior = (result.hit_mask & (np.abs(xs) < 0.9) & (np.abs(ys) < 0.9))
        assert np.sum(interior) > 50
        assert np.allclose(result.delivered[interior], expect_delivered,
                           atol=1e-9)
        assert np.allclose(result.leaked[interior], expect_leaked, atol=1e-9)


class TestWindowingWedge:
    """A two-facet wedge pavilion windows below the critical angle.

    A ray straight down through the table meets a pavilion facet at
    incidence angle a (the wedge's pavilion angle). For a >= theta_c =
    asin(1/n) it is totally internally reflected (and the reflected ray
    meets the *other* facet at 180 - 3a > theta_c for these angles, so it
    stays inside and eventually returns upward). For a < theta_c most of
    the energy refracts straight out of the pavilion — the face-up center
    windows. The transition is at exactly theta_c up to the width of the
    Fresnel shoulder (reflectance climbs to 1 within ~1 degree of
    theta_c), so the observed 50 % crossover must sit within 1 degree of
    theta_c.
    """

    N = 1.54
    THETA_C = math.degrees(math.asin(1.0 / N))       # 40.49 deg for n=1.54

    def _center_leak(self, angle_deg):
        poly = fx.wedge_polytope(angle_deg)
        result = tr.trace(poly, self.N, resolution=32)
        c = result.resolution // 2
        assert result.hit_mask[c, c]
        return result.leaked[c, c], result.class_map[c, c]

    def test_windows_below_critical(self):
        leak, cls = self._center_leak(self.THETA_C - 2.0)
        assert leak > 0.5
        assert cls == tr.CLASS_WINDOW

    def test_returns_above_critical(self):
        leak, cls = self._center_leak(self.THETA_C + 2.0)
        assert leak < 0.5
        assert cls != tr.CLASS_WINDOW

    def test_transition_angle_matches_theta_c(self):
        angles = np.arange(self.THETA_C - 3.0, self.THETA_C + 3.0, 0.5)
        leaks = np.array([self._center_leak(a)[0] for a in angles])
        crossing = angles[np.argmax(leaks < 0.5)]     # first non-windowing
        assert abs(crossing - self.THETA_C) <= 1.0

    def test_leak_attributed_to_the_pavilion_tier(self):
        poly = fx.wedge_polytope(self.THETA_C - 2.0)
        result = tr.trace(poly, self.N, resolution=32)
        rows = {r["tier"]: r for r in metrics.tier_table(result)}
        assert rows["Pavilion wedge"]["leak_pct"] > 40.0
        assert rows["Pavilion wedge"]["leak_pct"] > rows[
            "Pavilion wedge"]["return_pct"]


class TestAbsorption:
    """Beer-Lambert body color (Phase 4c): approximate, off by default,
    applied per escaping branch over its recorded internal path length."""

    def test_off_by_default_and_zero_alpha_identical(self):
        base = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32)
        explicit = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32,
                            absorption_per_mm=0.0)
        assert base.absorption_per_mm == 0.0
        assert np.all(base.absorbed == 0.0)
        assert base.brightness.tobytes() == explicit.brightness.tobytes()

    def test_extended_ledger_conserves_energy(self):
        result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32,
                          absorption_per_mm=0.05)
        hits = result.hit_mask
        total = (result.delivered + result.leaked + result.pruned
                 + result.absorbed)[hits]
        assert np.allclose(total, 1.0, atol=1e-9)
        assert float(np.sum(result.absorbed[hits])) > 0.0

    def test_more_absorption_less_light(self):
        """Monotonicity (phase prompt): longer path or higher alpha means
        more attenuation, so brightness falls and absorbed energy rises
        as alpha grows."""
        values = []
        absorbed = []
        for alpha in (0.0, 0.02, 0.1, 0.5):
            result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32,
                              absorption_per_mm=alpha)
            values.append(metrics.brightness_pct(result))
            absorbed.append(float(np.sum(result.absorbed)))
        assert values == sorted(values, reverse=True)
        assert absorbed == sorted(absorbed)

    def test_slab_closed_form_with_absorption(self):
        """The slab series with attenuation: the k-th downward escape
        carries T^2 R^{2k} e^{-a(2k+1)t}, the k-th upward internal escape
        T^2 R^{2k+1} e^{-a(2k+2)t}, the external reflection R unattenuated.
        Geometric sums with q = R^2 e^{-2at}:

            leaked    = T^2 e^{-at} / (1 - q)
            delivered = R + T^2 R e^{-2at} / (1 - q)
            absorbed  = 1 - delivered - leaked   (as min_energy -> 0)
        """
        n, t, a = 1.5, 1.0, 0.3
        R0 = ((n - 1.0) / (n + 1.0)) ** 2
        T0 = 1.0 - R0
        q = R0 ** 2 * math.exp(-2.0 * a * t)
        expect_down = T0 ** 2 * math.exp(-a * t) / (1.0 - q)
        expect_up = R0 + T0 ** 2 * R0 * math.exp(-2.0 * a * t) / (1.0 - q)

        result = tr.trace(fx.slab_polytope(half_thickness=t / 2.0), n,
                          resolution=16, max_depth=64, min_energy=1e-12,
                          absorption_per_mm=a)
        hits = result.hit_mask
        assert np.allclose(result.leaked[hits], expect_down, atol=1e-9)
        assert np.allclose(result.delivered[hits], expect_up, atol=1e-9)
        assert np.allclose(result.absorbed[hits],
                           1.0 - expect_up - expect_down, atol=1e-9)

    def test_best_exit_branch_is_recorded(self):
        result = tr.trace(fx.slab_polytope(), 1.5, resolution=16)
        hits = result.hit_mask
        # The slab's dominant branch is the straight-through transmission
        # (energy T^2 = 0.9216), heading straight down.
        T0 = 1.0 - ((1.5 - 1.0) / (1.5 + 1.0)) ** 2
        assert np.allclose(result.best_exit_energy[hits], T0 ** 2,
                           atol=1e-9)
        assert np.allclose(result.best_exit_dir[hits],
                           [0.0, 0.0, -1.0], atol=1e-9)
        assert np.all(result.best_exit_energy[~hits] == 0.0)


# ---------------------------------------------------------------------------
# Symmetry (SRB is 8-fold symmetric)
# ---------------------------------------------------------------------------

class TestSymmetry:
    def test_brightness_map_is_fourfold_symmetric(self):
        """The 8-fold SRB is in particular invariant under 90 deg rotation,
        and rot90 maps the pixel grid onto itself exactly. Plane constants
        at symmetric azimuths agree only to float rounding, so a handful of
        decision-boundary pixels may flip; the mass of the map must agree
        tightly."""
        result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=64)
        diff = np.abs(result.brightness - np.rot90(result.brightness))
        assert float(np.quantile(diff, 0.99)) < 1e-6
        assert float(np.mean(diff)) < 1e-4

    def test_tilt_curve_matches_across_symmetric_azimuths(self):
        poly = fx.srb_polytope()
        values = []
        for az in (0.0, 90.0):
            result = tr.trace(poly, QUARTZ_N, resolution=48, tilt_deg=10.0,
                              tilt_azimuth_deg=az)
            values.append(metrics.brightness_pct(result))
        assert values[0] == pytest.approx(values[1], abs=0.1)


# ---------------------------------------------------------------------------
# Metrics plumbing
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_percentages_are_consistent(self):
        result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=32)
        b = metrics.brightness_pct(result)
        leak = metrics.leak_pct(result)
        pruned = metrics.pruned_pct(result)
        assert 0.0 < b < 100.0
        assert 0.0 < leak < 100.0
        # Uniform hemisphere: brightness <= delivered share, and the
        # ledger rows account for everything.
        rows = metrics.tier_table(result)
        total = sum(r["return_pct"] + r["leak_pct"] for r in rows) + pruned
        assert total == pytest.approx(100.0, abs=1e-6)

    def test_tilt_curve_shape(self):
        tilts, values = metrics.tilt_curve(
            fx.srb_polytope(), QUARTZ_N, tilt_max_deg=20.0, tilt_steps=3,
            resolution=16)
        assert list(tilts) == [0.0, 10.0, 20.0]
        assert len(values) == 3
        assert np.all((values >= 0.0) & (values <= 100.0))

    def test_summary_text_restates_definitions(self):
        from freecad.lapidary.optics import materials
        result = tr.trace(fx.srb_polytope(), QUARTZ_N, resolution=16)
        text = metrics.summary_text(result, materials.PRESETS["Quartz"])
        assert "Light return" in text
        assert "not comparable" in text
        assert "mean of the 1.544" in text     # birefringence note surfaces

    def test_head_shadow_energy_and_brightness(self):
        # A slab returns its delivered energy straight up: with a
        # near-hemisphere head cone all of that is head-shadowed, so the
        # brightness is 0 — but the *dominant* destination is still the
        # 92 % that leaks out of the bottom, so the class stays WINDOW.
        light = lighting.HeadShadow(lighting.UniformHemisphere(),
                                    half_angle_deg=89.0)
        result = tr.trace(fx.slab_polytope(), 1.5, lighting=light,
                          resolution=16)
        hits = result.hit_mask
        assert np.allclose(result.head_energy[hits],
                           result.delivered[hits], atol=1e-12)
        assert np.allclose(result.brightness[hits], 0.0, atol=1e-12)
        assert np.all(result.class_map[hits] == tr.CLASS_WINDOW)

    def test_head_shadow_dominant_classification(self):
        # The wedge above the critical angle returns most energy upward;
        # with a near-hemisphere head cone that return is head shadow, so
        # the center pixel classifies HEAD.
        poly = fx.wedge_polytope(TestWindowingWedge.THETA_C + 2.0)
        light = lighting.HeadShadow(lighting.UniformHemisphere(),
                                    half_angle_deg=89.0)
        result = tr.trace(poly, TestWindowingWedge.N, lighting=light,
                          resolution=32)
        c = result.resolution // 2
        assert result.class_map[c, c] == tr.CLASS_HEAD
