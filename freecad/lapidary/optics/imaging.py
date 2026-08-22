# SPDX-License-Identifier: LGPL-2.1-or-later
"""Map rendering: TraceResult arrays -> PNG bytes (DESIGN_OPTICS.md
sections 7 and 8).

DESIGN_OPTICS.md section 7 offers QImage with a pure-Python fallback; this
module implements the pure-Python encoder as the *only* writer, because
the stored PNGs must be byte-deterministic (a section 10 requirement Qt
cannot promise across platforms and plugin sets) and the encoder is ~40
lines of stdlib ``zlib`` + ``struct``. Decision recorded in
docs/dev-notes.md.

Image conventions:

- Maps are rendered with view-frame +y pointing *up* the image (the
  TraceResult arrays are indexed [iy, ix] with iy increasing along +y, so
  rows are flipped for the PNG's top-down order).
- Pixels the primary ray misses are fully transparent.
- Classification colors (the legend, also exported for the dock):
  LIT near-white, WINDOW/LEAK steel blue, HEAD dark charcoal.

Pure Python + numpy; no FreeCAD, no Qt.
"""

import struct
import zlib

import numpy as np

from freecad.lapidary.optics import tracer as _tracer

__all__ = [
    "write_png",
    "brightness_image",
    "classification_image",
    "tilt_montage_image",
    "curve_image",
    "spread_image",
    "CLASS_COLORS",
    "CLASS_LEGEND",
]

#: RGBA per classification code (index = CLASS_* constant).
CLASS_COLORS = np.array([
    [0, 0, 0, 0],           # MISS: transparent
    [245, 243, 235, 255],   # LIT: near-white (returns environment light)
    [70, 110, 180, 255],    # WINDOW/LEAK: steel blue (exits the pavilion)
    [55, 55, 60, 255],      # HEAD: dark charcoal (observer shadow)
], dtype=np.uint8)

CLASS_LEGEND = (("LIT", "returns light from the environment"),
                ("WINDOW", "exits the pavilion side (window/leak)"),
                ("HEAD", "returns inside the observer head shadow"))


# ---------------------------------------------------------------------------
# Minimal deterministic PNG encoder (8-bit RGBA)
# ---------------------------------------------------------------------------

def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

def write_png(rgba):
    """Encode an (H, W, 4) uint8 array as PNG bytes.

    Filter type 0 on every scanline and a fixed zlib level, so identical
    arrays always produce identical bytes (map determinism, section 10).
    """
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("write_png expects (H, W, 4) uint8, got %r"
                         % (rgba.shape,))
    height, width = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b""))


def _flip(array):
    """Map array [iy, ix] (iy along +y) -> image rows (top-down)."""
    return array[::-1]


# ---------------------------------------------------------------------------
# Map images
# ---------------------------------------------------------------------------

def brightness_image(result):
    """Brightness map as (R, R, 4) uint8: grayscale ramp, misses
    transparent. Pixel value = round(255 * clip(brightness, 0, 1))."""
    value = np.clip(result.brightness, 0.0, 1.0)
    gray = np.round(255.0 * value).astype(np.uint8)
    rgba = np.stack([gray, gray, gray,
                     np.where(result.hit_mask, 255, 0).astype(np.uint8)],
                    axis=2)
    return _flip(rgba)


def classification_image(result):
    """Window/leak classification map, colored per CLASS_COLORS."""
    return _flip(CLASS_COLORS[result.class_map])


def tilt_montage_image(results, gap=2):
    """A horizontal strip of classification-shaded brightness maps, one
    per tilt step, separated by transparent gutters."""
    if not results:
        raise ValueError("tilt_montage_image needs at least one result")
    tiles = [brightness_image(r) for r in results]
    height = max(t.shape[0] for t in tiles)
    width = sum(t.shape[1] for t in tiles) + gap * (len(tiles) - 1)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    x = 0
    for tile in tiles:
        out[:tile.shape[0], x:x + tile.shape[1]] = tile
        x += tile.shape[1] + gap
    return out


def curve_image(xs, ys, width=320, height=200, y_max=100.0):
    """A minimal brightness-vs-tilt line plot as (H, W, 4) uint8.

    Deliberately spartan (axes, gridlines, one polyline) — the dock shows
    it at thumbnail size; there is no plotting dependency to lean on.
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    img = np.full((height, width, 4), [255, 255, 255, 255], dtype=np.uint8)
    pad = 12
    img[:, :, :3][:pad // 3, :] = 200      # thin frame shading top
    # Gridlines every 25 % of y.
    for frac in (0.25, 0.5, 0.75):
        row = int((height - 2 * pad) * frac) + pad
        img[row, pad:width - pad, :3] = 225
    # Axes.
    img[height - pad, pad:width - pad, :3] = 60
    img[pad:height - pad, pad, :3] = 60
    if len(xs) >= 2 and xs[-1] > xs[0]:
        # Dense-sample the polyline and rasterize point by point.
        t = np.linspace(0.0, 1.0, 4 * width)
        x_dense = np.interp(t, np.linspace(0, 1, len(xs)), xs)
        y_dense = np.interp(x_dense, xs, ys)
        px = (pad + (x_dense - xs[0]) / (xs[-1] - xs[0])
              * (width - 2 * pad - 1)).astype(int)
        py = (height - pad - np.clip(y_dense, 0.0, y_max) / y_max
              * (height - 2 * pad - 1)).astype(int)
        img[py, px, :3] = [180, 90, 20]
        img[np.clip(py + 1, 0, height - 1), px, :3] = [180, 90, 20]
    return img


def spread_image(fire_result):
    """The per-pixel fire spread map (Phase 4c): white (no spread)
    ramping to violet, normalized to the map's own maximum spread;
    pixels without a defined spread are transparent."""
    spread = fire_result.spread_deg
    weight = fire_result.weight
    valid = weight > 0.0
    peak = float(np.max(spread)) if np.any(valid) else 0.0
    u = np.zeros_like(spread) if peak <= 0.0 else np.clip(
        spread / peak, 0.0, 1.0)
    ramp = np.array([120, 40, 200], dtype=np.float64)   # violet
    rgb = (255.0 + (ramp - 255.0) * u[..., None]).astype(np.uint8)
    alpha_ch = np.where(valid, 255, 0).astype(np.uint8)
    return _flip(np.concatenate([rgb, alpha_ch[..., None]], axis=2))


def render_study_maps(result, tilt_results=(), tilt_angles=(),
                      tilt_values=(), fire_result=None):
    """All the PNGs one study run stores, as {name: bytes}."""
    maps = {
        "brightness.png": write_png(brightness_image(result)),
        "classification.png": write_png(classification_image(result)),
    }
    if tilt_results:
        maps["tilt_maps.png"] = write_png(tilt_montage_image(tilt_results))
    if len(tilt_angles) >= 2:
        maps["tilt_curve.png"] = write_png(
            curve_image(tilt_angles, tilt_values))
    if fire_result is not None:
        maps["fire_spread.png"] = write_png(spread_image(fire_result))
    return maps
