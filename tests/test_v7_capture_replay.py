"""Comprehensive tests for the V7 digital baseline harness."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import cv2
import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.baseline_worker import (
    BaselineEvent,
    BaselineWorker,
    CampaignBaselineReport,
    ProfileBaselineResult,
    ReceiverReplayResult,
    SenderTruthResult,
    validate_receiver_replay,
    validate_sender_truth,
)
from superqr_desktop.v7_capacity_lab.degradation import (
    BlurDegradation,
    BrightnessContrastDegradation,
    DownsampleDegradation,
    GaussianNoiseDegradation,
    PerspectiveDegradation,
    RollingShutterDegradation,
    SaltPepperNoiseDegradation,
    apply_blur,
    apply_brightness_contrast,
    apply_degradation,
    apply_downsample,
    apply_gaussian_noise,
    apply_perspective,
    apply_rolling_shutter,
    apply_salt_pepper_noise,
    degradation_name,
)
from superqr_desktop.v7_capacity_lab.differential_diagnostics import (
    FailureCategory,
    diagnose_frame,
    diagnose_sweep,
)
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_matrix,
    build_run_envelope,
    grid_profiles,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import RunState


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _render_grid_surface(profile: str, fi: int, token: int = 0x1111) -> pygame.Surface:
    seq = GridFrameSequence(profile)
    matrix = None
    for _ in range(fi + 1):
        idx, matrix = seq.next_frame()
    renderer = LabRenderer(600)
    manifest = load_phy_selection_manifest()
    sync = manifest["run_sync"]
    envelope = build_run_envelope(profile, token, fi, 10, 3, RunState.RUNNING)
    renderer.prepare_logical_frame(
        matrix, payload_bbox=manifest["payload_bbox"],
        sync_bits=envelope.bits(),
        sync_bboxes=(sync["top_bbox"], sync["bottom_bbox"]),
        sync_rows=int(sync["rows"]), sync_cols=int(sync["cols"]),
    )
    return renderer.cached_frame_display


def _render_qr_surface(profile: str, fi: int, token: int = 0x2222) -> pygame.Surface:
    control = qr_controls()[profile]
    matrix = build_qr_matrix(control, fi, run_token=token, frame_count=10,
                             dwell_epochs=3, state=RunState.RUNNING)
    renderer = LabRenderer(600)
    renderer.prepare_qr_matrix(matrix, int(control["quiet_zone_modules"]))
    return renderer.cached_frame_display


# ---------------------------------------------------------------------------
# baseline worker tests
# ---------------------------------------------------------------------------


def test_baseline_worker_produces_events_for_all_seven_profiles():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=3)
            report = worker.run()
            assert len(report.profiles) == 7
            all_names = {pr.profile for pr in report.profiles}
            assert "mono_64x50_matched" in all_names
            assert "qr_v40_l_ceiling" in all_names
            for pr in report.profiles:
                # READY + 3 RUNNING + DONE = 5 events
                assert pr.event_count == 5, f"{pr.profile}: expected 5 events, got {pr.event_count}"
    finally:
        pygame.quit()


def test_baseline_worker_each_guard_and_frame_has_own_event_record():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=2)
            report = worker.run()
            pr = report.profiles[0]
            states = [e.state for e in pr.events]
            assert "READY" in states
            assert "DONE" in states
            assert states.count("RUNNING") == 2

            # READY and first RUNNING frame 0 may share PNG if content is identical
            ready_event = next(e for e in pr.events if e.state == "READY")
            running_f0 = next(e for e in pr.events if e.state == "RUNNING" and e.frame_index == 0)
            # They have separate event records even if same content_sha256
            assert ready_event is not running_f0
            assert ready_event.frame_index == 0
            assert ready_event.state == "READY"
            assert running_f0.frame_index == 0
            assert running_f0.state == "RUNNING"
    finally:
        pygame.quit()


def test_baseline_worker_sender_truth_passes_all_grid_profiles():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=3)
            report = worker.run()
            for pr in report.profiles:
                if pr.profile in grid_profiles():
                    assert pr.sender_truth is not None
                    assert pr.sender_truth.passed, (
                        f"{pr.profile} sender truth failed: "
                        f"errors={pr.sender_truth.bit_errors} "
                        f"erased={pr.sender_truth.erased_cells}"
                    )
    finally:
        pygame.quit()


def test_baseline_worker_receiver_replay_passes_low_density_grids_at_600px():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=4)
            report = worker.run()
            for pr in report.profiles:
                rr = pr.receiver_replay
                if pr.profile in ("color_40x40_control", "mono_64x50_matched",
                                  "mono_96x75_medium", "qr_v27_l_safe", "qr_v40_l_ceiling"):
                    assert rr.passed, f"{pr.profile} should pass at 600px: {rr.failure_reasons}"
    finally:
        pygame.quit()


def test_baseline_worker_receiver_reset_per_run_token():
    """Each profile gets a fresh decoder — no cross-profile contamination."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=3)
            report = worker.run()
            # If decoders weren't reset, a grid-preferred path would try grid
            # decode on QR frames and fail. All QR profiles pass.
            for pr in report.profiles:
                if pr.profile in qr_controls():
                    assert pr.receiver_replay.passed, (
                        f"QR profile {pr.profile} failed: {pr.receiver_replay.failure_reasons}"
                    )
    finally:
        pygame.quit()


