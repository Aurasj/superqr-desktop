from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame
import zxingcpp

from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.v7_capacity_lab.advanced_phy import (
    advanced_profile,
    advanced_profiles,
    build_advanced_grid_symbols,
    build_advanced_qr_matrix,
    build_advanced_qr_payload,
    default_advanced_profile_name,
    validate_advanced_phy_vectors,
)
from superqr_desktop.v7_capacity_lab.advanced_renderer import AdvancedFrameComposer
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer


def test_advanced_manifest_is_bounded_to_30_fps_and_default_is_fast20():
    validate_advanced_phy_vectors()
    profiles = advanced_profiles()
    assert default_advanced_profile_name() == "advanced_quad_qr_v27_l_fast20"
    assert max(float(profile["target_fps"]) for profile in profiles.values()) == 30.0
    assert profiles[default_advanced_profile_name()]["target_fps"] == 20.0


def test_quad_qr_lanes_are_independent_and_binary_decodable():
    profile = advanced_profile("advanced_quad_qr_v27_l_fast20")
    payloads = []
    for lane in profile["lanes"]:
        payload = build_advanced_qr_payload(profile, lane, 0, run_token=0x1234)
        payloads.append(payload)
        assert payload[:4] == b"SQA1"
        assert payload[6] == lane["lane_id"]
        assert payload[7] == 4
        matrix = build_advanced_qr_matrix(profile, lane, 0, run_token=0x1234)
        image = np.fromiter(
            (0 if value else 255 for row in matrix for value in row),
            dtype=np.uint8,
            count=len(matrix) * len(matrix),
        ).reshape((len(matrix), len(matrix)))
        result = zxingcpp.read_barcode(
            image,
            formats=zxingcpp.BarcodeFormat.QRCode,
            text_mode=zxingcpp.TextMode.Plain,
            is_pure=True,
        )
        assert result is not None
        assert bytes(result.bytes) == payload
    assert len({payload for payload in payloads}) == 4


def test_fast_quad_keeps_three_pixels_per_module_at_1000_marker():
    pygame.init()
    try:
        renderer = LabRenderer(1000)
        profile = advanced_profile("advanced_quad_qr_v27_l_fast20")
        for lane in profile["lanes"]:
            rect = renderer._compute_display_payload_rect(lane["bbox"])
            scale = min(rect.width // lane["total_modules"], rect.height // lane["total_modules"])
            assert scale >= 3
    finally:
        pygame.quit()


def test_hybrid_color_lanes_generate_full_declared_symbol_range():
    profile = advanced_profile("advanced_hybrid_qr2_c8_c16_20")
    grid_lanes = [lane for lane in profile["lanes"] if lane["kind"] == "grid"]
    assert {lane["bits_per_cell"] for lane in grid_lanes} == {3, 4}
    for lane in grid_lanes:
        observed = set()
        for frame_index in range(8):
            symbols = build_advanced_grid_symbols(profile, lane, frame_index)
            observed.update(symbol for row in symbols for symbol in row)
        assert observed == set(range(1 << lane["bits_per_cell"]))


def test_advanced_composer_builds_fast_and_hybrid_frames():
    pygame.init()
    try:
        for name in (
            "advanced_quad_qr_v27_l_fast20",
            "advanced_hybrid_qr2_c4_c8_20",
            "advanced_hybrid_qr2_c8_c16_20",
        ):
            renderer = LabRenderer(1000)
            composer = AdvancedFrameComposer(renderer)
            profile = advanced_profile(name)
            qr_surfaces = {}
            for lane in profile["lanes"]:
                if lane["kind"] == "qr":
                    matrix = build_advanced_qr_matrix(profile, lane, 0)
                    qr_surfaces[lane["lane_id"]] = renderer.build_qr_native_surface(
                        matrix, lane["quiet_zone_modules"]
                    )
            composer.prepare(profile, 0, qr_surfaces)
            assert renderer.cached_frame_display is not None
            assert renderer.cached_frame_display.get_size() == (1000, 1000)
    finally:
        pygame.quit()


def test_controller_exposes_fast_and_selection_without_exceeding_30_fps():
    controller = CampaignController()
    controller.set_frames(32)
    controller.set_preset("Phase 0 advanced FAST")
    assert controller.run_count == 1
    assert controller.runs[0].profile == "advanced_quad_qr_v27_l_fast20"
    assert controller.runs[0].target_fps == 20.0
    assert controller.runs[0].frame_count == 32

    controller.set_preset("Phase 0 advanced selection")
    assert controller.run_count == 4
    assert {run.target_fps for run in controller.runs} == {20.0, 30.0}
    assert all(run.target_fps <= 30.0 for run in controller.runs)
