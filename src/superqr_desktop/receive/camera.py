"""Bounded background camera receiver for production V40 QR transfers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import statistics
import threading
import time

import cv2
import numpy as np
import zxingcpp

from superqr_desktop.receive.accumulator import ProductionQrAccumulator, ReceivedArtifact
from superqr_desktop.v7.transport import V7TransportError


@dataclass(frozen=True)
class ProductionReceiveSnapshot:
    state: str
    camera_fps: float
    decode_p50_ms: float
    decode_p95_ms: float
    camera_frames: int
    decoded_frames: int
    unique_frames: int
    duplicate_frames: int
    total_frames: int
    progress: float
    real_payload_kib_s: float
    profile_id: int | None
    failure: str


class ProductionCameraReceiver:
    def __init__(self, camera_index: int = 0, width: int = 1920, height: int = 1080, fps: float = 30.0):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.accumulator = ProductionQrAccumulator()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot = ProductionReceiveSnapshot(
            "IDLE", 0.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0.0, 0.0, None, ""
        )
        self._preview: np.ndarray | None = None
        self._artifact: ReceivedArtifact | None = None

    @property
    def artifact(self) -> ReceivedArtifact | None:
        with self._lock:
            return self._artifact

    def snapshot(self) -> ProductionReceiveSnapshot:
        with self._lock:
            return self._snapshot

    def preview(self) -> np.ndarray | None:
        with self._lock:
            return None if self._preview is None else self._preview.copy()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self.accumulator.artifact is not None:
            raise RuntimeError("save or discard the verified file before receiving another")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="superqr-production-camera", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def discard(self) -> None:
        self.stop()
        self.accumulator.reset(discard_artifact=True)
        with self._lock:
            self._artifact = None
            self._snapshot = ProductionReceiveSnapshot(
                "IDLE", 0.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0.0, 0.0, None, ""
            )

    def detach_saved(self) -> None:
        """Forget a staged artifact after the caller has copied it elsewhere."""
        self.stop()
        self.accumulator.reset(discard_artifact=True)
        with self._lock:
            self._artifact = None

    def _run(self) -> None:
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            self._set_error(f"Camera {self.camera_index} did not open")
            return
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        capture_times: deque[float] = deque(maxlen=90)
        decode_times: deque[float] = deque(maxlen=512)
        camera_frames = 0
        decoded_frames = 0
        started_payload_at: float | None = None
        last_preview = 0.0
        failure = "Show the full V40 QR inside the camera frame"
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                now = time.perf_counter()
                if not ok:
                    raise RuntimeError("camera stopped returning frames")
                camera_frames += 1
                capture_times.append(now)
                decode_started = time.perf_counter()
                barcode = zxingcpp.read_barcode(
                    frame,
                    formats=zxingcpp.QRCode,
                    try_rotate=True,
                    try_downscale=True,
                    try_invert=False,
                    text_mode=zxingcpp.Plain,
                )
                decode_ms = (time.perf_counter() - decode_started) * 1000.0
                decode_times.append(decode_ms)
                if barcode is not None and barcode.valid:
                    decoded_frames += 1
                    try:
                        was_new = self.accumulator.accept(barcode.bytes)
                        if was_new and started_payload_at is None:
                            started_payload_at = now
                        failure = ""
                    except V7TransportError as exc:
                        failure = str(exc)
                elif not failure:
                    failure = "QR not decoded in latest camera frame"

                progress = self.accumulator.progress
                camera_fps = 0.0
                if len(capture_times) >= 2:
                    camera_fps = (len(capture_times) - 1) / max(1e-9, capture_times[-1] - capture_times[0])
                ordered = sorted(decode_times)
                p50 = statistics.median(ordered) if ordered else 0.0
                p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
                elapsed = now - started_payload_at if started_payload_at is not None else 0.0
                real_kib_s = progress.received_payload_bytes / 1024.0 / elapsed if elapsed > 0 else 0.0
                artifact = self.accumulator.artifact
                state = "PREVIEW" if artifact is not None else ("RECEIVING" if progress.total_frames else "SEARCHING")
                if now - last_preview >= 0.2:
                    preview = frame
                    if preview.shape[1] > 960:
                        scale = 960.0 / preview.shape[1]
                        preview = cv2.resize(preview, (960, max(1, int(preview.shape[0] * scale))))
                    last_preview = now
                else:
                    preview = None
                snapshot = ProductionReceiveSnapshot(
                    state,
                    camera_fps,
                    p50,
                    p95,
                    camera_frames,
                    decoded_frames,
                    progress.unique_frames,
                    progress.duplicate_frames,
                    progress.total_frames,
                    progress.fraction,
                    real_kib_s,
                    progress.profile_id,
                    failure,
                )
                with self._lock:
                    self._snapshot = snapshot
                    if preview is not None:
                        self._preview = preview.copy()
                    if artifact is not None:
                        self._artifact = artifact
                if artifact is not None:
                    return
        except Exception as exc:
            self._set_error(f"{type(exc).__name__}: {exc}")
        finally:
            cap.release()

    def _set_error(self, message: str) -> None:
        current = self.snapshot()
        with self._lock:
            self._snapshot = ProductionReceiveSnapshot(
                "ERROR",
                current.camera_fps,
                current.decode_p50_ms,
                current.decode_p95_ms,
                current.camera_frames,
                current.decoded_frames,
                current.unique_frames,
                current.duplicate_frames,
                current.total_frames,
                current.progress,
                current.real_payload_kib_s,
                current.profile_id,
                message,
            )