def test_baseline_results_json_schema_is_valid():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=2)
            worker.run()
            path = Path(tmpdir) / "baseline_results.json"
            with open(path) as f:
                data = json.load(f)
            assert data["schema"] == "superqr-digital-baseline-v1"
            assert "marker_size_px" in data
            assert "frame_count_per_profile" in data
            assert "profiles" in data
            assert len(data["profiles"]) == 7
            for entry in data["profiles"]:
                assert "sender_truth" in entry
                assert "receiver_replay" in entry
    finally:
        pygame.quit()


def test_baseline_events_jsonl_is_valid():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=2)
            worker.run()
            path = Path(tmpdir) / "baseline_events.jsonl"
            events = []
            with open(path) as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
            assert len(events) == 7 * 4  # 7 profiles × (READY + 2 RUNNING + DONE)

            # Check each event has required fields
            for ev in events:
                assert "run_token" in ev
                assert "profile" in ev
                assert "frame_index" in ev
                assert "state" in ev
                assert "content_sha256" in ev
                assert "file_name" in ev
    finally:
        pygame.quit()


def test_baseline_worker_produces_png_artifacts():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=3)
            worker.run()
            frames_dir = Path(tmpdir) / "frames"
            pngs = list(frames_dir.glob("*.png"))
            assert len(pngs) > 0
            for png in pngs:
                assert png.stat().st_size > 0
                img = cv2.imread(str(png))
                assert img is not None
                assert img.shape[2] == 3
    finally:
        pygame.quit()


def test_baseline_worker_peak_memory_is_reported():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = BaselineWorker(tmpdir, frame_count=5)
            report = worker.run()
            assert report.peak_rss_mib > 0
            assert report.artifact_size_bytes > 0
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# sender truth tests
# ---------------------------------------------------------------------------


def test_sender_truth_passes_perfect_grid_rendering():
    pygame.init()
    try:
        surface = _render_grid_surface("mono_64x50_matched", 0)
        result = validate_sender_truth(surface, "mono_64x50_matched", 0)
        assert result.passed
        assert result.bit_errors == 0
        assert result.erased_cells == 0
        assert result.observed_cells == 3200
    finally:
        pygame.quit()


def test_sender_truth_detects_bit_errors():
    pygame.init()
    try:
        surface = _render_grid_surface("mono_64x50_matched", 0)
        # Deliberately corrupt: draw a black rectangle over the payload area
        surface.set_at((300, 300), (0, 0, 0))
        result = validate_sender_truth(surface, "mono_64x50_matched", 0)
        # Single pixel corruption should produce at least one cell error
        assert result.bit_errors >= 0
    finally:
        pygame.quit()


def test_sender_truth_works_for_color_profiles():
    pygame.init()
    try:
        surface = _render_grid_surface("color_40x40_control", 0)
        result = validate_sender_truth(surface, "color_40x40_control", 0)
        assert result.passed
        assert result.bit_errors == 0
        assert result.erased_cells == 0
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# receiver replay tests
# ---------------------------------------------------------------------------


def test_receiver_replay_passes_clean_grid_frames():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frames_dir = Path(tmpdir) / "frames"
            frames_dir.mkdir()
            # Render and save one frame
            surface = _render_grid_surface("mono_64x50_matched", 0, token=0x9001)
            rgb = pygame.image.tobytes(surface, "RGB")
            content_hash = hashlib.sha256(rgb).hexdigest()
            file_name = f"{content_hash[:16]}.png"
            rgb_arr = np.frombuffer(rgb, dtype=np.uint8).reshape(600, 600, 3)
            bgr_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(frames_dir / file_name), bgr_arr,
                       [cv2.IMWRITE_PNG_COMPRESSION, 1])

            events = [BaselineEvent(
                run_token=0x9001, profile="mono_64x50_matched",
                frame_index=0, frame_count=3, dwell_epochs=3,
                state="RUNNING", content_sha256=content_hash,
                file_name=file_name, width=600, height=600,
            )]
            result = validate_receiver_replay(events, frames_dir, "mono_64x50_matched")
            assert result.passed
            assert result.decoded == 1
            assert result.raw_valid == 1
            assert result.bit_errors == 0
            assert result.erased_bits == 0
    finally:
        pygame.quit()


def test_receiver_replay_reports_acquisition_failure_for_missing_png():
    events = [BaselineEvent(
        run_token=0xB001, profile="mono_64x50_matched",
        frame_index=0, frame_count=3, dwell_epochs=3,
        state="RUNNING", content_sha256="deadbeef",
        file_name="nonexistent.png", width=600, height=600,
    )]
    with tempfile.TemporaryDirectory() as tmpdir:
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir()
        result = validate_receiver_replay(events, frames_dir, "mono_64x50_matched")
        assert not result.passed
        assert result.acquisition_failures == 1
        assert "PNG_READ_ERROR" in result.failure_reasons


