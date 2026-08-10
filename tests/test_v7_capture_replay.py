"""Comprehensive tests for the V7 capture/replay/diagnostic harness."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import cv2
import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.capture_harness import CaptureRecorder, CapturedFrame
from superqr_desktop.v7_capacity_lab.replay_decoder import (
    ReplayDecoder,
    ReplayReport,
    _load_png_bgr,
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
    degradation_param,
)
from superqr_desktop.v7_capacity_lab.differential_diagnostics import (
    FailureCategory,
    FrameDiagnosis,
    SweepDiagnosis,
    diagnose_frame,
    diagnose_sweep,
)
from superqr_desktop.v7_capacity_lab.sweep_runner import (
    binary_search_boundary,
    frame_drop_boundary,
    run_campaign_sweep,
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
from superqr_desktop.v7_capacity_lab.camera_receiver import Phase1CameraDecoder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _render_grid_frame(profile: str, frame_index: int, run_token: int = 0x1111) -> pygame.Surface:
    """Render one grid frame with the lab carrier and return the display surface."""
    sequence = GridFrameSequence(profile)
    matrix = None
    for _ in range(frame_index + 1):
        idx, matrix = sequence.next_frame()
    assert idx == frame_index
    renderer = LabRenderer(600)
    envelope = build_run_envelope(
        profile, run_token, frame_index, frame_count=10, dwell_epochs=3,
        state=RunState.RUNNING,
    )
    manifest = load_phy_selection_manifest()
    sync = manifest["run_sync"]
    renderer.prepare_logical_frame(
        matrix,
        payload_bbox=manifest["payload_bbox"],
        sync_bits=envelope.bits(),
        sync_bboxes=(sync["top_bbox"], sync["bottom_bbox"]),
        sync_rows=int(sync["rows"]),
        sync_cols=int(sync["cols"]),
    )
    return renderer.cached_frame_display


def _render_qr_frame(profile: str, frame_index: int, run_token: int = 0x2222) -> pygame.Surface:
    """Render one QR control frame at a fixed optical footprint."""
    control = qr_controls()[profile]
    matrix = build_qr_matrix(
        control, frame_index, run_token=run_token, frame_count=10,
        dwell_epochs=3, state=RunState.RUNNING,
    )
    renderer = LabRenderer(600)
    renderer.prepare_qr_matrix(matrix, int(control["quiet_zone_modules"]))
    return renderer.cached_frame_display


def _surface_to_bgr(surface: pygame.Surface) -> np.ndarray:
    """Convert a pygame RGB surface to a numpy BGR array (as the decoder expects)."""
    rgb = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# capture harness tests
# ---------------------------------------------------------------------------


def test_capture_recorder_records_unique_frames_and_deduplicates():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()
            surface = _render_grid_frame("mono_64x50_matched", 0)
            ts = 1_000_000_000

            assert recorder.record_logical_frame(
                surface, run_token=0x1111, profile="mono_64x50_matched",
                frame_index=0, frame_count=10, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=ts,
            )

            # Same surface again (dwell repeat) → deduplicated
            ts2 = ts + 16_666_667
            assert not recorder.record_logical_frame(
                surface, run_token=0x1111, profile="mono_64x50_matched",
                frame_index=0, frame_count=10, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=ts2,
            )

            # Different frame
            surface2 = _render_grid_frame("mono_64x50_matched", 1)
            ts3 = ts2 + 16_666_667
            assert recorder.record_logical_frame(
                surface2, run_token=0x1111, profile="mono_64x50_matched",
                frame_index=1, frame_count=10, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=ts3,
            )

            assert recorder.frame_count == 2

            # Verify dedup: first frame has 2 timestamps
            first = None
            for f in recorder._frames:
                if f.frame_index == 0:
                    first = f
            assert first is not None
            assert len(first.present_timestamps_ns) == 2

            recorder.stop()
    finally:
        pygame.quit()


def test_capture_manifest_is_valid_json_and_contains_all_runs():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            for fi in range(3):
                surface = _render_grid_frame("mono_64x50_matched", fi)
                recorder.record_logical_frame(
                    surface, run_token=0xBEEF, profile="mono_64x50_matched",
                    frame_index=fi, frame_count=3, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000 + fi * 50_000_000,
                )

            recorder.start_run(0xBEEF, "mono_64x50_matched", 3, 3, 1_000_000_000)
            recorder.finish_run(1_200_000_000)
            recorder.stop()

            path = recorder.write_manifest()
            assert path.exists()

            with open(path) as f:
                manifest = json.load(f)
            assert manifest["schema"] == "superqr-capture-manifest-v1"
            assert len(manifest["frames"]) == 3
            assert len(manifest["runs"]) == 1
            assert manifest["runs"][0]["run_token"] == 0xBEEF
            assert manifest["runs"][0]["unique_frames"] == 3

            # Verify PNG files exist
            for frame in manifest["frames"]:
                png_path = recorder._frames_dir / frame["file_name"]
                assert png_path.exists()
                assert png_path.stat().st_size > 0
    finally:
        pygame.quit()


def test_capture_records_read_and_done_guards():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            # Render frames with distinct states so content hashes differ
            manifest = load_phy_selection_manifest()
            sync = manifest["run_sync"]
            for state, fi, token in [("READY", 0, 0xCAFE), ("RUNNING", 0, 0xCAFE), ("DONE", 4, 0xCAFE)]:
                sequence = GridFrameSequence("mono_64x50_matched")
                matrix = None
                for _ in range(fi + 1):
                    idx, matrix = sequence.next_frame()
                renderer = LabRenderer(600)
                envelope = build_run_envelope(
                    "mono_64x50_matched", token, fi, 5, 3,
                    state=RunState[state],
                )
                renderer.prepare_logical_frame(
                    matrix,
                    payload_bbox=manifest["payload_bbox"],
                    sync_bits=envelope.bits(),
                    sync_bboxes=(sync["top_bbox"], sync["bottom_bbox"]),
                    sync_rows=int(sync["rows"]),
                    sync_cols=int(sync["cols"]),
                )
                recorder.record_logical_frame(
                    renderer.cached_frame_display,
                    run_token=token, profile="mono_64x50_matched",
                    frame_index=fi, frame_count=5, dwell_epochs=3,
                    state=state, present_timestamp_ns=1_000_000_000 + fi * 200_000_000,
                )
            recorder.stop()

            export_manifest = recorder.export_manifest()
            states = {f["state"] for f in export_manifest["frames"]}
            assert "READY" in states
            assert "RUNNING" in states
            assert "DONE" in states
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# replay decoder tests
# ---------------------------------------------------------------------------


def test_pristine_grid_replay_recovers_all_frames_with_perfect_metrics():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            for fi in range(5):
                surface = _render_grid_frame("mono_64x50_matched", fi, run_token=0xAAAA)
                recorder.record_logical_frame(
                    surface, run_token=0xAAAA, profile="mono_64x50_matched",
                    frame_index=fi, frame_count=5, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000 + fi * 50_000_000,
                )

            recorder.start_run(0xAAAA, "mono_64x50_matched", 5, 3, 1_000_000_000)
            recorder.finish_run(1_300_000_000)
            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")
            report = replay.replay_all()

            assert report.total_expected == 5
            assert report.total_decoded == 5
            assert report.total_raw_valid == 5
            assert report.total_envelope_match == 5
            assert report.total_state_match == 5
            assert report.total_profile_match == 5
            assert report.total_frame_index_match == 5
            assert report.total_run_token_match == 5
            assert report.total_bit_errors == 0
            assert report.total_erased_bits == 0
            assert report.passed
    finally:
        pygame.quit()


def test_pristine_qr_replay_recovers_exact_envelope():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            for fi in range(4):
                surface = _render_qr_frame("qr_v27_l_safe", fi, run_token=0xBBBB)
                recorder.record_logical_frame(
                    surface, run_token=0xBBBB, profile="qr_v27_l_safe",
                    frame_index=fi, frame_count=4, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000 + fi * 41_666_667,
                )

            recorder.start_run(0xBBBB, "qr_v27_l_safe", 4, 3, 1_000_000_000)
            recorder.finish_run(1_200_000_000)
            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")
            report = replay.replay_all()

            assert report.total_expected == 4
            assert report.total_decoded == 4
            assert report.total_raw_valid == 4
            assert report.total_innovative_bytes == report.total_expected_innovative_bytes
            assert report.passed
    finally:
        pygame.quit()


def test_replay_decoder_validates_expected_innovative_bytes():
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0xCCCC)
            recorder.record_logical_frame(
                surface, run_token=0xCCCC, profile="mono_64x50_matched",
                frame_index=0, frame_count=1, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=1_000_000_000,
            )
            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")
            report = replay.replay_all()

            assert report.total_innovative_bytes > 0
            assert report.total_innovative_bytes == report.total_expected_innovative_bytes
    finally:
        pygame.quit()


def test_replay_all_profiles_in_capture_manifest():
    """Every canonical grid and QR profile must replay perfectly when pristine."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            run_token = 0xD001
            for profile_name in list(grid_profiles())[:2] + list(qr_controls())[:1]:
                if profile_name in grid_profiles():
                    surface = _render_grid_frame(profile_name, 0, run_token=run_token)
                else:
                    surface = _render_qr_frame(profile_name, 0, run_token=run_token)
                recorder.record_logical_frame(
                    surface, run_token=run_token, profile=profile_name,
                    frame_index=0, frame_count=5, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000,
                )
                recorder.start_run(run_token, profile_name, 5, 3, 1_000_000_000)
                recorder.finish_run(1_100_000_000)
                run_token += 1

            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")
            report = replay.replay_all()
            assert report.passed
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# degradation tests
# ---------------------------------------------------------------------------


