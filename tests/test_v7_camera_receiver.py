import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import cv2
import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.camera_receiver import (
    DecodeResult,
    Phase1CameraDecoder,
    ReceiverMetrics,
)
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_matrix,
    build_run_envelope,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import RunState


def _surface_bgr(surface: pygame.Surface) -> np.ndarray:
    rgb = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _physical_camera_view(surface: pygame.Surface) -> np.ndarray:
    marker = _surface_bgr(surface)
    height, width = marker.shape[:2]
    source = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    destination = np.array([[176, 45], [790, 82], [765, 681], [145, 646]], np.float32)
    transform = cv2.getPerspectiveTransform(source, destination)
    camera = np.full((720, 960, 3), 24, dtype=np.uint8)
    warped = cv2.warpPerspective(marker, transform, (960, 720))
    mask = cv2.warpPerspective(np.full((height, width), 255, np.uint8), transform, (960, 720))
    camera[mask > 0] = warped[mask > 0]
    camera = cv2.GaussianBlur(camera, (3, 3), 0.55)
    return camera


def test_pc_camera_decoder_acquires_and_scores_perspective_grid():
    pygame.init()
    try:
        manifest = load_phy_selection_manifest()
        profile = "mono_64x50_matched"
        sequence = GridFrameSequence(profile)
        frame_index, matrix = sequence.next_frame()
        envelope = build_run_envelope(
            profile, 0xCAFE, frame_index, frame_count=12, dwell_epochs=3,
            state=RunState.RUNNING,
        )
        renderer = LabRenderer(600)
        sync = manifest["run_sync"]
        renderer.prepare_logical_frame(
            matrix,
            payload_bbox=manifest["payload_bbox"],
            sync_bits=envelope.bits(),
            sync_bboxes=(sync["top_bbox"], sync["bottom_bbox"]),
            sync_rows=sync["rows"], sync_cols=sync["cols"],
        )
        result = Phase1CameraDecoder()._decode_grid(
            _physical_camera_view(renderer.cached_frame_display)
        )
        assert result.failure_reason is None
        assert result.envelope == envelope
        assert result.profile == profile
        assert result.finder_count == 4
        assert result.observed_bits == 3200
        assert result.erased_bits == 0
        assert result.bit_errors == 0
        assert result.raw_valid
    finally:
        pygame.quit()


def test_pc_camera_decoder_recovers_binary_qr_envelope():
    pygame.init()
    try:
        control = qr_controls()["qr_v27_l_safe"]
        matrix = build_qr_matrix(
            control, 3, run_token=0x1234, frame_count=9,
            dwell_epochs=3, state=RunState.RUNNING,
        )
        renderer = LabRenderer(600)
        renderer.prepare_qr_matrix(matrix, int(control["quiet_zone_modules"]))
        result = Phase1CameraDecoder()._decode_qr(renderer_to_camera(renderer))
        assert result.failure_reason is None
        assert result.profile == control["name"]
        assert result.envelope is not None
        assert result.envelope.run_token == 0x1234
        assert result.envelope.frame_index == 3
        assert result.raw_valid
    finally:
        pygame.quit()


def renderer_to_camera(renderer: LabRenderer) -> np.ndarray:
    surface = renderer.cached_frame_display
    assert surface is not None
    frame = _surface_bgr(surface)
    # A white surround keeps the standard quiet zone intact.
    return cv2.copyMakeBorder(frame, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def test_all_profiles_use_identical_outer_camera_footprint():
    pygame.init()
    try:
        for marker_size in (600, 700, 800):
            renderer = LabRenderer(marker_size)
            for control in qr_controls().values():
                matrix = build_qr_matrix(control, 0)
                renderer.prepare_qr_matrix(matrix, int(control["quiet_zone_modules"]))
                assert renderer.cached_frame_display.get_size() == (marker_size, marker_size)
                layout = renderer.qr_layout(int(control["total_modules"]))
                assert layout["canvas_size_px"] == marker_size
                assert layout["rendered_size_px"] <= marker_size
                assert layout["integer_module_scale_px"] >= 1
    finally:
        pygame.quit()


def test_receiver_counts_innovative_valid_frame_only_once():
    metrics = ReceiverMetrics()
    envelope = build_run_envelope(
        "qr_v27_l_safe", 0x8888, 7, frame_count=20, dwell_epochs=3,
        state=RunState.RUNNING,
    )
    result = DecodeResult(
        path="QR", envelope=envelope, profile="qr_v27_l_safe",
        frame_index=7, observed_bits=1465 * 8, valid_samples=1465 * 8,
        raw_valid=True, inner_fec_valid=True,
    )
    first = metrics.record(result, 2.0, 1_000_000_000)
    duplicate = metrics.record(result, 2.0, 1_010_000_000)
    assert first == qr_controls()["qr_v27_l_safe"]["frame_bytes"]
    assert duplicate == 0
