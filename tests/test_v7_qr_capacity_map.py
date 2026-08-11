import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.campaign.qr_capacity_map import build_qr_capacity_map_runs
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    build_qr_matrix,
    profile_id,
    qr_capacity_map_controls,
    qr_controls,
    validate_qr_capacity_map_vectors,
    validate_qr_vectors,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_qr_capacity_map_manifest


FPS = [20.0, 24.0, 30.0, 36.0, 40.0, 48.0, 60.0]
PROFILES = [
    "qr_v27_l_safe",
    "qr_v30_l_map",
    "qr_v33_l_map",
    "qr_v36_l_map",
    "qr_v40_l_ceiling",
]


def test_qr_capacity_map_extension_keeps_canonical_controls_frozen():
    extension = load_qr_capacity_map_manifest()
    assert [p["name"] for p in extension["profiles"]] == PROFILES[1:4]

    controls = qr_controls()
    assert list(controls) == ["qr_v27_l_safe", "qr_v40_l_ceiling"]
    assert "qr_v30_l_map" in controls
    assert controls["qr_v30_l_map"]["version"] == 30
    assert list(qr_capacity_map_controls()) == [
        "qr_v30_l_map",
        "qr_v33_l_map",
        "qr_v36_l_map",
    ]

    assert profile_id("qr_v27_l_safe") == 5
    assert profile_id("qr_v40_l_ceiling") == 6
    assert profile_id("qr_v30_l_map") == 7
    assert profile_id("qr_v33_l_map") == 8
    assert profile_id("qr_v36_l_map") == 9


def test_qr_capacity_map_vectors_validate_with_existing_payload_builder():
    validate_qr_vectors()
    validate_qr_capacity_map_vectors()


def test_qr_capacity_map_profiles_render_on_fixed_canvas():
    pygame.init()
    try:
        renderer = LabRenderer(marker_size=600)
        for control in qr_capacity_map_controls().values():
            matrix = build_qr_matrix(control, 0)
            native = renderer.build_qr_native_surface(
                matrix,
                int(control["quiet_zone_modules"]),
            )
            renderer.prepare_qr_native_surface(native)
            surface = renderer.cached_frame_display
            assert surface is not None
            assert surface.get_size() == (600, 600)
    finally:
        pygame.quit()


def test_qr_capacity_map_builds_five_blocks_with_interleaved_control():
    runs = build_qr_capacity_map_runs(dwell=3, frames=256)
    assert len(runs) == 39

    cursor = 0
    for block_index, profile in enumerate(PROFILES):
        block = runs[cursor:cursor + len(FPS)]
        assert [run.profile for run in block] == [profile] * len(FPS)
        assert [run.target_fps for run in block] == FPS
        cursor += len(FPS)
        if block_index + 1 < len(PROFILES):
            control = runs[cursor]
            assert control.profile == "qr_v27_l_safe"
            assert control.target_fps == 24.0
            cursor += 1

    assert cursor == len(runs)
    assert all(run.dwell_epochs == 3 for run in runs)
    assert all(run.frame_count == 256 for run in runs)


def test_controller_exposes_qr_capacity_cadence_map():
    ctrl = CampaignController()
    ctrl.set_preset("QR capacity cadence map")
    assert ctrl.run_count == 39
    assert ctrl.runs[0].profile == "qr_v27_l_safe"
    assert ctrl.runs[-1].profile == "qr_v40_l_ceiling"
    assert ctrl.runs[-1].target_fps == 60.0
