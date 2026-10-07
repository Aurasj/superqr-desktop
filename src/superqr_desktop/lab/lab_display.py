"""Deterministic display controller for the retained ColorGrid8 LAB."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
import sys
import time

import pygame

REFERENCE_REFRESH_HZ = 60.0
FALLBACK_REFRESH_HZ = REFERENCE_REFRESH_HZ


def detect_os_refresh_hz() -> float:
    """Detect the true display refresh rate from OS platform APIs."""
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            class DEVMODEW(ctypes.Structure):
                _fields_ = [
                    ("dmDeviceName", ctypes.c_wchar * 32),
                    ("dmSpecVersion", ctypes.wintypes.WORD),
                    ("dmDriverVersion", ctypes.wintypes.WORD),
                    ("dmSize", ctypes.wintypes.WORD),
                    ("dmDriverExtra", ctypes.wintypes.WORD),
                    ("dmFields", ctypes.wintypes.DWORD),
                    ("dmPositionX", ctypes.c_long),
                    ("dmPositionY", ctypes.c_long),
                    ("dmDisplayOrientation", ctypes.wintypes.DWORD),
                    ("dmDisplayFixedOutput", ctypes.wintypes.DWORD),
                    ("dmColor", ctypes.c_short),
                    ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short),
                    ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", ctypes.wintypes.WORD),
                    ("dmBitsPerPel", ctypes.wintypes.DWORD),
                    ("dmPelsWidth", ctypes.wintypes.DWORD),
                    ("dmPelsHeight", ctypes.wintypes.DWORD),
                    ("dmDisplayFlags", ctypes.wintypes.DWORD),
                    ("dmDisplayFrequency", ctypes.wintypes.DWORD),
                ]

            dm = DEVMODEW()
            dm.dmSize = ctypes.sizeof(DEVMODEW)
            if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
                freq = float(dm.dmDisplayFrequency)
                if freq > 0:
                    return freq
        except Exception:
            pass

    if pygame.display.get_init():
        try:
            freq = float(pygame.display.get_current_refresh_rate() or 0)
            if freq > 0:
                return freq
        except Exception:
            pass

    return FALLBACK_REFRESH_HZ


class TimingMode(Enum):
    VSYNC_MODE = auto()
    FALLBACK_TIMER_MODE = auto()


def calculate_percentiles(values: list[float]) -> tuple[float, float]:
    """Calculate p50 (median) and p95 from a list of duration measurements in ms."""
    if not values:
        return 0.0, 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0], sorted_vals[0]
    p50_idx = int(0.50 * (n - 1))
    p95_idx = int(0.95 * (n - 1))
    return sorted_vals[p50_idx], sorted_vals[p95_idx]


@dataclass
class DisplayDiagnostics:
    requested_fps: int = 30
    requested_vsync: bool = True
    driver_vsync_reported: bool = False
    actual_vsync_enabled: bool = False
    vsync_verified: bool = False
    reported_refresh_hz: float = 0.0
    detected_os_refresh_hz: float = 0.0
    timing_mode: TimingMode = TimingMode.FALLBACK_TIMER_MODE
    refresh_period_ms: float = 0.0
    dwell_refreshes: float = 2.0
    is_refresh_divisible: bool = True
    timing_warning: str = ""
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
    _logical_frame_intervals: list[float] = field(default_factory=list)
    _render_durations_ms: list[float] = field(default_factory=list)
    _max_recent: int = 20

    def record_present(self, block_us: int, interval_ms: float) -> None:
        self.present_block_us = block_us
        self.present_interval_ms = interval_ms
        self._recent_intervals.append(interval_ms)
        if interval_ms > 0:
            self._all_intervals.append(interval_ms)
        if len(self._recent_intervals) > self._max_recent:
            self._recent_intervals.pop(0)

    def record_logical_frame_interval(self, duration_ms: float) -> None:
        if duration_ms > 0:
            self._logical_frame_intervals.append(duration_ms)
            self.measured_logical_frame_ms = duration_ms

    def record_render_duration(self, duration_ms: float) -> None:
        if duration_ms >= 0:
            self._render_durations_ms.append(duration_ms)

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

    @property
    def logical_frame_intervals(self) -> list[float]:
        return list(self._logical_frame_intervals)

    @property
    def render_durations(self) -> list[float]:
        return list(self._render_durations_ms)

    def logical_frame_percentiles(self) -> tuple[float, float]:
        return calculate_percentiles(self._logical_frame_intervals)

    def render_percentiles(self) -> tuple[float, float]:
        return calculate_percentiles(self._render_durations_ms)

    def summary(self) -> str:
        divisible_str = "divisible" if self.is_refresh_divisible else f"NOT divisible ({self.dwell_refreshes:.2f} refreshes/frame)"
        return " | ".join((
            f"VSync: {'YES' if self.actual_vsync_enabled else 'NO'}",
            f"Refresh: {self.reported_refresh_hz:.1f} Hz ({divisible_str})",
            f"Target: {self.requested_fps} FPS",
            f"Dwell: {self.dwell_refreshes:.2f} refreshes ({self.expected_logical_dwell_ms:.1f} ms)",
            f"Mode: {self.timing_mode.name}",
        ))


@dataclass
class DwellState:
    """Derive logical frame dwell directly from actual physical refresh cadence.

    When refresh is cleanly divisible (e.g. 60 Hz -> 30 FPS), each logical frame
    dwells for exactly integer physical refreshes (e.g. 2 refreshes).
    When not divisible (e.g. 72 Hz -> 30 FPS), dwell fractional accumulation
    alternates refreshes without accumulating drift.
    """

    requested_fps: int
    present_refresh_hz: float = REFERENCE_REFRESH_HZ
    presents_for_current_frame: int = 0
    logical_frame_index: int = 0
    _accumulated_presents: float = 0.0

    @property
    def dwell_refreshes(self) -> float:
        eff_hz = self.present_refresh_hz if self.present_refresh_hz > 0 else REFERENCE_REFRESH_HZ
        return eff_hz / self.requested_fps

    @property
    def is_integer_dwell(self) -> bool:
        k = self.dwell_refreshes
        return abs(k - round(k)) < 0.001

    def record_present(self) -> bool:
        self.presents_for_current_frame += 1
        self._accumulated_presents += 1.0
        dwell = self.dwell_refreshes
        if self._accumulated_presents + 1e-9 >= dwell:
            self._accumulated_presents = max(0.0, self._accumulated_presents - dwell)
            self.presents_for_current_frame = 0
            return True
        return False

    def advance_logical_frame(self) -> None:
        self.logical_frame_index += 1

    def timer_tick(self) -> bool:
        return True


class LabDisplayController:
    """Own the ColorGrid8 SDL display and presentation cadence."""

    @classmethod
    def _apply_event_filter(cls) -> None:
        # Keep expose/resize/render-reset events. Pygame's integer constants
        # include flags and key codes too; they are not an event-type registry.
        pygame.event.set_allowed(None)
        pygame.event.set_blocked(pygame.MOUSEMOTION)

    def __init__(self, requested_fps: int = 30):
        self.requested_fps = requested_fps
        self.screen: pygame.Surface | None = None
        self.marker_size = 1000
        detected_hz = detect_os_refresh_hz()
        self.diag = DisplayDiagnostics(
            requested_fps=requested_fps,
            detected_os_refresh_hz=detected_hz,
            reported_refresh_hz=detected_hz,
        )
        self.dwell = DwellState(
            requested_fps=requested_fps,
            present_refresh_hz=detected_hz,
        )
        self._last_present_time: float | None = None
        self._dwell_start_time: float | None = None
        self._verification_intervals: list[float] = []
        self._next_timer_deadline: float | None = None
        self._update_dwell_diagnostics(detected_hz)

    def _update_dwell_diagnostics(self, refresh_hz: float) -> None:
        self.dwell.present_refresh_hz = refresh_hz
        k = refresh_hz / self.requested_fps if self.requested_fps > 0 else 2.0
        self.diag.dwell_refreshes = k
        self.diag.is_refresh_divisible = abs(k - round(k)) < 0.001
        self.diag.expected_logical_dwell_ms = 1000.0 / self.requested_fps
        if not self.diag.is_refresh_divisible:
            low_ms = 1000.0 / refresh_hz * int(k)
            high_ms = 1000.0 / refresh_hz * (int(k) + 1)
            self.diag.timing_warning = (
                f"WARNING: Detected display refresh ({refresh_hz:.1f} Hz) is not evenly divisible by "
                f"requested {self.requested_fps} FPS (ratio={k:.2f}). Frame dwell alternates (~{low_ms:.1f}/{high_ms:.1f} ms). "
                f"For controlled testing, switch monitor to 60 Hz in Windows Display Settings."
            )
        else:
            self.diag.timing_warning = ""

    def detect_displays(self) -> list[dict]:
        if not pygame.display.get_init():
            pygame.display.init()
            self._apply_event_filter()
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

    def setup_display(
        self,
        display_index: int = 0,
        fullscreen: bool = False,
        marker_size: int = 1000,
        window_size: tuple[int, int] | None = None,
    ) -> None:
        self.marker_size = marker_size
        displays = self.detect_displays()
        disp_info = next((item for item in displays if item["index"] == display_index), displays[0])
        screen_w, screen_h = disp_info["width"], disp_info["height"]
        if fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.RESIZABLE
            # Use large / near-maximized window by default to maximize optical carrier area
            requested_w, requested_h = window_size or (screen_w - 64, screen_h - 96)
            canvas_w = max(320, min(requested_w, screen_w - 32))
            canvas_h = max(320, min(requested_h, screen_h - 64))

        self.diag.requested_vsync = True
        self._apply_event_filter()
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
        pygame.display.set_caption("SuperQR LAB · ColorGrid8")
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

        detected_hz = detect_os_refresh_hz()
        self.diag.detected_os_refresh_hz = detected_hz
        self.diag.reported_refresh_hz = detected_hz

        if self.diag.driver_vsync_reported and detected_hz > 0:
            self.diag.timing_mode = TimingMode.VSYNC_MODE
            self.diag.refresh_period_ms = 1000.0 / detected_hz
            self.diag.timing_note = f"driver reported VSync; detected {detected_hz:.1f} Hz cadence"
        else:
            self.diag.timing_mode = TimingMode.FALLBACK_TIMER_MODE
            self.diag.refresh_period_ms = 1000.0 / detected_hz
            self.diag.actual_vsync_enabled = False
            self.diag.vsync_verified = False
            self.diag.timing_note = f"paced timer fallback ({detected_hz:.1f} Hz reference)"

        self._update_dwell_diagnostics(detected_hz)

    def present(self, frame_surface: pygame.Surface) -> None:
        if self.screen is None or not pygame.display.get_init():
            raise RuntimeError("lab display is not open")
        if self.diag.timing_mode == TimingMode.FALLBACK_TIMER_MODE:
            self._pace_fallback()
        t0 = time.perf_counter_ns()
        # A reused Surface can be mutated; a window backbuffer can also be
        # invalidated while dwelling on a static frame. Identity is not a
        # guarantee that the visible pixels are still present.
        canvas_w, canvas_h = self.screen.get_size()
        frame_w, frame_h = frame_surface.get_size()
        cx = (canvas_w - frame_w) // 2
        cy = (canvas_h - frame_h) // 2
        self.screen.fill((255, 255, 255))
        self.screen.blit(frame_surface, (cx, cy))
        pygame.display.flip()
        t1 = time.perf_counter_ns()

        now = time.perf_counter()
        interval_ms = 0.0 if self._last_present_time is None else (now - self._last_present_time) * 1000.0
        self._last_present_time = now
        self.diag.record_present((t1 - t0) // 1000, interval_ms)
        self._observe_present_interval(interval_ms)
        self.diag.present_count += 1
        self._verify_vsync(interval_ms)
        if self.diag.actual_vsync_enabled:
            self.diag.check_late()

    def _observe_present_interval(self, interval_ms: float) -> None:
        """Keep dwell tied to display refresh, not individual jittery presents.

        Present intervals already feed latency/loss diagnostics. Feeding them
        back into dwell turns scheduling jitter into extra frame transitions.
        """

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
            self.diag.timing_note = f"measured VSync cadence {median:.2f} ms ({1000.0/median:.1f} Hz)"
        else:
            self.diag.actual_vsync_enabled = False
            self.diag.vsync_verified = True
            self.diag.timing_mode = TimingMode.FALLBACK_TIMER_MODE
            self.diag.timing_note = f"driver VSync rejected: measured {median:.2f} ms; using timer pacing"
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
        now = time.perf_counter()
        if self._dwell_start_time is not None:
            duration_ms = (now - self._dwell_start_time) * 1000.0
            self.diag.record_logical_frame_interval(duration_ms)
        self._dwell_start_time = now

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
        self.diag._logical_frame_intervals.clear()
        self.diag._render_durations_ms.clear()
        self.diag.vsync_verified = False
        self._verification_intervals.clear()
        if self.diag.timing_mode == TimingMode.FALLBACK_TIMER_MODE and self.diag.driver_vsync_reported:
            self.diag.timing_mode = TimingMode.VSYNC_MODE
            self.diag.timing_note = "re-measuring VSync after PREPARING"
        self.dwell = DwellState(
            requested_fps=self.requested_fps,
            present_refresh_hz=self.diag.reported_refresh_hz or REFERENCE_REFRESH_HZ,
        )
        self._last_present_time = None
        self._dwell_start_time = time.perf_counter()

    def configure_dwell(self, requested_fps: int) -> None:
        self.requested_fps = requested_fps
        self.diag.requested_fps = requested_fps
        self._update_dwell_diagnostics(self.diag.reported_refresh_hz or REFERENCE_REFRESH_HZ)
        self.reset_measurement()

    def close(self) -> None:
        self.screen = None
        self._last_present_time = None
        self._dwell_start_time = None
        self._next_timer_deadline = None
        if pygame.display.get_init():
            pygame.display.quit()
