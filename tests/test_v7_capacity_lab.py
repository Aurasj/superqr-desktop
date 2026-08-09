"""Lean tests for the preserved V7 Capacity Lab and product-shell invariants."""

import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.v7_capacity_lab import protocol_bridge
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.analysis import analyze_records
from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    Phase1CampaignWorker,
    RunSpec,
    build_campaign,
)
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
    assert manifest["schema_version"] == 3
    assert manifest["acquisition_carrier"]["status"] == "LAB_ONLY_NOT_PRODUCTION_V7_GEOMETRY"
    assert len(manifest["grid_profiles"]) == 5
    assert len(manifest["qr_controls"]) == 2
    validate_grid_vectors()
    validate_qr_vectors()


def test_v7_lab_carrier_renders_manifest_geometry_exactly():
    pygame.init()
    try:
        manifest = protocol_bridge.load_phy_selection_manifest()
        profile = GridFrameSequence("mono_64x50_matched")
        frame_index, matrix = profile.next_frame()
        envelope = build_run_envelope("mono_64x50_matched", 0xC570, frame_index, 32, 3)
        renderer = LabRenderer(marker_size=1000)
        renderer.prepare_logical_frame(
            matrix,
            payload_bbox=manifest["payload_bbox"],
            sync_bits=envelope.bits(),
            sync_bboxes=(manifest["run_sync"]["top_bbox"], manifest["run_sync"]["bottom_bbox"]),
            sync_rows=manifest["run_sync"]["rows"],
            sync_cols=manifest["run_sync"]["cols"],
        )
        surface = renderer.cached_frame_display
        assert surface is not None
        # Continuous border: white outside, black band, white inside.
        assert surface.get_at((49, 500))[:3] == (255, 255, 255)
        assert surface.get_at((50, 500))[:3] == (0, 0, 0)
        assert surface.get_at((69, 500))[:3] == (0, 0, 0)
        assert surface.get_at((70, 500))[:3] == (255, 255, 255)
        # Standard nested TL finder and both duplicated optical sync bands.
        assert surface.get_at((80, 80))[:3] == (0, 0, 0)
        assert surface.get_at((94, 94))[:3] == (255, 255, 255)
        assert surface.get_at((109, 109))[:3] == (0, 0, 0)
        first_bit = envelope.bits()[0]
        expected = (255, 255, 255) if first_bit else (0, 0, 0)
        assert surface.get_at((207, 152))[:3] == expected
        assert surface.get_at((207, 832))[:3] == expected
    finally:
        pygame.quit()


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


def test_desktop_matches_ready_running_done_conformance_trace():
    trace = protocol_bridge.load_phy_selection_manifest()["run_sync"]["conformance_trace"]
    for packet in trace["packets"]:
        envelope = build_run_envelope(
            trace["profile"], trace["run_token"], packet["frame_index"],
            trace["frame_count"], trace["dwell_epochs"], RunState[packet["state"]],
        )
        assert envelope.encode().hex().upper() == packet["packet_hex"]


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


def test_lab_display_extends_the_white_quiet_zone_to_the_screen():
    pygame.display.init()
    controller = LabDisplayController()
    try:
        controller.screen = pygame.display.set_mode((320, 240))
        controller.marker_size = 100
        marker = pygame.Surface((100, 100))
        marker.fill((0, 0, 0))
        controller.present(marker)
        assert tuple(controller.screen.get_at((0, 0)))[:3] == (255, 255, 255)
        assert tuple(controller.screen.get_at((160, 120)))[:3] == (0, 0, 0)
    finally:
        controller.close()


def test_vsync_is_claimed_only_after_measured_refresh_cadence():
    controller = LabDisplayController()
    controller.diag.driver_vsync_reported = True
    controller.diag.refresh_period_ms = 1000.0 / 60.0
    for _ in range(12):
        controller._verify_vsync(1000.0 / 60.0)
    assert controller.diag.vsync_verified
    assert controller.diag.actual_vsync_enabled

    slow = LabDisplayController()
    slow.diag.driver_vsync_reported = True
    slow.diag.refresh_period_ms = 1000.0 / 60.0
    for _ in range(12):
        slow._verify_vsync(1000.0 / 48.0)
    assert slow.diag.vsync_verified
    assert not slow.diag.actual_vsync_enabled
    assert slow.diag.timing_mode.name == "FALLBACK_TIMER_MODE"


def test_physical_lab_ui_exposes_required_controls():
    import inspect
    from superqr_desktop.v7_capacity_lab.phy_lab_ui import PhyLabWindow

    source = inspect.getsource(PhyLabWindow)
    for label in ("CAMPAIGN CONSOLE", "Campaign setup", "Live run", "START CAMPAIGN", "STOP", "Analyze Android JSONL"):
        assert label in source


