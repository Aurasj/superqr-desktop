from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState
from superqr_desktop.v7_capacity_lab.shapegrid import (
    build_shapegrid_block_data,
    build_shapegrid_frame_cells,
    default_shapegrid_profile_name,
    shapegrid_profile,
    shapegrid_profiles,
    validate_shapegrid_vectors,
)
from superqr_desktop.v7_capacity_lab.shapegrid_renderer import ShapeGridFrameComposer


def test_shapegrid_contract_vectors_and_capacity_are_frozen():
    validate_shapegrid_vectors()
    profiles = list(shapegrid_profiles().values())
    assert [profile["profile_id"] for profile in profiles] == [18, 19, 20]
    assert [profile["role"] for profile in profiles] == ["SAFE", "DEFAULT_FAST", "STRESS"]
    assert [profile["target_fps"] for profile in profiles] == [20.0, 20.0, 20.0]
    assert [profile["useful_bytes_per_epoch"] for profile in profiles] == [6384, 8040, 9696]
    assert [profile["theoretical_net_mbps_at_20fps"] for profile in profiles] == [
        1.02144,
        1.2864,
        1.55136,
    ]
    assert [
        (profile["grid_cols"], profile["grid_rows"])
        for profile in profiles
    ] == [(136, 80), (136, 100), (152, 108)]
    assert profiles[0]["inactive_cells_per_block"] == 0
    assert profiles[1]["inactive_cells_per_block"] == 0


def test_shapegrid_inner_block_carries_ready_running_done_state():
    profile = shapegrid_profile(default_shapegrid_profile_name())
    states = []
    for state in (RunState.READY, RunState.RUNNING, RunState.DONE):
        block = build_shapegrid_block_data(
            profile,
            0,
            7,
            run_token=0x1234,
            state=state,
            frame_count=32,
            dwell_epochs=3,
        )
        assert block[:4] == b"SQS1"
        assert block[5] == 0
        assert block[6] == 8
        assert block[8:10] == bytes((0xD7, 0x01))
        states.append(block[10])
    assert states == [0, 1, 2]


def test_shapegrid_frame_cells_are_deterministic_and_fill_fast_grid():
    profile = shapegrid_profile(default_shapegrid_profile_name())
    first = build_shapegrid_frame_cells(profile, 7, run_token=0xCAFE)
    second = build_shapegrid_frame_cells(profile, 7, run_token=0xCAFE)
    assert first == second
    assert len(first) == 136 * 100
    assert max(first) <= 63


def test_shapegrid_fast_renders_with_integer_subcells_at_1000_marker():
    pygame.init()
    try:
        renderer = LabRenderer(1000)
        composer = ShapeGridFrameComposer(renderer)
        profile = shapegrid_profile(default_shapegrid_profile_name())
        assert composer.subcell_scale(profile) == 1
        cells = build_shapegrid_frame_cells(profile, 0, run_token=0xBEEF)
        sync_bits = LabRunEnvelope(
            RunState.RUNNING,
            int(profile["profile_id"]),
            0xBEEF,
            0,
            256,
            3,
        ).bits()
        composer.prepare(profile, cells, sync_bits=sync_bits)
        assert renderer.cached_frame_display is not None
        assert renderer.cached_frame_display.get_size() == (1000, 1000)
    finally:
        pygame.quit()


def test_shapegrid_stress_requires_larger_reference_marker():
    pygame.init()
    try:
        stress = shapegrid_profile("shapegrid_c4_s16_152x108_stress20")
        assert ShapeGridFrameComposer(LabRenderer(1000)).subcell_scale(stress) == 0
        assert ShapeGridFrameComposer(LabRenderer(1100)).subcell_scale(stress) >= 1
    finally:
        pygame.quit()


def test_controller_exposes_shapegrid_fast_and_three_profile_selection():
    controller = CampaignController()
    controller.set_frames(32)
    controller.set_preset("Phase 0 ShapeGrid FAST")
    assert controller.run_count == 1
    assert controller.runs[0].profile == "shapegrid_c4_s16_136x100_fast20"
    assert controller.runs[0].target_fps == 20.0
    assert controller.runs[0].frame_count == 32

    controller.set_preset("Phase 0 ShapeGrid selection")
    assert controller.run_count == 3
    assert [run.profile for run in controller.runs] == [
        "shapegrid_c4_s16_136x80_safe20",
        "shapegrid_c4_s16_136x100_fast20",
        "shapegrid_c4_s16_152x108_stress20",
    ]
    assert {run.target_fps for run in controller.runs} == {20.0}