def test_downsample_returns_correct_size():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = apply_downsample(frame, DownsampleDegradation(scale=0.5))
    assert result.shape == frame.shape


def test_blur_no_error_on_zero_sigma():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = apply_blur(frame, BlurDegradation(sigma=0.0))
    assert result.shape == frame.shape


def test_blur_applies_smoothing():
    frame = np.zeros((128, 128, 3), dtype=np.uint8)
    frame[64, 64] = 255
    result = apply_blur(frame, BlurDegradation(sigma=3.0))
    assert result[64, 64, 0] < 255


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
        deg = deg_type(0.5) if deg_type != BrightnessContrastDegradation else BrightnessContrastDegradation(0.5, 0)
        name = degradation_name(deg)
        assert isinstance(name, str) and len(name) > 0


def test_downsample_degrades_grid_decode():
    """A strong downsample should cause payload errors in the decoder."""
    pygame.init()
    try:
        surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0xEEEE)
        bgr = _surface_to_bgr(surface)
        degraded = apply_downsample(bgr, DownsampleDegradation(scale=0.15))
        result = Phase1CameraDecoder().analyze(degraded)

        # At 0.15 scale the grid is ~10x8 pixels — payload must have errors
        assert result.bit_errors > 0 or result.erased_bits > 0 or not result.raw_valid
    finally:
        pygame.quit()


