# SPDX-License-Identifier: LGPL-2.1-or-later
"""Map rendering tests (DESIGN_OPTICS.md sections 7, 8, 10 — Phase 4b).

The PNG encoder is validated structurally (signature, chunk CRCs, IHDR)
and by full decode: filter-0 scanlines invert trivially, so the tests
decompress IDAT and compare the pixel bytes against the source array.
Determinism is byte-level. No FreeCAD, no Qt.
"""

import struct
import zlib

import numpy as np
import pytest

import optics_fixtures as fx
from freecad.lapidary.optics import imaging
from freecad.lapidary.optics import tracer as tr


def _decode_png(data):
    """Minimal decoder for this module's own output (filter 0 only)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    chunks = []
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:
                                       pos + 12 + length])[0]
        assert crc == zlib.crc32(tag + payload) & 0xFFFFFFFF, tag
        chunks.append((tag, payload))
        pos += 12 + length
    assert chunks[0][0] == b"IHDR" and chunks[-1][0] == b"IEND"
    width, height, depth, color = struct.unpack(
        ">IIBB", chunks[0][1][:10])
    assert depth == 8 and color == 6          # 8-bit RGBA
    raw = zlib.decompress(
        b"".join(p for t, p in chunks if t == b"IDAT"))
    stride = 1 + 4 * width
    rows = []
    for iy in range(height):
        row = raw[iy * stride:(iy + 1) * stride]
        assert row[0] == 0                    # filter type 0
        rows.append(np.frombuffer(row[1:], dtype=np.uint8))
    return np.stack(rows).reshape(height, width, 4)


@pytest.fixture(scope="module")
def slab_result():
    return tr.trace(fx.slab_polytope(), 1.5, resolution=16)


@pytest.fixture(scope="module")
def srb_result():
    return tr.trace(fx.srb_polytope(), 1.54, resolution=32)


class TestPngEncoder:
    def test_roundtrip(self):
        rng = np.random.default_rng(3)
        rgba = rng.integers(0, 256, size=(9, 13, 4), dtype=np.uint8)
        assert np.array_equal(_decode_png(imaging.write_png(rgba)), rgba)

    def test_determinism(self, srb_result):
        a = imaging.write_png(imaging.brightness_image(srb_result))
        b = imaging.write_png(imaging.brightness_image(srb_result))
        assert a == b

    def test_rejects_bad_shapes(self):
        with pytest.raises(ValueError):
            imaging.write_png(np.zeros((4, 4, 3), dtype=np.uint8))


class TestMaps:
    def test_brightness_values_and_orientation(self, srb_result):
        img = imaging.brightness_image(srb_result)
        R = srb_result.resolution
        assert img.shape == (R, R, 4)
        # Row flip: image row 0 is the +y edge (array row R-1).
        expected = np.round(
            255.0 * np.clip(srb_result.brightness[R - 1], 0.0, 1.0))
        assert np.array_equal(img[0, :, 0], expected.astype(np.uint8))
        # Misses transparent, hits opaque.
        assert np.array_equal(img[:, :, 3] == 255,
                              srb_result.hit_mask[::-1])

    def test_classification_colors(self, slab_result):
        img = imaging.classification_image(slab_result)
        hits = slab_result.hit_mask[::-1]
        # The slab is all WINDOW (92 % leaks): every hit pixel steel blue.
        assert np.all(img[hits] == imaging.CLASS_COLORS[tr.CLASS_WINDOW])
        assert np.all(img[~hits, 3] == 0)

    def test_tilt_montage_geometry(self, slab_result):
        strip = imaging.tilt_montage_image([slab_result] * 3, gap=2)
        R = slab_result.resolution
        assert strip.shape == (R, 3 * R + 4, 4)
        assert np.all(strip[:, R:R + 2, 3] == 0)      # transparent gutter

    def test_curve_image_draws_the_polyline(self):
        img = imaging.curve_image([0.0, 10.0, 20.0], [90.0, 70.0, 40.0])
        # Some pixels must carry the curve color.
        curve = np.all(img[:, :, :3] == [180, 90, 20], axis=2)
        assert np.sum(curve) > 50

    def test_render_study_maps_keys(self, srb_result):
        maps = imaging.render_study_maps(
            srb_result, tilt_results=[srb_result, srb_result],
            tilt_angles=[0.0, 10.0], tilt_values=[95.0, 90.0])
        assert set(maps) == {"brightness.png", "classification.png",
                             "tilt_maps.png", "tilt_curve.png"}
        for data in maps.values():
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