def test_grid_campaign_runs_ready_running_done_without_manual_input():
    presenter = Phase1CampaignPresenter(
        [RunSpec("mono_64x50_matched", 3, 1)], display_index=0,
        fullscreen=False, marker_size=600, ready_seconds=0.0, done_seconds=0.0,
        first_run_token=0x1234,
    )
    try:
        presenter.start()
        assert presenter.snapshot().state == CampaignState.READY
        assert presenter.tick()
        assert presenter.snapshot().state == CampaignState.RUNNING
        for _ in range(4):
            presenter.last_advance -= 1.0
            assert presenter.tick()
            if presenter.snapshot().state == CampaignState.DONE:
                break
        snapshot = presenter.snapshot()
        assert snapshot.state == CampaignState.DONE
        assert snapshot.run_token == 0x1234
    finally:
        presenter.stop()


def test_presentation_worker_completes_without_tk_scheduler_and_exports_each_run():
    presenter = Phase1CampaignPresenter(
        [RunSpec("mono_64x50_matched", 2, 6)], display_index=0,
        fullscreen=False, marker_size=400, ready_seconds=0.3, done_seconds=0.0,
        first_run_token=0x4321,
    )
    worker = Phase1CampaignWorker(presenter)
    try:
        worker.start()
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            snapshot = worker.snapshot()
            if snapshot is not None and snapshot.state == CampaignState.DONE:
                break
            time.sleep(0.01)
        snapshot = worker.snapshot()
        assert snapshot is not None
        assert snapshot.state == CampaignState.DONE
        payload = worker.export_payload()
        assert payload["schema"] == "superqr-phy-lab-sender-v3"
        assert payload["production_wire_frozen"] is False
        assert payload["presentation"] == {
            "display_index": 0,
            "fullscreen": False,
            "marker_size_px": 400,
            "ready_seconds": 0.3,
            "done_seconds": 0.0,
        }
        assert payload["runtime_isolation"] == "process"
        assert payload["presenter_process_id"] != os.getpid()
        assert payload["runs_completed"] == 1
        assert payload["runs"][0]["run_token"] == 0x4321
        assert payload["runs"][0]["present_count"] >= 11
        assert 50.0 <= payload["runs"][0]["present_fps"] <= 70.0
        assert payload["runs"][0]["late_presents"] == 0
        assert payload["runs"][0]["vsync_verified"]
    finally:
        worker.stop()


def test_presentation_worker_stop_request_never_waits_for_display_shutdown():
    presenter = Phase1CampaignPresenter(
        [RunSpec("mono_64x50_matched", 3, 256)], display_index=0,
        fullscreen=False, marker_size=400, ready_seconds=10.0, done_seconds=0.0,
    )
    worker = Phase1CampaignWorker(presenter)
    try:
        worker.start()
        import time
        deadline = time.monotonic() + 3.0
        while worker.snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        worker.request_stop()
        assert time.monotonic() - started < 0.05
        deadline = time.monotonic() + 3.0
        while worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not worker.is_alive()
        assert worker.snapshot().state == CampaignState.STOPPED
    finally:
        worker.stop()


def test_presentation_worker_sequences_all_canonical_profiles_and_tokens():
    presenter = Phase1CampaignPresenter(
        build_campaign("All canonical profiles", "mono_64x50_matched", 2, 1),
        display_index=0, fullscreen=False, marker_size=400,
        ready_seconds=0.0, done_seconds=0.0, first_run_token=0x7000,
    )
    worker = Phase1CampaignWorker(presenter)
    try:
        worker.start()
        import time
        deadline = time.monotonic() + 8.0
        while worker.is_alive() and time.monotonic() < deadline:
            worker.snapshot()
            time.sleep(0.01)
        assert not worker.is_alive()
        payload = worker.export_payload()
        assert payload["runs_completed"] == 7
        assert [run["run_token"] for run in payload["runs"]] == list(range(0x7000, 0x7007))
        assert payload["runs"][-1]["profile"] == "qr_v40_l_ceiling"
    finally:
        worker.stop()


def test_campaign_stop_interrupts_qr_preparation_between_frames():
    presenter = Phase1CampaignPresenter(
        [RunSpec("qr_v40_l_ceiling", 3, 256)], display_index=0,
        fullscreen=False, marker_size=400, ready_seconds=0.0, done_seconds=0.0,
    )
    try:
        presenter.request_stop()
        presenter.start()
        assert presenter.state == CampaignState.STOPPED
        assert presenter.qr_native == []
    finally:
        presenter.stop()


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
    assert summary["pipeline_mean_ms"] == 10.0


def test_log_analysis_reports_unsynchronized_pipeline_and_capture_evidence():
    records = [
        {
            "profile": "AUTO_UNSYNCED", "completed_ns": (index + 1) * 1_000_000_000,
            "pipeline_ms": 1200.0 + index * 100.0, "scored": False,
            "failure_reason": "QR_NOT_DECODED", "sync_status": "QR_NOT_DECODED",
            "geometry_source": "NO_V6_GEOMETRY", "capture_width": 3456,
            "capture_height": 3456,
        }
        for index in range(3)
    ]
    summary = analyze_records(records)
    assert summary["scored_frames"] == 0
    assert summary["pipeline_mean_ms"] == 1300.0
    assert summary["analysis_fps"] == 1.0
    assert summary["capture_resolutions"] == {"3456x3456": 3}
    assert summary["sync_states"] == {"QR_NOT_DECODED": 3}
    assert summary["geometry_states"] == {"NO_V6_GEOMETRY": 3}