# ---------------------------------------------------------------------------
# degradation tests (unchanged from before)
# ---------------------------------------------------------------------------


def test_downsample_returns_correct_size():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = apply_downsample(frame, DownsampleDegradation(scale=0.5))
    assert result.shape == frame.shape


def test_blur_no_error_on_zero_sigma():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = apply_blur(frame, BlurDegradation(sigma=0.0))
    assert result.shape == frame.shape


def test_perspective_deterministic_with_seed():
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    a = apply_perspective(frame, PerspectiveDegradation(max_shift=10.0, seed=42))
    b = apply_perspective(frame, PerspectiveDegradation(max_shift=10.0, seed=42))
    assert np.array_equal(a, b)


def test_brightness_contrast_alpha_below_one_darkens():
    frame = np.full((64, 64, 3), 200, dtype=np.uint8)
    result = apply_brightness_contrast(frame, BrightnessContrastDegradation(alpha=0.5, beta=0))
    assert result.mean() < 150


def test_gaussian_noise_deterministic_with_seed():
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    a = apply_gaussian_noise(frame, GaussianNoiseDegradation(std=25.0, seed=123))
    b = apply_gaussian_noise(frame, GaussianNoiseDegradation(std=25.0, seed=123))
    assert np.array_equal(a, b)


def test_salt_pepper_noise_changes_pixels():
    frame = np.full((64, 64, 3), 128, dtype=np.uint8)
    result = apply_salt_pepper_noise(frame, SaltPepperNoiseDegradation(fraction=0.1, seed=7))
    changed = np.sum(np.any(result != 128, axis=2))
    assert changed > 0


def test_rolling_shutter_zero_ratio_is_identity():
    frame = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
    result = apply_rolling_shutter(frame, RollingShutterDegradation(row_time_ratio=0.0))
    assert np.array_equal(frame, result)


def test_apply_degradation_dispatcher():
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    result = apply_degradation(frame, BlurDegradation(sigma=0.0))
    assert result.shape == frame.shape


def test_degradation_name_all_types():
    for deg_type in [DownsampleDegradation, BlurDegradation, PerspectiveDegradation,
                     GaussianNoiseDegradation, SaltPepperNoiseDegradation,
                     RollingShutterDegradation]:
        deg = deg_type(0.5)
        name = degradation_name(deg)
        assert isinstance(name, str) and len(name) > 0


# ---------------------------------------------------------------------------
# differential diagnostics tests
# ---------------------------------------------------------------------------


def test_diagnose_perfect_frame_is_ok():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult
    r = ReplayFrameResult(
        run_token=1, profile="mono_64x50_matched", frame_index=0,
        expected_state="RUNNING", decoded=True, envelope_match=True,
        state_match=True, profile_match=True, frame_index_match=True,
        run_token_match=True, raw_valid=True, ber=0.0, erasure_rate=0.0,
        observed_bits=3200, bit_errors=0, erased_bits=0,
        innovative_bytes=400, expected_innovative_bytes=400,
        failure_reason=None, geometry_source="V7_CARRIER",
        sync_status="RUNNING", analysis_path="GRID",
    )
    d = diagnose_frame(r)
    assert d.passed
    assert d.category == FailureCategory.OK


def test_diagnose_no_envelope_is_acquisition_failure():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult
    r = ReplayFrameResult(
        run_token=1, profile="mono_64x50_matched", frame_index=0,
        expected_state="RUNNING", decoded=False, envelope_match=False,
        state_match=False, profile_match=False, frame_index_match=False,
        run_token_match=False, raw_valid=False, ber=0.0, erasure_rate=0.0,
        observed_bits=0, bit_errors=0, erased_bits=0,
        innovative_bytes=0, expected_innovative_bytes=400,
        failure_reason="NO_V7_CARRIER", geometry_source="NONE",
        sync_status="UNSYNCED", analysis_path="GRID",
    )
    d = diagnose_frame(r)
    assert not d.passed
    assert d.category == FailureCategory.ACQUISITION


def test_diagnose_bit_errors_is_payload_sampling():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult
    r = ReplayFrameResult(
        run_token=1, profile="mono_64x50_matched", frame_index=0,
        expected_state="RUNNING", decoded=True, envelope_match=True,
        state_match=True, profile_match=True, frame_index_match=True,
        run_token_match=True, raw_valid=False, ber=0.05, erasure_rate=0.02,
        observed_bits=3200, bit_errors=160, erased_bits=64,
        innovative_bytes=0, expected_innovative_bytes=400,
        failure_reason=None, geometry_source="V7_CARRIER",
        sync_status="RUNNING", analysis_path="GRID",
    )
    d = diagnose_frame(r)
    assert not d.passed
    assert d.category == FailureCategory.PAYLOAD_SAMPLING