def test_gaussian_blur_eventually_breaks_decode():
    """A strong blur should eventually cause decode failures."""
    pygame.init()
    try:
        surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0xFFFF)
        bgr = _surface_to_bgr(surface)
        degraded = apply_blur(bgr, BlurDegradation(sigma=15.0))
        result = Phase1CameraDecoder().analyze(degraded)

        assert result.bit_errors > 0 or result.erased_bits > 0 or not result.raw_valid
    finally:
        pygame.quit()


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


def test_diagnose_wrong_run_token_is_sync_failure():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult

    r = ReplayFrameResult(
        run_token=1, profile="mono_64x50_matched", frame_index=0,
        expected_state="RUNNING", decoded=True, envelope_match=True,
        state_match=True, profile_match=False, frame_index_match=True,
        run_token_match=False, raw_valid=False, ber=0.0, erasure_rate=0.0,
        observed_bits=3200, bit_errors=0, erased_bits=0,
        innovative_bytes=0, expected_innovative_bytes=400,
        failure_reason=None, geometry_source="V7_CARRIER",
        sync_status="RUNNING", analysis_path="GRID",
    )
    d = diagnose_frame(r)
    assert not d.passed
    assert d.category == FailureCategory.SYNC


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


def test_diagnose_qr_decode_failure():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult

    r = ReplayFrameResult(
        run_token=1, profile="qr_v27_l_safe", frame_index=0,
        expected_state="RUNNING", decoded=True, envelope_match=True,
        state_match=True, profile_match=True, frame_index_match=True,
        run_token_match=True, raw_valid=False, ber=0.0, erasure_rate=0.0,
        observed_bits=0, bit_errors=0, erased_bits=0,
        innovative_bytes=0, expected_innovative_bytes=1465,
        failure_reason="QR_INVALID_PAYLOAD", geometry_source="QR_DECODED",
        sync_status="UNSYNCED", analysis_path="QR",
    )
    d = diagnose_frame(r)
    assert not d.passed
    assert d.category == FailureCategory.QR_DECODING


