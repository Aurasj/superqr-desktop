"""Desktop-camera receiver and scorer for the lab-only V7 Phase 1 campaign.

The module deliberately consumes the Phase 1 manifest and test payloads.  It is
not the production V7 modem.  Its purpose is to make screen/camera experiments
repeatable on a PC before involving an Android camera pipeline.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import platform
import threading
import time
from typing import Any, Callable

import cv2
import numpy as np
import zxingcpp

from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_control_payload,
    grid_profiles,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState


CANONICAL_SIZE = 1000


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    fps: float = 30.0
    backend: str = "AUTO"


@dataclass(frozen=True)
class CameraProbe:
    index: int
    backend: str
    width: int
    height: int
    fps: float
    name: str


@dataclass
class DecodeResult:
    path: str
    geometry_source: str = "NONE"
    sync_status: str = "UNSYNCED"
    failure_reason: str | None = None
    envelope: LabRunEnvelope | None = None
    profile: str = "UNKNOWN"
    frame_index: int | None = None
    quad: np.ndarray | None = None
    finder_centers: np.ndarray | None = None
    candidate_count: int = 0
    finder_count: int = 0
    observed_bits: int = 0
    erased_bits: int = 0
    bit_errors: int = 0
    valid_samples: int = 0
    raw_valid: bool = False
    inner_fec_valid: bool = False
    contrast: float = 0.0
    geometry_ms: float = 0.0
    sync_ms: float = 0.0
    payload_ms: float = 0.0
    qr_ms: float = 0.0


@dataclass(frozen=True)
class ReceiverSnapshot:
    state: str
    camera: str
    capture_width: int
    capture_height: int
    requested_mode: str
    capture_fps: float
    analysis_fps: float
    analyzed_frames: int
    scored_frames: int
    profile: str
    run_token: int | None
    run_state: str
    frame_index: int | None
    unique_frames: int
    frame_count: int
    geometry_state: str
    sync_state: str
    finder_count: int
    candidate_count: int
    ber: float
    erasure_rate: float
    raw_valid_yield: float
    pipeline_mean_ms: float
    pipeline_p95_ms: float
    failure_reason: str
    failure_counts: dict[str, int]
    error: str | None


def _backend_id(name: str) -> int:
    normalized = name.upper()
    if normalized == "DSHOW":
        return cv2.CAP_DSHOW
    if normalized == "MSMF":
        return cv2.CAP_MSMF
    return cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY


def open_camera(config: CameraConfig) -> cv2.VideoCapture:
    """Open a camera and request a mode; callers must inspect negotiated mode."""
    cap = cv2.VideoCapture(config.index, _backend_id(config.backend))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(
            f"Camera {config.index} did not open with "
            f"{config.backend if config.backend != 'AUTO' else 'the preferred backend'}"
        )
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    cap.set(cv2.CAP_PROP_FPS, config.fps)
    return cap


def probe_cameras(max_indices: int = 6) -> list[CameraProbe]:
    probes: list[CameraProbe] = []
    backend_name = "DSHOW" if platform.system() == "Windows" else "AUTO"
    names: list[str] = []
    if platform.system() == "Windows":
        try:
            import pygame.camera
            pygame.camera.init()
            names = [str(name) for name in pygame.camera.list_cameras()]
            pygame.camera.quit()
        except Exception:
            names = []
    indices = range(min(max_indices, len(names))) if names else range(max_indices)
    for index in indices:
        cap = cv2.VideoCapture(index, _backend_id(backend_name))
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        if ok:
            backend = cap.getBackendName()
            height, width = frame.shape[:2]
            probes.append(CameraProbe(
                index=index,
                backend=backend,
                width=width,
                height=height,
                fps=float(cap.get(cv2.CAP_PROP_FPS)),
                name=(names[index] if index < len(names) else f"Camera {index}"),
            ))
        cap.release()
    return probes


def _order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    result = np.empty((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    result[0] = points[np.argmin(sums)]
    result[2] = points[np.argmax(sums)]
    result[1] = points[np.argmin(diffs)]
    result[3] = points[np.argmax(diffs)]
    return result


def _bbox_mean(image: np.ndarray, bbox: list[float]) -> np.ndarray:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, round(bbox[0] * width / CANONICAL_SIZE)))
    y1 = max(0, min(height - 1, round(bbox[1] * height / CANONICAL_SIZE)))
    x2 = max(x1 + 1, min(width, round(bbox[2] * width / CANONICAL_SIZE)))
    y2 = max(y1 + 1, min(height, round(bbox[3] * height / CANONICAL_SIZE)))
    return image[y1:y2, x1:x2].mean(axis=(0, 1))


class Phase1CameraDecoder:
    """Decode V7 lab grids and standard-QR controls from BGR camera frames."""

    def __init__(self):
        self.manifest = load_phy_selection_manifest()
        self._profiles = list(grid_profiles()) + list(qr_controls())
        self._qr = cv2.QRCodeDetector()
        self._grid_reference: dict[str, list[np.ndarray]] = {}
        self._grid_sequences: dict[str, GridFrameSequence] = {}
        self._preferred_path: str | None = None
        self._path_misses = 0

    def analyze(self, frame: np.ndarray) -> DecodeResult:
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("camera frame must be BGR")

        # Stay on a synchronized carrier until it has genuinely disappeared.
        # During search, alternate the expensive QR decoder with grid geometry.
        if self._preferred_path == "GRID":
            first, second = self._decode_grid, self._decode_qr
        elif self._preferred_path == "QR":
            first, second = self._decode_qr, self._decode_grid
        else:
            first, second = self._decode_grid, self._decode_qr
        result = first(frame)
        if result.envelope is None:
            self._path_misses += 1
            if self._preferred_path is None or self._path_misses >= 3:
                alternate = second(frame)
                if alternate.envelope is not None or (
                    alternate.failure_reason == "QR_NOT_DECODED"
                    and result.failure_reason == "NO_V7_CARRIER"
                ):
                    result = alternate
        if result.envelope is not None:
            self._preferred_path = result.path
            self._path_misses = 0
        elif self._path_misses >= 8:
            self._preferred_path = None
        return result

    def _quad_candidates(self, gray: np.ndarray) -> list[np.ndarray]:
        frame_area = gray.shape[0] * gray.shape[1]
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        canny = cv2.Canny(gray, 45, 145)
        candidates: list[tuple[float, np.ndarray]] = []
        for mask in (binary, canny):
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = abs(cv2.contourArea(contour))
                if area < frame_area * 0.025 or area > frame_area * 0.98:
                    continue
                perimeter = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
                if len(approx) != 4 or not cv2.isContourConvex(approx):
                    continue
                quad = _order_quad(approx[:, 0, :])
                sides = [np.linalg.norm(quad[(i + 1) % 4] - quad[i]) for i in range(4)]
                if min(sides) < 45 or max(sides) / max(1.0, min(sides)) > 3.0:
                    continue
                duplicate = any(np.mean(np.linalg.norm(quad - old, axis=1)) < 8 for _, old in candidates)
                if not duplicate:
                    candidates.append((area, quad))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [quad for _, quad in candidates[:18]]

    def _warp_candidate(self, frame: np.ndarray, quad: np.ndarray, edge: float) -> tuple[np.ndarray, np.ndarray]:
        destination = np.array(
            [[edge, edge], [CANONICAL_SIZE - edge, edge],
             [CANONICAL_SIZE - edge, CANONICAL_SIZE - edge], [edge, CANONICAL_SIZE - edge]],
            dtype=np.float32,
        )
        homography = cv2.getPerspectiveTransform(quad, destination)
        return cv2.warpPerspective(frame, homography, (CANONICAL_SIZE, CANONICAL_SIZE)), homography

    def _finder_evidence(self, warped_gray: np.ndarray) -> tuple[int, np.ndarray]:
        centers = []
        valid = 0
        for finder in self.manifest["acquisition_carrier"]["finder_patterns"]:
            outer = float(_bbox_mean(warped_gray, finder["outer_bbox"]))
            inner = float(_bbox_mean(warped_gray, finder["inner_bbox"]))
            core = float(_bbox_mean(warped_gray, finder["core_bbox"]))
            contrast = inner - (outer + core) / 2.0
            if contrast >= 22 and inner > outer + 15 and inner > core + 15:
                valid += 1
            bbox = finder["outer_bbox"]
            centers.append(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
        return valid, np.asarray(centers, dtype=np.float32)

    def _decode_sync_bbox(self, warped_gray: np.ndarray, bbox: list[float]) -> tuple[LabRunEnvelope | None, float]:
        sync = self.manifest["run_sync"]
        rows, cols = int(sync["rows"]), int(sync["cols"])
        x1, y1, x2, y2 = map(int, bbox)
        cells = cv2.resize(warped_gray[y1:y2, x1:x2], (cols, rows), interpolation=cv2.INTER_AREA)
        low, high = np.percentile(cells, (10, 90))
        contrast = float(high - low)
        if contrast < 18:
            return None, contrast
        threshold = float(low + high) / 2.0
        bits = (cells.reshape(-1) > threshold).astype(np.uint8)
        packet = np.packbits(bits, bitorder="big").tobytes()
        try:
            return LabRunEnvelope.decode(packet), contrast
        except (ValueError, KeyError):
            return None, contrast

    def _decode_grid(self, frame: np.ndarray) -> DecodeResult:
        result = DecodeResult(path="GRID", failure_reason="NO_V7_CARRIER")
        started = time.perf_counter_ns()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        candidates = self._quad_candidates(gray)
        result.candidate_count = len(candidates)
        result.geometry_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        best_finders = 0
        best_quad = candidates[0] if candidates else None
        sync_started = time.perf_counter_ns()
        for quad in candidates:
            for edge in self.manifest["acquisition_carrier"]["candidate_contour_edges"]:
                warped, homography = self._warp_candidate(frame, quad, float(edge))
                warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
                finder_count, canonical_finders = self._finder_evidence(warped_gray)
                if finder_count > best_finders:
                    best_finders, best_quad = finder_count, quad
                if finder_count < 4:
                    continue
                top, top_contrast = self._decode_sync_bbox(warped_gray, self.manifest["run_sync"]["top_bbox"])
                bottom, bottom_contrast = self._decode_sync_bbox(warped_gray, self.manifest["run_sync"]["bottom_bbox"])
                if top is None or bottom is None or top != bottom:
                    result.failure_reason = "V7_SYNC_INVALID"
                    result.contrast = max(result.contrast, min(top_contrast, bottom_contrast))
                    continue
                if top.profile_id >= len(self._profiles) or self._profiles[top.profile_id] not in grid_profiles():
                    continue
                inverse = np.linalg.inv(homography)
                camera_finders = cv2.perspectiveTransform(canonical_finders.reshape(1, -1, 2), inverse)[0]
                result.geometry_source = "V7_CARRIER"
                result.sync_status = top.state.name
                result.failure_reason = None
                result.envelope = top
                result.profile = self._profiles[top.profile_id]
                result.frame_index = top.frame_index
                result.quad = quad
                result.finder_centers = camera_finders
                result.finder_count = finder_count
                result.contrast = min(top_contrast, bottom_contrast)
                if top.state == RunState.RUNNING:
                    self._score_grid(result, warped, top)
                result.sync_ms = (time.perf_counter_ns() - sync_started) / 1_000_000.0
                return result
        result.finder_count = best_finders
        result.quad = best_quad
        if candidates and best_finders < 4:
            result.failure_reason = f"V7_FINDERS_{best_finders}_OF_4"
        result.sync_ms = (time.perf_counter_ns() - sync_started) / 1_000_000.0
        return result

    def _grid_reference_frame(self, profile: str, index: int) -> np.ndarray:
        cached = self._grid_reference.setdefault(profile, [])
        sequence = self._grid_sequences.setdefault(profile, GridFrameSequence(profile))
        if len(cached) <= index:
            for _ in range(len(cached), index + 1):
                _, matrix = sequence.next_frame()
                cached.append(np.asarray(matrix.symbols, dtype=np.uint8))
        return cached[index]

    def _score_grid(self, result: DecodeResult, warped: np.ndarray, envelope: LabRunEnvelope) -> None:
        started = time.perf_counter_ns()
        profile = grid_profiles()[result.profile]
        rows, cols = int(profile["rows"]), int(profile["cols"])
        bits_per_cell = int(profile["bits_per_cell"])
        x1, y1, x2, y2 = map(int, self.manifest["payload_bbox"])
        cells = cv2.resize(warped[y1:y2, x1:x2], (cols, rows), interpolation=cv2.INTER_AREA)
        reference = self._grid_reference_frame(result.profile, envelope.frame_index)
        if bits_per_cell == 1:
            gray = cv2.cvtColor(cells, cv2.COLOR_BGR2GRAY).astype(np.float32)
            pilots = {item["name"]: item for item in self.manifest["acquisition_carrier"]["pilots"]}
            black = float(_bbox_mean(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), pilots["BLACK"]["core_bbox"]))
            white = float(_bbox_mean(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), pilots["WHITE"]["core_bbox"]))
            contrast = max(1.0, white - black)
            threshold = (black + white) / 2.0
            symbols = (gray > threshold).astype(np.uint8)
            confidence = np.abs(gray - threshold) / (contrast / 2.0)
            erased = confidence < 0.22
            xor = np.bitwise_xor(symbols, reference)
            errors = int(np.count_nonzero(xor[~erased]))
            erased_bits = int(np.count_nonzero(erased))
            result.contrast = contrast
        else:
            pilot_defs = {item["name"]: item for item in self.manifest["acquisition_carrier"]["pilots"]}
            prototypes = np.stack([
                _bbox_mean(warped, pilot_defs[name]["core_bbox"])
                for name in ("BLACK", "WHITE", "RED", "BLUE")
            ]).astype(np.float32)
            lab_cells = cv2.cvtColor(cells, cv2.COLOR_BGR2LAB).astype(np.float32)
            lab_prototypes = cv2.cvtColor(prototypes.reshape(1, 4, 3).astype(np.uint8), cv2.COLOR_BGR2LAB)[0].astype(np.float32)
            distances = np.linalg.norm(lab_cells[:, :, None, :] - lab_prototypes[None, None, :, :], axis=3)
            order = np.sort(distances, axis=2)
            symbols = np.argmin(distances, axis=2).astype(np.uint8)
            erased = (order[:, :, 1] - order[:, :, 0]) < 10.0
            xor = np.bitwise_xor(symbols, reference)
            bit_errors = np.vectorize(lambda value: int(value).bit_count(), otypes=[np.uint8])(xor)
            errors = int(bit_errors[~erased].sum())
            erased_bits = int(np.count_nonzero(erased) * bits_per_cell)
            result.contrast = float(np.mean(order[:, :, 1] - order[:, :, 0]))
        result.observed_bits = rows * cols * bits_per_cell
        result.erased_bits = erased_bits
        result.bit_errors = errors
        result.valid_samples = rows * cols - int(np.count_nonzero(erased))
        result.raw_valid = errors == 0 and erased_bits == 0
        # Phase 1 frames do not carry production inner FEC.  This field means
        # the raw frame would enter a decoder intact; no correction is claimed.
        result.inner_fec_valid = result.raw_valid
        result.payload_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    def _decode_qr(self, frame: np.ndarray) -> DecodeResult:
        result = DecodeResult(path="QR", failure_reason="QR_NOT_DECODED")
        started = time.perf_counter_ns()
        barcode = zxingcpp.read_barcode(
            frame,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_rotate=True,
            try_downscale=False,
            try_invert=False,
            text_mode=zxingcpp.TextMode.Plain,
        )
        payload = barcode.bytes if barcode is not None and barcode.valid else b""
        points = None
        if barcode is not None:
            position = barcode.position
            points = np.asarray([
                (position.top_left.x, position.top_left.y),
                (position.top_right.x, position.top_right.y),
                (position.bottom_right.x, position.bottom_right.y),
                (position.bottom_left.x, position.bottom_left.y),
            ], dtype=np.float32)
        if not payload:
            try:
                payload, cv_points, _ = self._qr.detectAndDecodeBytes(frame)
                if points is None:
                    points = cv_points
            except cv2.error:
                payload = b""
        result.qr_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if points is not None:
            result.quad = np.asarray(points, dtype=np.float32).reshape(-1, 2)
            result.geometry_source = "QR_DETECTED"
        if not payload:
            return result
        try:
            payload = bytes(payload)
            if barcode is None or not barcode.valid:
                # OpenCV exposes QR byte-mode data after converting the QR's
                # ISO-8859-1 mapping to UTF-8. ZXing returns exact bytes.
                try:
                    payload = payload.decode("utf-8").encode("latin-1")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass
            if len(payload) < 30 or payload[:4] != b"SQP1":
                raise ValueError("QR payload header")
            expected_size = int.from_bytes(payload[14:16], "little")
            if len(payload) != expected_size:
                raise ValueError("QR payload size")
            import zlib
            expected_crc = int.from_bytes(payload[-4:], "little")
            if zlib.crc32(payload[:-4]) & 0xFFFFFFFF != expected_crc:
                raise ValueError("QR payload CRC")
            envelope = LabRunEnvelope.decode(payload[16:26])
            if envelope.profile_id >= len(self._profiles):
                raise ValueError("QR profile id")
            profile = self._profiles[envelope.profile_id]
            if profile not in qr_controls():
                raise ValueError("QR profile mismatch")
            expected = build_qr_control_payload(
                qr_controls()[profile], envelope.frame_index,
                run_token=envelope.run_token, state=envelope.state,
                frame_count=envelope.frame_count, dwell_epochs=envelope.dwell_epochs,
            )
            if payload != expected:
                raise ValueError("QR deterministic payload mismatch")
        except (ValueError, KeyError) as exc:
            result.failure_reason = f"QR_INVALID_{str(exc).replace(' ', '_').upper()}"
            return result
        result.envelope = envelope
        result.profile = profile
        result.frame_index = envelope.frame_index
        result.geometry_source = "QR_DECODED"
        result.sync_status = envelope.state.name
        result.failure_reason = None
        result.finder_count = 4
        if envelope.state == RunState.RUNNING:
            result.observed_bits = len(payload) * 8
            result.valid_samples = result.observed_bits
            result.raw_valid = True
            result.inner_fec_valid = True
        return result


class ReceiverMetrics:
    def __init__(self):
        self.started_ns = time.perf_counter_ns()
        self.capture_times: deque[int] = deque(maxlen=90)
        self.analysis_times: deque[int] = deque(maxlen=90)
        self.pipeline_ms: deque[float] = deque(maxlen=256)
        self.analyzed = 0
        self.scored = 0
        self.observed_bits = 0
        self.erased_bits = 0
        self.bit_errors = 0
        self.raw_valid = 0
        self.unique: dict[tuple[int, str], set[int]] = {}
        self.innovative_seen: set[tuple[int, str, int]] = set()
        self.failures: Counter[str] = Counter()

    @staticmethod
    def _rate(times: deque[int]) -> float:
        return (len(times) - 1) * 1e9 / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0

    def record_capture(self, timestamp: int) -> None:
        self.capture_times.append(timestamp)

    def record(self, result: DecodeResult, pipeline_ms: float, timestamp: int) -> int:
        innovative_bytes = 0
        self.analyzed += 1
        self.analysis_times.append(timestamp)
        self.pipeline_ms.append(pipeline_ms)
        if result.failure_reason:
            self.failures[result.failure_reason] += 1
        if result.envelope is not None and result.envelope.state == RunState.RUNNING:
            self.scored += 1
            self.observed_bits += result.observed_bits
            self.erased_bits += result.erased_bits
            self.bit_errors += result.bit_errors
            self.raw_valid += int(result.raw_valid)
            key = (result.envelope.run_token, result.profile)
            self.unique.setdefault(key, set()).add(result.envelope.frame_index)
            innovation_key = (result.envelope.run_token, result.profile, result.envelope.frame_index)
            if result.raw_valid and innovation_key not in self.innovative_seen:
                self.innovative_seen.add(innovation_key)
                if result.profile in grid_profiles():
                    innovative_bytes = int(grid_profiles()[result.profile]["raw_bytes_per_frame"])
                else:
                    innovative_bytes = int(qr_controls()[result.profile]["frame_bytes"])
        return innovative_bytes

    def snapshot(self, result: DecodeResult | None, camera: str, width: int, height: int, requested: str, error: str | None = None) -> ReceiverSnapshot:
        envelope = result.envelope if result else None
        non_erased = self.observed_bits - self.erased_bits
        pipelines = sorted(self.pipeline_ms)
        p95 = pipelines[max(0, int(len(pipelines) * 0.95 + 0.999) - 1)] if pipelines else 0.0
        unique = len(self.unique.get((envelope.run_token, result.profile), set())) if envelope and result else 0
        return ReceiverSnapshot(
            state="ERROR" if error else "ANALYZING",
            camera=camera, capture_width=width, capture_height=height,
            requested_mode=requested,
            capture_fps=self._rate(self.capture_times), analysis_fps=self._rate(self.analysis_times),
            analyzed_frames=self.analyzed, scored_frames=self.scored,
            profile=result.profile if result else "UNKNOWN",
            run_token=envelope.run_token if envelope else None,
            run_state=envelope.state.name if envelope else "UNSYNCED",
            frame_index=result.frame_index if result else None,
            unique_frames=unique, frame_count=envelope.frame_count if envelope else 0,
            geometry_state=result.geometry_source if result else "NONE",
            sync_state=result.sync_status if result else "UNSYNCED",
            finder_count=result.finder_count if result else 0,
            candidate_count=result.candidate_count if result else 0,
            ber=self.bit_errors / non_erased if non_erased else 0.0,
            erasure_rate=self.erased_bits / self.observed_bits if self.observed_bits else 0.0,
            raw_valid_yield=self.raw_valid / self.scored if self.scored else 0.0,
            pipeline_mean_ms=sum(self.pipeline_ms) / len(self.pipeline_ms) if self.pipeline_ms else 0.0,
            pipeline_p95_ms=p95,
            failure_reason=(result.failure_reason or "NONE") if result else "WAITING_FOR_FRAME",
            failure_counts=dict(self.failures.most_common(8)), error=error,
        )


def observation_record(
    result: DecodeResult,
    snapshot: ReceiverSnapshot,
    completed_ns: int,
    pipeline_ms: float,
    innovative_bytes: int,
) -> dict[str, Any]:
    envelope = result.envelope
    return {
        "schema": "superqr-pc-phy-lab-observation-v1",
        "completed_ns": completed_ns,
        "capture_width": snapshot.capture_width,
        "capture_height": snapshot.capture_height,
        "analysis_path": result.path,
        "geometry_source": result.geometry_source,
        "sync_status": result.sync_status,
        "failure_reason": result.failure_reason,
        "profile": result.profile,
        "run_id": f"{envelope.run_token:04X}" if envelope else "UNSYNCED",
        "run_token": envelope.run_token if envelope else None,
        "run_state": envelope.state.name if envelope else "UNSYNCED",
        "frame_index": result.frame_index,
        "frame_count": envelope.frame_count if envelope else None,
        "scored": bool(envelope and envelope.state == RunState.RUNNING),
        "candidate_count": result.candidate_count,
        "finder_count": result.finder_count,
        "observed_bits": result.observed_bits,
        "erased_bits": result.erased_bits,
        "bit_errors": result.bit_errors,
        "valid_samples": result.valid_samples,
        "raw_valid": result.raw_valid,
        "inner_fec_valid": result.inner_fec_valid,
        "innovative_bytes": innovative_bytes,
        "contrast": result.contrast,
        "pipeline_ms": pipeline_ms,
        "geometry_ms": result.geometry_ms,
        "sync_ms": result.sync_ms,
        "payload_ms": result.payload_ms,
        "qr_ms": result.qr_ms,
    }


def annotate_frame(frame: np.ndarray, result: DecodeResult, snapshot: ReceiverSnapshot) -> np.ndarray:
    annotated = frame.copy()
    if result.quad is not None and len(result.quad) == 4:
        color = (50, 220, 80) if result.envelope else (0, 190, 255)
        cv2.polylines(annotated, [np.round(result.quad).astype(np.int32)], True, color, 3, cv2.LINE_AA)
    if result.finder_centers is not None:
        for point in result.finder_centers:
            cv2.circle(annotated, tuple(np.round(point).astype(int)), 6, (50, 220, 80), 2, cv2.LINE_AA)
    if result.envelope:
        headline = f"LOCKED {result.profile} {result.envelope.run_token:04X} {result.envelope.state.name} #{result.envelope.frame_index}"
        color = (50, 220, 80)
    elif result.candidate_count or result.quad is not None:
        headline = f"CARRIER CANDIDATE - {result.failure_reason}"
        color = (0, 190, 255)
    else:
        headline = "SEARCHING - SHOW THE FULL MARKER"
        color = (60, 80, 255)
    cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 58), (8, 12, 18), -1)
    cv2.putText(annotated, headline, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1, cv2.LINE_AA)
    cv2.putText(
        annotated,
        f"{snapshot.capture_width}x{snapshot.capture_height}  capture {snapshot.capture_fps:.1f} fps  analysis {snapshot.analysis_fps:.1f} fps",
        (12, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (225, 232, 242), 1, cv2.LINE_AA,
    )
    return annotated


class CameraReceiverWorker:
    """Own camera capture and decoding on one background thread."""

    def __init__(self, config: CameraConfig, output_path: str | Path | None = None):
        self.config = config
        self.output_path = Path(output_path) if output_path else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot: ReceiverSnapshot | None = None
        self._preview: np.ndarray | None = None
        self._analysis_frame: np.ndarray | None = None
        self._best_preview: np.ndarray | None = None
        self._best_preview_rank = -1
        self._error: str | None = None
        self._records: list[dict[str, Any]] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="superqr-pc-camera", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def snapshot(self) -> ReceiverSnapshot | None:
        with self._lock:
            return self._snapshot

    def preview(self) -> np.ndarray | None:
        with self._lock:
            return None if self._preview is None else self._preview.copy()

    def analysis_frame(self) -> np.ndarray | None:
        """Return the latest unmodified frame that was passed to the decoder."""
        with self._lock:
            return None if self._analysis_frame is None else self._analysis_frame.copy()

    def best_preview(self) -> np.ndarray | None:
        """Return the strongest optical-evidence frame seen during this run."""
        with self._lock:
            return None if self._best_preview is None else self._best_preview.copy()

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def export(self, path: str | Path) -> None:
        records = self.records()
        with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _run(self) -> None:
        cap: cv2.VideoCapture | None = None
        handle = None
        try:
            cap = open_camera(self.config)
            decoder = Phase1CameraDecoder()
            metrics = ReceiverMetrics()
            next_preview_ns = 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            camera = f"Camera {self.config.index} • {cap.getBackendName()}"
            requested = f"{self.config.width}×{self.config.height} @ {self.config.fps:g}"
            if self.output_path:
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.output_path.open("w", encoding="utf-8", newline="\n")
            while not self._stop.is_set():
                ok, frame = cap.read()
                captured_ns = time.perf_counter_ns()
                if not ok:
                    raise RuntimeError("camera stopped returning frames")
                metrics.record_capture(captured_ns)
                started = time.perf_counter_ns()
                result = decoder.analyze(frame)
                completed = time.perf_counter_ns()
                pipeline_ms = (completed - started) / 1_000_000.0
                innovative_bytes = metrics.record(result, pipeline_ms, completed)
                snapshot = metrics.snapshot(result, camera, width, height, requested)
                record = observation_record(
                    result, snapshot, completed, pipeline_ms, innovative_bytes,
                )
                evidence_rank = (
                    1000 if result.envelope is not None else
                    500 if result.geometry_source == "QR_DETECTED" else
                    result.finder_count * 50 + min(result.candidate_count, 20)
                )
                preview_due = completed >= next_preview_ns
                evidence_improved = evidence_rank > self._best_preview_rank
                preview = annotate_frame(frame, result, snapshot) if preview_due or evidence_improved else None
                if preview_due:
                    next_preview_ns = completed + 200_000_000
                with self._lock:
                    self._snapshot = snapshot
                    if preview_due and preview is not None:
                        self._preview = preview
                        self._analysis_frame = frame.copy()
                    if evidence_improved and preview is not None:
                        self._best_preview_rank = evidence_rank
                        self._best_preview = preview
                    self._records.append(record)
                if handle:
                    handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                    handle.flush()
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                if self._snapshot:
                    values = asdict(self._snapshot)
                    values["state"] = "ERROR"
                    values["error"] = self._error
                    self._snapshot = ReceiverSnapshot(**values)
                else:
                    self._snapshot = ReceiverMetrics().snapshot(
                        None, f"Camera {self.config.index}", 0, 0,
                        f"{self.config.width}×{self.config.height} @ {self.config.fps:g}", self._error,
                    )
        finally:
            if handle:
                handle.close()
            if cap is not None:
                cap.release()


def run_headless(
    config: CameraConfig,
    output: str | Path,
    duration_s: float,
    snapshot_path: str | Path | None = None,
) -> ReceiverSnapshot:
    worker = CameraReceiverWorker(config, output)
    worker.start()
    try:
        startup_deadline = time.monotonic() + 20.0
        while worker.is_alive() and worker.snapshot() is None and time.monotonic() < startup_deadline:
            time.sleep(0.05)
        if worker.snapshot() is None:
            raise RuntimeError("camera did not deliver its first analyzed frame within 20 seconds")
        deadline = time.monotonic() + duration_s
        while worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        worker.stop()
    if snapshot_path is not None:
        preview = worker.best_preview()
        if preview is None:
            preview = worker.preview()
        if preview is not None and not cv2.imwrite(str(snapshot_path), preview):
            raise RuntimeError(f"could not write diagnostic snapshot: {snapshot_path}")
    snapshot = worker.snapshot()
    if snapshot is None:
        raise RuntimeError("receiver stopped without a snapshot")
    return snapshot
