from __future__ import annotations

from collections import deque
import time
import uuid


MEASUREMENT_SCHEMA_VERSION = 1


class PresentationTelemetry:
    """Allocation-light V7.0 sender presentation measurements.

    The tracker measures completed optical presentations. It deliberately keeps
    configured/nominal rate separate from observed presentation cadence.
    """

    def __init__(self, window_size: int = 256):
        if window_size < 2:
            raise ValueError("window_size must be >= 2")
        self.window_size = window_size
        self._intervals_ms: deque[float] = deque(maxlen=window_size)
        self.reset()

    def reset(self, now_ns: int | None = None) -> str:
        now = time.monotonic_ns() if now_ns is None else now_ns
        self.run_id = uuid.uuid4().hex
        self.start_ns = now
        self.first_present_ns: int | None = None
        self.last_present_ns: int | None = None
        self.present_count = 0
        self.late_present_count = 0
        self.current_frame_id = -1
        self.last_render_prepare_ms = 0.0
        self.last_display_flip_ms = 0.0
        self._intervals_ms.clear()
        return self.run_id

    def record_present(
        self,
        frame_id: int,
        configured_interval_ms: float,
        render_prepare_ms: float,
        display_flip_ms: float,
        now_ns: int | None = None,
    ) -> None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        if self.first_present_ns is None:
            self.first_present_ns = now
        if self.last_present_ns is not None:
            interval_ms = (now - self.last_present_ns) / 1_000_000.0
            self._intervals_ms.append(interval_ms)
            if interval_ms > configured_interval_ms * 1.25:
                self.late_present_count += 1
        self.last_present_ns = now
        self.present_count += 1
        self.current_frame_id = frame_id
        self.last_render_prepare_ms = max(0.0, float(render_prepare_ms))
        self.last_display_flip_ms = max(0.0, float(display_flip_ms))

    @staticmethod
    def _p95(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        # Nearest-rank percentile, clamped to a valid zero-based index.
        rank = max(1, (95 * len(ordered) + 99) // 100)
        return ordered[min(len(ordered), rank) - 1]

    def snapshot(self, now_ns: int | None = None) -> dict[str, float | int | str]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        values = list(self._intervals_ms)
        elapsed_ms = max(0.0, (now - self.start_ns) / 1_000_000.0)

        measured_fps = 0.0
        if (
            self.present_count >= 2
            and self.first_present_ns is not None
            and self.last_present_ns is not None
            and self.last_present_ns > self.first_present_ns
        ):
            measured_fps = (self.present_count - 1) / (
                (self.last_present_ns - self.first_present_ns) / 1_000_000_000.0
            )

        return {
            "measurement_schema_version": MEASUREMENT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "present_count": self.present_count,
            "present_measured_fps": measured_fps,
            "present_interval_ms_last": values[-1] if values else 0.0,
            "present_interval_ms_mean": (sum(values) / len(values)) if values else 0.0,
            "present_interval_ms_min": min(values) if values else 0.0,
            "present_interval_ms_max": max(values) if values else 0.0,
            "present_interval_ms_p95": self._p95(values),
            "late_present_count": self.late_present_count,
            "render_prepare_ms_last": self.last_render_prepare_ms,
            "display_flip_ms_last": self.last_display_flip_ms,
            "session_elapsed_ms": elapsed_ms,
            "current_frame_id": self.current_frame_id,
        }
