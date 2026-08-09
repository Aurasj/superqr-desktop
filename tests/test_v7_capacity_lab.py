"""Lean tests for the preserved V7 Capacity Lab and product-shell invariants."""

import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.v7_capacity_lab import protocol_bridge
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.analysis import analyze_records
from superqr_desktop.v7_capacity_lab.campaign import build_campaign
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_run_envelope,
    build_qr_control_payload,
    build_qr_matrix,
    qr_controls,
    validate_grid_vectors,
    validate_qr_vectors,
)
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState


def test_protocol_bridge_accessors_are_available():
    assert protocol_bridge.get_protocol_model() is not None
    assert protocol_bridge.get_protocol_palettes() is not None
    assert protocol_bridge.get_protocol_profiles() is not None


def test_reference_vectors_are_packaged():
    vectors = protocol_bridge.load_reference_vectors()
    assert len(vectors["vectors"]) == 14


def test_v6_visual_contract_is_preserved():
    contract = protocol_bridge.load_v6_visual_contract()
    assert contract["contract_version"] == "v6"
    assert contract["anchors"]["size"] == 80


def test_capacity_lab_can_render_reference_frame():
    pygame.init()
    try:
        profiles = protocol_bridge.get_protocol_profiles()
        model = protocol_bridge.get_protocol_model()
        profile = model.LabProfile(
            name="lab_96x96_candidate_8_a_seed42",
            grid_size=96,
            palette_name="candidate_8_a",
            layout_name="single",
            seed=42,
            dwell_epochs=2,
        )
        seq = profiles.build_frame_sequence(profile, num_data_frames=1)
        data_frame = next(f for f in seq.frames if not f.is_calibration)
        renderer = LabRenderer(marker_size=600)
        renderer.prepare_logical_frame(data_frame.symbol_matrix)
        assert renderer.cached_frame_display is not None
    finally:
        pygame.quit()


def test_app_has_single_product_entry_point_without_mode_selector():
    import inspect
    import superqr_desktop.app as app

    assert callable(app.main)
    source = inspect.getsource(app.ControlApp)
    assert "V6 Stable" not in source
    assert "V7 Development" not in source
    assert "Engine / Protocol" not in source
    assert "OPTICAL PROFILE" in source
    assert "TRANSFER" in source


def test_debug_patterns_still_use_frozen_v6_carrier():
    import superqr_desktop.app as app

    values = {value for _, value in app.DEBUG_PATTERNS}
    assert values == {"deterministic_random", "checkerboard", "black", "white"}


def test_phase1_manifest_and_vectors_are_packaged_and_valid():
    manifest = protocol_bridge.load_phy_selection_manifest()
    assert manifest["status"] == "LAB_ONLY_NOT_A_V7_WIRE_CONTRACT"
    assert len(manifest["grid_profiles"]) == 5
    assert len(manifest["qr_controls"]) == 2
    validate_grid_vectors()
    validate_qr_vectors()


def test_rectangular_monochrome_frame_and_run_sync():
    sequence = GridFrameSequence("mono_64x50_matched")
    frame_index, matrix = sequence.next_frame()
    assert frame_index == 0
    assert (matrix.cols, matrix.rows) == (64, 50)
    envelope = build_run_envelope("mono_64x50_matched", 0xBEEF, 0xA5, 256, 3)
    assert LabRunEnvelope.decode(envelope.encode()) == envelope

    pygame.init()
    try:
        renderer = LabRenderer(marker_size=800)
        manifest = protocol_bridge.load_phy_selection_manifest()
        renderer.prepare_logical_frame(
            matrix,
            payload_bbox=manifest["payload_bbox"],
            sync_bits=envelope.bits(),
            sync_bboxes=(manifest["run_sync"]["top_bbox"], manifest["run_sync"]["bottom_bbox"]),
            sync_rows=manifest["run_sync"]["rows"],
            sync_cols=manifest["run_sync"]["cols"],
        )
        assert renderer.cached_frame_display is not None
    finally:
        pygame.quit()


def test_qr_controls_use_exact_capacity_and_version():
    for control in qr_controls().values():
        payload = build_qr_control_payload(control, 0)
        assert len(payload) == control["frame_bytes"]
        matrix = build_qr_matrix(control, 0)
        assert len(matrix) == control["module_count"]


def test_qr_control_embeds_same_run_envelope():
    control = qr_controls()["qr_v27_l_safe"]
    payload = build_qr_control_payload(
        control, 17, run_token=0x1234, state=RunState.READY, frame_count=48, dwell_epochs=2,
    )
    envelope = LabRunEnvelope.decode(payload[16:26])
    assert envelope.run_token == 0x1234
    assert envelope.frame_index == 17
    assert envelope.frame_count == 48
    assert envelope.state == RunState.READY


def test_campaign_presets_are_ordered_and_reusable():
    canonical = build_campaign("All canonical profiles", "mono_96x75_medium", 3, 32)
    assert len(canonical) == 7
    assert canonical[0].profile == "color_40x40_control"
    assert canonical[-1].profile == "qr_v40_l_ceiling"
    assert all(run.frame_count == 32 for run in canonical)
    assert len(build_campaign("Full grid dwell sweep", "mono_96x75_medium", 3, 16)) == 10


def test_lab_display_close_is_idempotent():
    controller = LabDisplayController()
    controller.close()
    controller.close()
    assert controller.screen is None


def test_physical_lab_ui_exposes_required_controls():
    import inspect
    from superqr_desktop.v7_capacity_lab.phy_lab_ui import PhyLabWindow

    source = inspect.getsource(PhyLabWindow)
    for label in ("CAMPAIGN", "DISPLAY", "RUN CONTROL", "START CAMPAIGN", "STOP", "Analyze receiver JSONL"):
        assert label in source


def test_log_analysis_excludes_rejected_frames_and_flags_frame_zero_wait():
    base = {
        "run_id": "run-a", "completed_ns": 0, "observed_bits": 100,
        "bit_errors": 5, "erased_bits": 10, "frame_valid": False,
        "post_fec_valid": False, "innovative_bytes": 0, "pipeline_ms": 10.0,
    }
    records = [dict(base, completed_ns=index * 10, frame_index=0) for index in range(4)]
    records.append(dict(base, completed_ns=50, frame_index=None, scored=False, failure_reason="SYNC_CRC"))
    summary = analyze_records(records)
    assert summary["scored_frames"] == 4
    assert summary["rejected_frames"] == 1
    assert summary["initial_frame_zero_observations"] == 4
    assert summary["failure_reasons"] == {"SYNC_CRC": 1}
