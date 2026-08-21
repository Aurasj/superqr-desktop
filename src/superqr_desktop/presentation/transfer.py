"""Low-jitter production V40-L QR presentation.

QR encoding runs in a bounded background producer. The SDL/Tk thread only
creates/scales a tiny QR RGB surface and flips it, so QR generation time is not
charged against the optical dwell. Small/medium carousels that fit a strict
memory budget are cached after first preparation; large transfers stay fully
streaming and bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import queue
import threading
import time
from typing import Callable

import pygame
import segno

from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.v7.profiles import OpticalProfile


PREPARED_CAROUSEL_CACHE_BUDGET_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class PreparedQrFrame:
    frame_id: int
    loop_index: int
    total_modules: int
    rgb: bytes


class _QrFrameProducer:
    def __init__(
        self,
        frame_provider: Callable[[int], bytes],
        total_frames: int,
        session_id: int,
        profile: OpticalProfile,
        queue_size: int = 12,
        cache_budget_bytes: int = PREPARED_CAROUSEL_CACHE_BUDGET_BYTES,
    ) -> None:
        self.frame_provider = frame_provider
        self.total_frames = total_frames
        self.session_id = session_id
        self.profile = profile
        self.queue: queue.Queue[PreparedQrFrame] = queue.Queue(maxsize=queue_size)
        self.stop_event = threading.Event()
        self.error: str | None = None
        self.thread = threading.Thread(target=self._run, name="superqr-v40-producer", daemon=True)

        # Cache only when the complete working set fits. A partial cache would
        # thrash on later bijective carousel permutations and waste memory while
        # providing little deterministic benefit.
        module_count = 17 + 4 * profile.qr_version
        total_modules = module_count + 8  # four-module quiet zone on every side
        estimated_frame_bytes = total_modules * total_modules * 3
        self.cache_enabled = (
            cache_budget_bytes > 0
            and total_frames * estimated_frame_bytes <= cache_budget_bytes
        )
        self._prepared_cache: dict[int, PreparedQrFrame] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self._prepared_cache.clear()

    def _run(self) -> None:
        try:
            loop_index = 0
            while not self.stop_event.is_set():
                for position in range(self.total_frames):
                    if self.stop_event.is_set():
                        return
                    frame_id = self._frame_id(position, loop_index)
                    prepared = self._prepared_for(frame_id, loop_index)
                    while not self.stop_event.is_set():
                        try:
                            self.queue.put(prepared, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                loop_index += 1
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def _prepared_for(self, frame_id: int, loop_index: int) -> PreparedQrFrame:
        if self.cache_enabled:
            cached = self._prepared_cache.get(frame_id)
            if cached is not None:
                return PreparedQrFrame(
                    frame_id=frame_id,
                    loop_index=loop_index,
                    total_modules=cached.total_modules,
                    rgb=cached.rgb,
                )

        frame_bytes = self.frame_provider(frame_id)
        prepared = self._prepare(frame_id, loop_index, frame_bytes)
        if self.cache_enabled and not self.stop_event.is_set():
            # The RGB payload is immutable. Store one canonical copy and only
            # replace the cheap loop metadata on later passes.
            self._prepared_cache[frame_id] = PreparedQrFrame(
                frame_id=frame_id,
                loop_index=0,
                total_modules=prepared.total_modules,
                rgb=prepared.rgb,
            )
        return prepared

    def _frame_id(self, position: int, loop_index: int) -> int:
        """First pass is sequential; later passes permute frame/phase association.

        Out-of-order transport IDs make this safe. The permutation is bijective,
        so every source frame is still shown exactly once per carousel while a
        fixed camera/display phase cannot keep targeting the same frame forever.
        """
        total = self.total_frames
        if total <= 1 or loop_index == 0:
            return position
        candidate = 1 + ((self.session_id * 17 + loop_index * 29) % (total - 1))
        while math.gcd(candidate, total) != 1:
            candidate += 1
            if candidate >= total:
                candidate = 1
        offset = (self.session_id * 131 + loop_index * 977) % total
        return (offset + position * candidate) % total

    def _prepare(self, frame_id: int, loop_index: int, frame_bytes: bytes) -> PreparedQrFrame:
        qr = segno.make_qr(
            frame_bytes,
            version=self.profile.qr_version,
            error=self.profile.qr_ecc,
            mask=self.profile.qr_mask,
            mode="byte",
            boost_error=False,
        )
        matrix = qr.matrix
        modules = len(matrix)
        quiet = 4
        total = modules + quiet * 2
        rgb = bytearray([255]) * (total * total * 3)
        for row, values in enumerate(matrix):
            base = (row + quiet) * total + quiet
            for col, value in enumerate(values):
                if value:
                    pixel = (base + col) * 3
                    rgb[pixel] = 0
                    rgb[pixel + 1] = 0
                    rgb[pixel + 2] = 0
        return PreparedQrFrame(frame_id, loop_index, total, bytes(rgb))


class TransferPresenter:
    """Own the bounded QR producer and render prepared V40-L frames."""

    def __init__(self, display: DisplayController):
        self._display = display
        self._producer: _QrFrameProducer | None = None

    def start_stream(
        self,
        frame_provider: Callable[[int], bytes],
        total_frames: int,
        session_id: int,
        profile: OpticalProfile,
    ) -> None:
        self.stop_stream()
        if not profile.is_qr:
            raise ValueError("production transfer requires a QR optical profile")
        if total_frames < 1:
            raise ValueError("transfer requires at least one frame")
        self._producer = _QrFrameProducer(frame_provider, total_frames, session_id, profile)
        self._producer.start()

    def stop_stream(self) -> None:
        if self._producer is not None:
            self._producer.stop()
            self._producer = None

    @property
    def producer_error(self) -> str | None:
        return self._producer.error if self._producer is not None else None

    @property
    def ready_count(self) -> int:
        return self._producer.queue.qsize() if self._producer is not None else 0

    def pop_ready(self) -> PreparedQrFrame | None:
        if self._producer is None:
            return None
        try:
            return self._producer.queue.get_nowait()
        except queue.Empty:
            return None

    def render_prepared(self, frame: PreparedQrFrame, marker_size: int) -> dict[str, float]:
        screen = self._display.screen
        if screen is None:
            raise RuntimeError("optical display is not open")
        started_ns = time.perf_counter_ns()
        total = frame.total_modules
        scale = marker_size // total
        if scale < 1:
            raise ValueError(f"marker size {marker_size} is too small for V40 QR")
        rendered = total * scale
        native = pygame.image.frombytes(frame.rgb, (total, total), "RGB")
        scaled = pygame.transform.scale(native, (rendered, rendered))

        canvas_w, canvas_h = screen.get_size()
        marker_x = (canvas_w - marker_size) // 2
        marker_y = (canvas_h - marker_size) // 2
        qr_x = marker_x + (marker_size - rendered) // 2
        qr_y = marker_y + (marker_size - rendered) // 2
        screen.fill((8, 10, 14))
        pygame.draw.rect(screen, (255, 255, 255), (marker_x, marker_y, marker_size, marker_size))
        screen.blit(scaled, (qr_x, qr_y))
        flip_started_ns = time.perf_counter_ns()
        pygame.display.flip()
        completed_ns = time.perf_counter_ns()
        return {
            "render_ms": (flip_started_ns - started_ns) / 1_000_000.0,
            "flip_ms": (completed_ns - flip_started_ns) / 1_000_000.0,
        }

    def render_qr_bytes(self, frame_bytes: bytes, marker_size: int, profile: OpticalProfile) -> dict[str, float]:
        """Synchronous compatibility path used by tests/manual callers."""
        helper = _QrFrameProducer(lambda _idx: frame_bytes, 1, 1, profile, queue_size=1)
        prepared = helper._prepare(0, 0, frame_bytes)
        return self.render_prepared(prepared, marker_size)

    def invalidate_renderer(self) -> None:
        self.stop_stream()
