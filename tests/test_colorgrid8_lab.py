from __future__ import annotations

from superqr_desktop.v7_capacity_lab.colorgrid8_core import (
    FPS_SWEEP,
    GRID_SWEEP,
    ColorGrid8Profile,
    build_symbol_frame,
    golden_crc32,
)


def test_default_profile_keeps_200_kib_s_after_lab_overheads() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    assert profile.raw_kib_s == 265.78125
    assert profile.payload_kib_s > 253.37
    assert profile.post_fec_kib_s(0.20) > 202.70


def test_protocol_golden_frame_matches_reference_crc() -> None:
    profile = ColorGrid8Profile(168, 144, 30)
    assert golden_crc32(profile, 0) == 0xCE0A026F
    assert golden_crc32(profile, 1) == 0x6B848359
    assert golden_crc32(profile, 7) == 0xF7AA5BCF


def test_all_sweep_frames_are_valid_3_bit_symbols() -> None:
    for cols, rows in GRID_SWEEP:
        for fps in FPS_SWEEP:
            profile = ColorGrid8Profile(cols, rows, fps)
            frame = build_symbol_frame(profile, 1234)
            assert frame.shape == (rows, cols)
            assert int(frame.min()) >= 0
            assert int(frame.max()) <= 7
