"""V7 Capacity Lab display controller.

Owns the pygame display, handles VSync detection and verification,
and manages logical frame dwell timing.

Two modes:
    VSYNC_MODE — hardware-synchronized, counting actual completed presents.
    FALLBACK_TIMER_MODE — timer-based, no hardware sync claim.

Dwell semantics (VSYNC_MODE):
    Each logical frame is physically presented for exactly dwell_epochs
    completed display presents before the next logical frame is selected.
    The frame does NOT advance before the present that completes the
    current dwell window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame


# ---------------------------------------------------------------------------
# Timing mode
# ---------------------------------------------------------------------------

class TimingMode(Enum):
    VSYNC_MODE = auto()
    FALLBACK_TIMER_MODE = auto()


# ---------------------------------------------------------------------------
# Display diagnostics
# ---------------------------------------------------------------------------

@dataclass
class DisplayDiagnostics:
    """Live diagnostics reported by the display controller."""
    requested_vsync: bool = True
    actual_vsync_enabled: bool = False
    reported_refresh_hz: float = 0.0
    timing_mode: TimingMode = TimingMode.FALLBACK_TIMER_MODE
    refresh_period_ms: float = 0.0         # 1000 / refresh_hz
    dwell_epochs: int = 2
    expected_logical_dwell_ms: float = 0.0 # dwell_epochs * refresh_period_ms

    # Per-present measurements
    present_block_us: int = 0              # duration of last flip() call
    present_interval_ms: float = 0.0       # wall interval since previous flip return

    # Accumulated
    present_count: int = 0
    measured_logical_frame_ms: float = 0.0 # actual duration of last complete dwell window
    late_present_count: int = 0
    estimated_skipped_refreshes: int = 0

    # Rolling window for present intervals
    _recent_intervals: list[float] = field(default_factory=list)
    _max_recent: int = 20

    def record_present(self, block_us: int, interval_ms: float) -> None:
        self.present_block_us = block_us
        self.present_interval_ms = interval_ms
        self._recent_intervals.append(interval_ms)
        if len(self._recent_intervals) > self._max_recent:
            self._recent_intervals.pop(0)

    def check_late(self) -> None:
        """Check if the last present was late relative to refresh period."""
        if self.refresh_period_ms > 0 and self.present_interval_ms > self.refresh_period_ms * 1.5:
            self.late_present_count += 1
            if self.refresh_period_ms > 0:
                skipped = round(self.present_interval_ms / self.refresh_period_ms) - 1
                if skipped > 0:
                    self.estimated_skipped_refreshes += skipped

    @property
    def recent_intervals(self) -> list[float]:
        return list(self._recent_intervals)

    def summary(self) -> str:
        """One-line diagnostic summary."""
        parts = [
            f"VSync: {'YES' if self.actual_vsync_enabled else 'NO'}",
            f"Refresh: {self.reported_refresh_hz:.1f} Hz" if self.reported_refresh_hz > 0
            else "Refresh: unknown",
            f"Dwell: {self.dwell_epochs} epochs",
            f"Mode: {self.timing_mode.name}",
        ]
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Dwell controller
# ---------------------------------------------------------------------------

@dataclass
class DwellState:
    """Tracks logical frame advancement across display presents.

    In VSYNC_MODE, presents_for_current_frame is incremented AFTER each
    completed present. When it reaches dwell_epochs, the logical frame
    advances and the counter resets.

    In FALLBACK_TIMER_MODE, tick() is called from a timer instead.
    """
    dwell_epochs: int
    presents_for_current_frame: int = 0
    logical_frame_index: int = 0

    def record_present(self) -> bool:
        """Record a completed present. Returns True if frame should advance."""
        self.presents_for_current_frame += 1
        if self.presents_for_current_frame >= self.dwell_epochs:
            self.presents_for_current_frame = 0
            return True
        return False

    def advance_logical_frame(self) -> None:
        self.logical_frame_index += 1

    def timer_tick(self) -> bool:
        """Direct tick for fallback timer mode. Always returns True to signal advance."""
        return True


# ---------------------------------------------------------------------------
# Display controller
# ---------------------------------------------------------------------------

FALLBACK_REFRESH_HZ = 60.0


class LabDisplayController:
    """Pygame display setup with VSync detection and dwell timing."""

    def __init__(self, dwell_epochs: int = 2):
        self.dwell_epochs = dwell_epochs
        self.screen: pygame.Surface | None = None
        self.marker_size: int = 1000

        self.diag = DisplayDiagnostics(dwell_epochs=dwell_epochs)
        self.dwell = DwellState(dwell_epochs=dwell_epochs)

        self._last_present_time: float | None = None
        self._dwell_start_time: float | None = None

    def detect_displays(self) -> list[dict]:
        """Detect available displays. Must be called after pygame.display.init()."""
        if not pygame.display.get_init():
            pygame.display.init()

        displays = []
        try:
            sizes = pygame.display.get_desktop_sizes()
            for idx, (w, h) in enumerate(sizes):
                displays.append({
                    "index": idx,
                    "label": f"Display {idx + 1} ({w}x{h})",
                    "width": w,
                    "height": h,
                })
        except Exception:
            pass

        if not displays:
            try:
                info = pygame.display.Info()
                displays.append({
                    "index": 0,
                    "label": f"Display 1 ({info.current_w}x{info.current_h})",
                    "width": info.current_w,
                    "height": info.current_h,
                })
            except Exception:
                displays.append({
                    "index": 0,
                    "label": "Display 1 (Default)",
                    "width": 1920,
                    "height": 1080,
                })
        return displays

    def setup_display(
        self,
        display_index: int = 0,
        fullscreen: bool = False,
        marker_size: int = 1000,
    ) -> None:
        """Create the pygame display with VSync, falling back if unavailable."""
        self.marker_size = marker_size
        displays = self.detect_displays()
        disp_info = next((d for d in displays if d["index"] == display_index), displays[0])
        screen_w = disp_info["width"]
        screen_h = disp_info["height"]

        if fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.RESIZABLE
            canvas_w, canvas_h = marker_size, marker_size

        self.diag.requested_vsync = True

        # Attempt VSync display creation
        screen = None
        try:
            screen = pygame.display.set_mode(
                (canvas_w, canvas_h), flags | pygame.SCALED,
                display=display_index, vsync=1,
            )
        except pygame.error:
            pass
        except TypeError:
            # pygame-ce may not support vsync parameter
            pass

        if screen is None:
            try:
                screen = pygame.display.set_mode(
                    (canvas_w, canvas_h), flags,
                    display=display_index,
                )
            except pygame.error:
                screen = pygame.display.set_mode(
                    (canvas_w, canvas_h), flags,
                    display=0,
                )

        self.screen = screen
        pygame.display.set_caption("SuperQR V7 Capacity Lab")

        # Center windowed output
        if not fullscreen:
            try:
                pos_x = (screen_w - canvas_w) // 2
                pos_y = (screen_h - canvas_h) // 2
                pygame.display.set_window_position((pos_x, pos_y))
            except Exception:
                pass

        # Verify VSync status
        self._detect_timing_mode()

    def _detect_timing_mode(self) -> None:
        """Determine whether VSync is actually active."""
        try:
            self.diag.actual_vsync_enabled = pygame.display.is_vsync()
        except Exception:
            self.diag.actual_vsync_enabled = False

        try:
            self.diag.reported_refresh_hz = float(pygame.display.get_current_refresh_rate() or 0)
        except Exception:
            self.diag.reported_refresh_hz = 0.0

        if self.diag.actual_vsync_enabled and self.diag.reported_refresh_hz > 0:
            self.diag.timing_mode = TimingMode.VSYNC_MODE
            self.diag.refresh_period_ms = 1000.0 / self.diag.reported_refresh_hz
        else:
            self.diag.timing_mode = TimingMode.FALLBACK_TIMER_MODE
            self.diag.reported_refresh_hz = FALLBACK_REFRESH_HZ
            self.diag.refresh_period_ms = 1000.0 / FALLBACK_REFRESH_HZ
            self.diag.actual_vsync_enabled = False

        self.diag.expected_logical_dwell_ms = (
            self.diag.dwell_epochs * self.diag.refresh_period_ms
        )

    def present(self, frame_surface: pygame.Surface) -> None:
        """Present a frame and record timing.

        In VSYNC_MODE, flip() blocks until the next refresh boundary.
        In FALLBACK_TIMER_MODE, flip() may return immediately.

        The caller is responsible for calling this once per display refresh.
        """
        if self.screen is None or not pygame.display.get_init():
            raise RuntimeError("lab display is not open")
        t0 = time.perf_counter_ns()

        # Center the marker on the canvas
        canvas_w, canvas_h = self.screen.get_size()
        cx = (canvas_w - self.marker_size) // 2
        cy = (canvas_h - self.marker_size) // 2
        self.screen.fill((0, 0, 0))
        self.screen.blit(frame_surface, (cx, cy))
        pygame.display.flip()

        t1 = time.perf_counter_ns()
        block_us = (t1 - t0) // 1000

        # Compute interval since last present
        now = time.perf_counter()
        interval_ms = 0.0
        if self._last_present_time is not None:
            interval_ms = (now - self._last_present_time) * 1000.0

        self._last_present_time = now

        # Record
        self.diag.record_present(block_us, interval_ms)
        self.diag.present_count += 1

        if self.diag.timing_mode == TimingMode.VSYNC_MODE:
            self.diag.check_late()

    def record_dwell_complete(self) -> None:
        """Record the end of a logical frame dwell window."""
        if self._dwell_start_time is not None:
            now = time.perf_counter()
            self.diag.measured_logical_frame_ms = (now - self._dwell_start_time) * 1000.0
        self._dwell_start_time = time.perf_counter()

    # ------------------------------------------------------------------
    # Convenience wrappers used by lab_runner
    # ------------------------------------------------------------------

    def is_vsync_mode(self) -> bool:
        return self.diag.timing_mode == TimingMode.VSYNC_MODE

    def expected_dwell_ms(self) -> float:
        return self.diag.expected_logical_dwell_ms

    def reset_measurement(self) -> None:
        self.diag.present_block_us = 0
        self.diag.present_interval_ms = 0.0
        self.diag.present_count = 0
        self.diag.measured_logical_frame_ms = 0.0
        self.diag.late_present_count = 0
        self.diag.estimated_skipped_refreshes = 0
        self.diag._recent_intervals.clear()
        self.dwell = DwellState(dwell_epochs=self.dwell_epochs)
        self._last_present_time = None
        self._dwell_start_time = time.perf_counter()

    def close(self) -> None:
        """Idempotently release the display without touching a dead Surface."""
        self.screen = None
        self._last_present_time = None
        self._dwell_start_time = None
        if pygame.display.get_init():
            pygame.display.quit()