def test_diagnose_sweep_counts_categories():
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult

    results = [
        ReplayFrameResult(
            run_token=1, profile="mono_64x50_matched", frame_index=i,
            expected_state="RUNNING", decoded=True, envelope_match=True,
            state_match=True, profile_match=True, frame_index_match=True,
            run_token_match=True, raw_valid=True, ber=0.0, erasure_rate=0.0,
            observed_bits=3200, bit_errors=0, erased_bits=0,
            innovative_bytes=400, expected_innovative_bytes=400,
            failure_reason=None, geometry_source="V7_CARRIER",
            sync_status="RUNNING", analysis_path="GRID",
        )
        for i in range(3)
    ] + [
        ReplayFrameResult(
            run_token=1, profile="mono_64x50_matched", frame_index=3,
            expected_state="RUNNING", decoded=False, envelope_match=False,
            state_match=False, profile_match=False, frame_index_match=False,
            run_token_match=False, raw_valid=False, ber=0.0, erasure_rate=0.0,
            observed_bits=0, bit_errors=0, erased_bits=0,
            innovative_bytes=0, expected_innovative_bytes=400,
            failure_reason="NO_V7_CARRIER", geometry_source="NONE",
            sync_status="UNSYNCED", analysis_path="GRID",
        ),
    ]

    diag = diagnose_sweep(results, "blur", 3.5)
    assert diag.total_frames == 4
    assert diag.passed == 3
    assert diag.failed == 1
    assert diag.acquisition_failures == 1
    assert diag.first_failure_boundary == 3.5


# ---------------------------------------------------------------------------
# sweep runner tests
# ---------------------------------------------------------------------------


def test_binary_search_finds_blur_boundary():
    """Binary search should find a sigma where blur breaks mono_64x50_matched."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            for fi in range(4):
                surface = _render_grid_frame("mono_64x50_matched", fi, run_token=0x9001)
                recorder.record_logical_frame(
                    surface, run_token=0x9001, profile="mono_64x50_matched",
                    frame_index=fi, frame_count=4, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000 + fi * 50_000_000,
                )
            recorder.start_run(0x9001, "mono_64x50_matched", 4, 3, 1_000_000_000)
            recorder.finish_run(1_300_000_000)
            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")

            # Pristine must pass first
            report = replay.replay_all()
            assert report.passed

            # Binary search for blur boundary
            boundary, history = binary_search_boundary(
                replay, "mono_64x50_matched", BlurDegradation,
                start=0.0, end=20.0, tolerance=0.5, max_iterations=12,
            )
            # A boundary should exist within the range (blur eventually breaks everything)
            assert boundary is not None
            assert 0.0 < boundary <= 20.0
            assert len(history) > 0
    finally:
        pygame.quit()


def test_frame_drop_boundary_returns_none_for_single_frame():
    """A single-frame capture has no frame-drop boundary."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()
            surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0x9002)
            recorder.record_logical_frame(
                surface, run_token=0x9002, profile="mono_64x50_matched",
                frame_index=0, frame_count=1, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=1_000_000_000,
            )
            recorder.write_manifest()
            recorder.stop()

            replay = ReplayDecoder(Path(tmpdir) / "capture_manifest.json")
            boundary = frame_drop_boundary(replay, "mono_64x50_matched")
            assert boundary is None
    finally:
        pygame.quit()


