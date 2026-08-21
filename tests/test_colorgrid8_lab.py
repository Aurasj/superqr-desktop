from __future__ import annotations

from superqr_desktop.lab.colorgrid8_core import (
    FPS_SWEEP,
    GRID_SWEEP,
    ColorGrid8Profile,
    build_symbol_frame,
    golden_crc32,
)
from superqr_desktop.lab.colorgrid8_renderer import choose_cell_px


def test_default_profile_keeps_200_kib_s_after_lab_overheads() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    assert profile.raw_kib_s == 265.78125
    assert profile.payload_kib_s == 251.597900390625
    assert profile.post_fec_kib_s(0.20) == 201.2783203125


def test_protocol_golden_frame_matches_reference_crc() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    assert golden_crc32(profile, 0) == 0x94A6DBA5
    assert golden_crc32(profile, 1) == 0xBADE60B7
    assert golden_crc32(profile, 7) == 0x276C602C


def test_header_is_repeated_across_two_rows_for_warp_tolerance() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    frame = build_symbol_frame(profile, 1234)
    assert (frame[0] == frame[1]).all()


def test_all_sweep_frames_are_valid_3_bit_symbols() -> None:
    for cols, rows in GRID_SWEEP:
        for fps in FPS_SWEEP:
            profile = ColorGrid8Profile(cols, rows, fps)
            frame = build_symbol_frame(profile, 1234)
            assert frame.shape == (rows, cols)
            assert int(frame.min()) >= 0
            assert int(frame.max()) <= 7


def test_high_resolution_sender_uses_available_optical_area() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    # 3840x2160 can fit 13 px cells after the defined LAB margins. The old
    # arbitrary 10 px cap threw away useful camera sampling resolution.
    assert choose_cell_px(profile, 3840, 2160) == 13
