"""Deterministic display controller for V7 physical PHY campaigns."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame


class TimingMode(Enum):
    VSYNC_MODE = auto()
    FALLBACK_TIMER_MODE = auto()


@dataclass
class DisplayDiagnostics:
    requested_vsync: bool = True
    driver_vsync_reported: bool = False
    actual_vsync_enabled: bool = False
    vsync_verified: bool = False
    reported_refresh_hz: float = 0.0
    timing_mode: TimingMode = TimingMode.FALLBACK_TIMER_MODE
    refresh_period_ms: float = 0.0
    dwell_epochs: int = 2
    expected_logical_dwell_ms: float = 0.0
    present_block_us: int = 0
    present_interval_ms: float = 0.0
    present_count: int = 0
    measured_logical_frame_ms: float = 0.0
    late_present_count: int = 0
    estimated_skipped_refreshes: int = 0
    timing_note: str = "not measured"
    _recent_intervals: list[float] = field(default_factory=list)
    _all_intervals: list[float] = field(default_factory=list)
    _max_recent: int = 20

    def record_present(self, block_us: int, interval_ms: float) -> None:
        self.present_block_us = block_us
        self.present_interval_ms = interval_ms
        self._recent_intervals.append(interval_ms)
        if interval_ms > 0:
            self._all_intervals.append(interval_ms)
        if len(self._recent_intervals) > self._max_recent:
            self._recent_intervals.pop(0)

    def check_late(self) -> None:
        if self.refresh_period_ms > 0 and self.present_interval_ms > self.refresh_period_ms * 1.5:
            self.late_present_count += 1
            skipped = round(self.present_interval_ms / self.refresh_period_ms) - 1
            if skipped > 0:
                self.estimated_skipped_refreshes += skipped

    @property
    def recent_intervals(self) -> list[float]:
        return list(self._recent_intervals)

    @property
    def all_intervals(self) -> list[float]:
        return list(self._all_intervals)

    def summary(self) -> str:
        return " | ".join((
            f"VSync: {'YES' if self.actual_vsync_enabled else 'NO'}",
            f"Refresh: {self.reported_refresh_hz:.1f} Hz" if self.reported_refresh_hz > 0 else "Refresh: unknown",
            f"Dwell: {self.dwell_epochs} epochs",
            f"Mode: {self.timing_mode.name}",
        ))


@dataclass
class DwellState:
    dwell_epochs: int
    presents_for_current_frame: int = 0
    logical_frame_index: int = 0

    def record_present(self) -> bool:
        self.presents_for_current_frame += 1
        if self.presents_for_current_frame >= self.dwell_epochs:
            self.presents_for_current_frame = 0
            return True
        return False

    def advance_logical_frame(self) -> None:
        self.logical_frame_index += 1

    def timer_tick(self) -> bool:
        return True


FALLBACK_REFRESH_HZ = 60.0


class LabDisplayController:
    """Own the SDL display and measured/timer presentation cadence.

    ``marker_size`` is the custom-grid carrier size selected by the operator.
    A physical campaign may also present a larger standard-QR control surface.
    ``present`` therefore centers the *actual surface dimensions*, not the grid
    marker size. This keeps 600 px custom carriers and 900 px QR control canvases
    centered on exactly the same monitor point.
    """

    def __init__(self, dwell_epochs: int = 2):
        self.dwell_epochs = dwell_epochs
        self.screen: pygame.Surface | None = None
        self.marker_size = 1000
        self.diag = DisplayDiagnostics(dwell_epochs=dwell_epochs)
        self.dwell = DwellState(dwell_epochs=dwell_epochs)
        self._last_present_time: float | None = None
        self._dwell_start_time: float | None = None
        self._last_frame_surface: pygame.Surface | None = None
        self._verification_intervals: list[float] = []
        self._next_timer_deadline: float | None = None

    def detect_displays(self) -> list[dict]:
        if not pygame.display.get_init():
            pygame.display.init()
        displays = []
        try:
            for idx, (width, height) in enumerate(pygame.display.get_desktop_sizes()):
                displays.append({
                    "index": idx,
                    "label": f"Display {idx + 1} ({width}x{height})",
                    "width": width,
                    "height": height,
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

    def setup_display(self, display_index: int = 0, fullscreen: bool = False, marker_size: int = 1000) -> None:
        self.marker_size = marker_size
        displays = self.detect_displays()
        disp_info = next((item for item in displays if item["index"] == display_index), displays[0])
        screen_w, screen_h = disp_info["width"], disp_info["height"]
        if fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.RESIZABLE
            # Physical QR controls are defined on a 900 px canvas. Keep a
            # windowed campaign large enough to show them without clipping too.
            canonical_qr_canvas = 900
            canvas_w = canvas_h = max(marker_size, canonical_qr_canvas)

        self.diag.requested_vsync = True
        screen = None
        try:
            screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=display_index, vsync=1)
        except (pygame.error, TypeError):
            pass
        if screen is None:
            try:
                screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=display_index)
            except pygame.error:
                screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=0)

        self.screen = screen
        pygame.display.set_caption("SuperQR V7 Capacity Lab")
        self.screen.fill((255, 255, 255))
        pygame.display.flip()
        if not fullscreen:
            try:
                pygame.display.set_window_position(((screen_w - canvas_w) // 2, (screen_h - canvas_h) // 2))
            except Exception:
                pass
        self._detect_timing_mode()

    def _detect_timing_mode(self) -> None:
        try:
            self.diag.driver_vsync_reported = pygame.display.is_vsync()
        except Exception:
            self.diag.driver_vsync_reported = False
        try:
            self.diag.reported_refresh_hz = float(pygame.display.get_current_refresh_rate() or 0)
        except Exception:
            self.diag.reported_refresh_hz = 0.0

        if self.diag.driver_vsync_reported and self.diag.reported_refresh_hz > 0:
            self.diag.timing_mode = TimingMode.VSYNC_MODE
            self.diag.refresh_period_ms = 1000.0 / self.diag.reported_refresh_hz
            self.diag.timing_note = "driver reported VSync; measuring present cadence"
        else:
            self.diag.timing_mode = TimingMode.FALLBACK_TIMER_MODE
            self.diag.reported_refresh_hz = FALLBACK_REFRESH_HZ
            self.diag.refresh_period_ms = 1000.0 / FALLBACK_REFRESH_HZ
            self.diag.actual_vsync_enabled = False
            self.diag.vsync_verified = False
            self.diag.timing_note = "paced timer fallback"
        self.diag.expected_logical_dwell_ms = self.diag.dwell_epochs * self.diag.refresh_period_ms

    def present(self, frame_surface: pygame.Surface) -> None:
        if self.screen is None or not pygame.display.get_init():
            raise RuntimeError("lab display is not open")
        if self.diag.timing_mode == TimingMode.FALLBACK_TIMER_MODE:
            self._pace_fallback()
        t0 = time.perf_counter_ns()
        if frame_surface is not self._last_frame_surface:
            canvas_w, canvas_h = self.screen.get_size()
            frame_w, frame_h = frame_surface.get_size()
            cx = (canvas_w - frame_w) // 2
            cy = (canvas_h - frame_h) // 2
            self.screen.fill((255, 255, 255))
            self.screen.blit(frame_surface, (cx, cy))
            self._last_frame_surface = frame_surface
        pygame.display.flip()
        t1 = time.perf_counter_ns()

        now = time.perf_counter()
        interval_ms = 0.0 if self._last_present_time is None else (now - self._last_present_time) * 1000.0
        self._last_present_time = now
        self.diag.record_present((t1 - t0) // 1000, interval_ms)
        self.diag.present_count += 1
        self._verify_vsync(interval_ms)
        if self.diag.actual_vsync_enabled:
            self.diag.check_late()

    def _verify_vsync(self, interval_ms: float) -> None:
        if self.diag.vsync_verified or not self.diag.driver_vsync_reported or interval_ms <= 0:
            return
        self._verification_intervals.append(interval_ms)
        if len(self._verification_intervals) < 12:
            return
        ordered = sorted(self._verification_intervals)
        median = ordered[len(ordered) // 2]
        period = self.diag.refresh_period_ms
        if period > 0 and period * 0.75 <= median <= period * 1.20:
            self.diag.actual_vsync_enabled = True
            self.diag.vsync_verified = True
            self.diag.timing_note = f"measured VSync cadence {median:.2f} ms"
        else:
            self.diag.actual_vsync_enabled = False
            self.diag.vsync_verified = True
            self.diag.timing_mode = TimingMode.FALLBACK_TIMER_MODE
            self.diag.timing_note = f"driver VSync rejected: measured {median:.2f} ms"
            self._next_timer_deadline = time.perf_counter() + self.diag.refresh_period_ms / 1000.0

    def _pace_fallback(self) -> None:
        period = self.diag.refresh_period_ms / 1000.0
        now = time.perf_counter()
        if self._next_timer_deadline is None:
            self._next_timer_deadline = now
        remaining = self._next_timer_deadline - now
        if remaining > 0.002:
            time.sleep(remaining - 0.001)
        while time.perf_counter() < self._next_timer_deadline:
            pass
        now = time.perf_counter()
        self._next_timer_deadline += period
        if self._next_timer_deadline < now - period:
            self._next_timer_deadline = now + period

    def record_dwell_complete(self) -> None:
        if self._dwell_start_time is not None:
            now = time.perf_counter()
            self.diag.measured_logical_frame_ms = (now - self._dwell_start_time) * 1000.0
        self._dwell_start_time = time.perf_counter()

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
        self.diag._all_intervals.clear()
        self.dwell = DwellState(dwell_epochs=self.dwell_epochs)
        self._last_present_time = None
        self._dwell_start_time = time.perf_counter()

    def configure_dwell(self, dwell_epochs: int) -> None:
        self.dwell_epochs = dwell_epochs
        self.diag.dwell_epochs = dwell_epochs
        self.diag.expected_logical_dwell_ms = dwell_epochs * self.diag.refresh_period_ms
        self.reset_measurement()

    def close(self) -> None:
        self.screen = None
        self._last_present_time = None
        self._dwell_start_time = None
        self._last_frame_surface = None
        self._next_timer_deadline = None
        if pygame.display.get_init():
            pygame.display.quit()