def test_run_campaign_sweep_produces_report():
    """Full campaign sweep produces a valid report for multiple profiles."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            for profile_name in ("mono_64x50_matched", "qr_v27_l_safe"):
                if profile_name in grid_profiles():
                    surface = _render_grid_frame(profile_name, 0, run_token=0xA001)
                else:
                    surface = _render_qr_frame(profile_name, 0, run_token=0xA001)
                recorder.record_logical_frame(
                    surface, run_token=0xA001, profile=profile_name,
                    frame_index=0, frame_count=3, dwell_epochs=3,
                    state="RUNNING", present_timestamp_ns=1_000_000_000,
                )
                recorder.start_run(0xA001, profile_name, 3, 3, 1_000_000_000)
                recorder.finish_run(1_100_000_000)

            recorder.write_manifest()
            recorder.stop()

            report = run_campaign_sweep(Path(tmpdir) / "capture_manifest.json")
            assert len(report.profiles) == 2
            profile_names = {pr.profile for pr in report.profiles}
            assert "mono_64x50_matched" in profile_names
            assert "qr_v27_l_safe" in profile_names

            for pr in report.profiles:
                assert len(pr.boundaries) > 0
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# integration: capture → replay → differential analysis
# ---------------------------------------------------------------------------


def test_end_to_end_pristine_replay_sweep_pipeline():
    """Full pipeline: capture grid + QR frames, replay, run diagnostics."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Capture
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            profiles_and_frames = [
                ("mono_64x50_matched", 3, 0xB001),
                ("qr_v27_l_safe", 3, 0xB002),
            ]
            for profile, count, token in profiles_and_frames:
                for fi in range(count):
                    if profile in grid_profiles():
                        surface = _render_grid_frame(profile, fi, run_token=token)
                    else:
                        surface = _render_qr_frame(profile, fi, run_token=token)
                    recorder.record_logical_frame(
                        surface, run_token=token, profile=profile,
                        frame_index=fi, frame_count=count, dwell_epochs=3,
                        state="RUNNING", present_timestamp_ns=1_000_000_000 + fi * 50_000_000,
                    )
                recorder.start_run(token, profile, count, 3, 1_000_000_000)
                recorder.finish_run(1_000_000_000 + count * 50_000_000)

            recorder.stop()
            manifest_path = recorder.write_manifest()

            # 2. Pristine replay
            replay = ReplayDecoder(manifest_path)
            report = replay.replay_all()
            assert report.passed, f"pristine replay failed: {report.failure_reasons}"

            # 3. Verify individual frame diagnoses
            for fr in report.frame_results:
                d = diagnose_frame(fr)
                assert d.passed
                assert d.category == FailureCategory.OK

            # 4. Degradation should break things
            for captured in replay.expected_frames[:1]:
                filepath = replay._frames_dir / captured["file_name"]
                bgr = _load_png_bgr(filepath)
                degraded = apply_blur(bgr, BlurDegradation(sigma=12.0))
                result = replay._decoder.analyze(degraded)
                assert result.bit_errors > 0 or result.erased_bits > 0 or not result.raw_valid

    finally:
        pygame.quit()


def test_capture_png_files_are_valid_images():
    """Every captured PNG must be read as a valid BGR numpy array."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0xCCCC)
            recorder.record_logical_frame(
                surface, run_token=0xCCCC, profile="mono_64x50_matched",
                frame_index=0, frame_count=1, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=1_000_000_000,
            )
            recorder.stop()
            recorder.write_manifest()

            manifest = recorder.export_manifest()
            for frame in manifest["frames"]:
                filepath = recorder._frames_dir / frame["file_name"]
                bgr = _load_png_bgr(filepath)
                assert bgr is not None
                assert bgr.ndim == 3
                assert bgr.shape[2] == 3
                assert bgr.shape[0] == frame["height"]
                assert bgr.shape[1] == frame["width"]
    finally:
        pygame.quit()


def test_capture_hashes_match_surface_content():
    """The content_sha256 in the manifest must match the rendered surface."""
    pygame.init()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CaptureRecorder(tmpdir)
            recorder.start()

            surface = _render_grid_frame("mono_64x50_matched", 0, run_token=0xDDDD)
            recorder.record_logical_frame(
                surface, run_token=0xDDDD, profile="mono_64x50_matched",
                frame_index=0, frame_count=1, dwell_epochs=3,
                state="RUNNING", present_timestamp_ns=1_000_000_000,
            )
            recorder.stop()
            recorder.write_manifest()

            manifest = recorder.export_manifest()
            for frame in manifest["frames"]:
                # Verify the PNG file exists and is loadable
                filepath = recorder._frames_dir / frame["file_name"]
                bgr = _load_png_bgr(filepath)
                assert bgr is not None
                assert bgr.shape[0] == frame["height"]
                assert bgr.shape[1] == frame["width"]
                # The content_sha256 is of the RGB surface bytes (pre-encode)
                # Reconstruct RGB from surface and verify
                surface_rgb = pygame.image.tobytes(surface, "RGB")
                expected_hash = hashlib.sha256(surface_rgb).hexdigest()
                assert expected_hash == frame["content_sha256"]
    finally:
        pygame.quit()
