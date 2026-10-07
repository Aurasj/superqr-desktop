"""Exercise Android's actual C++ decoder with Desktop's current wire bytes.

Set SUPERQR_COLORGRID_DECODER to the host-built colorgrid8_decode_probe.
The probe links vision/src/main/cpp/colorgrid8_native.cpp unchanged.
Build it with a host C++ compiler and CMake, using
../superqr-android/vision/src/test/cpp as the CMake source directory.
"""
import os
import struct
import subprocess

import numpy as np
import pytest

from superqr_desktop.lab.colorgrid8_core import (
    ColorGrid8Profile, PALETTE_RGB, build_payload_symbol_frame, is_pilot,
)
from superqr_desktop.lab.colorgrid8_transfer import (
    ColorGrid8TransferSession, parse_transport_frame, symbols_to_bytes,
)

PROBE = os.environ.get("SUPERQR_COLORGRID_DECODER")
pytestmark = pytest.mark.skipif(not PROBE, reason="host native decoder probe not configured")
PROFILE = ColorGrid8Profile(336, 288, 30, version=2)


def means(symbols):
    rgb = PALETTE_RGB[symbols].astype(float)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return np.stack((.299*r + .587*g + .114*b,
                     -.169*r - .331*g + .5*b + 128,
                     .5*r - .419*g - .081*b + 128)).round().clip(0, 255).astype(np.uint8)


def decode(planes, profile=PROFILE):
    result = subprocess.run([PROBE, str(profile.cols), str(profile.rows)], input=planes.tobytes(), capture_output=True, check=True)
    return struct.unpack("<5i", result.stdout[:20]), np.frombuffer(result.stdout[20:], dtype=np.uint8)


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(bytes(range(251)) * 31)
    with ColorGrid8TransferSession(path, PROFILE) as transfer:
        yield transfer


@pytest.mark.parametrize("index", [0, 1, 31, 65535])
def test_native_recovers_exact_desktop_transport(session, index):
    symbols = session.symbol_frame(index)
    stats, decoded = decode(means(symbols))
    expected = np.asarray([symbols[r, c] for r in range(2, PROFILE.rows)
                           for c in range(PROFILE.cols) if not is_pilot(PROFILE, r, c)])
    assert stats == (1, 6, index, 0, PROFILE.payload_cells)
    np.testing.assert_array_equal(decoded, expected)
    assert parse_transport_frame(PROFILE, symbols_to_bytes(decoded)) is not None


@pytest.mark.parametrize("bit", [0, 12, 20, 51, 55])
def test_corrupt_header_is_rejected_without_guessing(session, bit):
    symbols = session.symbol_frame(0)
    symbols[:2, bit*2:bit*2+2] ^= 4
    stats, _ = decode(means(symbols))
    assert stats[:2] == (0, 4)


def test_mixed_header_rows_and_shifted_grid_are_rejected(session):
    symbols = session.symbol_frame(0)
    symbols[1] = session.symbol_frame(1)[1]
    assert decode(means(symbols))[0][:2] == (0, 4)
    shifted = np.roll(session.symbol_frame(0), (-1, -1), axis=(0, 1))
    assert decode(means(shifted))[0][:2] == (0, 4)


def test_wrong_profile_and_flat_pilots_are_rejected(session):
    wrong = ColorGrid8Profile(336, 288, 60, version=2)
    symbols = build_payload_symbol_frame(wrong, 0, np.zeros(100, dtype=np.uint8))
    assert decode(means(symbols))[0][:2] == (0, 4)
    planes = means(session.symbol_frame(0))
    planes[:, 2:, :] = 128
    assert decode(planes)[0][:2] == (0, 5)


@pytest.mark.parametrize("canvas", [(1856, 984), (2560, 1440)])
def test_rendered_cell_centers_recover_file_through_native_decoder(session, canvas):
    import cv2
    import pygame
    from superqr_desktop.lab.colorgrid8_renderer import ColorGrid8Renderer

    symbols = session.symbol_frame(0)
    surface, geometry = ColorGrid8Renderer().render_symbols(PROFILE, symbols, *canvas)
    # Same canonical finder mapping used by the Android GL pipeline. Project
    # quarter-cell samples, rather than shifting by one cell or one camera pixel.
    canonical = np.float32([(0, 0), (352, 0), (352, 304), (0, 304)])
    h = cv2.getPerspectiveTransform(canonical, np.float32(geometry.fiducial_centers))
    rows, cols = np.indices(symbols.shape)
    rgb = pygame.surfarray.array3d(surface)
    for dy, dx in [(-.25, -.25), (-.25, .25), (.25, -.25), (.25, .25)]:
        points = np.stack((cols + 8.5 + dx, rows + 8.5 + dy), axis=-1).astype(np.float32)
        mapped = cv2.perspectiveTransform(points.reshape(-1, 1, 2), h).reshape(*symbols.shape, 2)
        sampled = rgb[mapped[..., 0].astype(int), mapped[..., 1].astype(int)]
        np.testing.assert_array_equal(sampled, PALETTE_RGB[symbols])
    stats, decoded = decode(means(symbols))
    assert stats[:3] == (1, 6, 0)
    assert parse_transport_frame(PROFILE, symbols_to_bytes(decoded)) is not None
