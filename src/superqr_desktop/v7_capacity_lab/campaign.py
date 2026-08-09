"""Reusable presentation engine for UI and CLI physical PHY campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import secrets
import threading
import time

import pygame

from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController, TimingMode
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_matrix,
    build_run_envelope,
    grid_profiles,
    qr_controls,
    validate_grid_vectors,
    validate_qr_vectors,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import RunState


class CampaignState(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class RunSpec:
    profile: str
    dwell_epochs: int
    frame_count: int


@dataclass(frozen=True)
class PresentationSnapshot:
    state: CampaignState
    profile: str
    dwell_epochs: int
    run_token: int
    run_number: int
    run_total: int
    frame_index: int
    frame_count: int
    ready_remaining_s: float
    present_count: int
    logical_fps: float
    present_fps: float
    late_presents: int
    render_prepare_ms: float
    timing_mode: str
    vsync_verified: bool
    present_interval_ms: float
    timing_note: str
    error: str | None


@dataclass(frozen=True)
class RunPresentationResult:
    profile: str
    dwell_epochs: int
    run_token: int
    frame_count: int
    elapsed_s: float
    present_count: int
    present_fps: float
    interval_p95_ms: float
    interval_max_ms: float
    late_presents: int
    estimated_skipped_refreshes: int
    timing_mode: str
    vsync_verified: bool
    reported_refresh_hz: float
    timing_note: str


def build_campaign(preset: str, profile: str, dwell: int, frames: int) -> list[RunSpec]:
    all_profiles = list(grid_profiles()) + list(qr_controls())
    if preset == "Selected profile":
        names = [profile]
    elif preset == "All canonical profiles":
        names = all_profiles
    elif preset == "Monochrome density sweep":
        names = [name for name in grid_profiles() if name.startswith("mono_")]
    elif preset == "Full grid dwell sweep":
        return [RunSpec(name, epoch, frames) for epoch in (3, 2) for name in grid_profiles()]
    else:
        raise ValueError(f"unknown campaign preset: {preset}")
    return [RunSpec(name, dwell, frames) for name in names]


class Phase1CampaignPresenter:
    """Single-threaded, bounded-memory physical presentation state machine."""

    def __init__(
        self,
        runs: list[RunSpec],
        *,
        display_index: int,
        fullscreen: bool,
        marker_size: int,
        ready_seconds: float = 4.0,
        done_seconds: float = 2.0,
        first_run_token: int | None = None,
    ):
        if not runs:
            raise ValueError("campaign must contain at least one run")
        self.runs = runs
        self.display_index = display_index
        self.fullscreen = fullscreen
        self.marker_size = marker_size
        self.ready_seconds = ready_seconds
        self.done_seconds = done_seconds
        self.next_token = first_run_token if first_run_token is not None else secrets.randbelow(0xFFFF) + 1
        self.manifest = load_phy_selection_manifest()
        self.display: LabDisplayController | None = None
        self.renderer: LabRenderer | None = None
        self.state = CampaignState.IDLE
        self.run_number = 0
        self.run_token = 0
        self.frame_index = 0
        self.state_started = time.perf_counter()
        self.run_started = 0.0
        self.last_advance = 0.0
        self.grid_sequence: GridFrameSequence | None = None
        self.grid_matrix = None
        self.qr_native: list[pygame.Surface] = []
        self.qr_ready: pygame.Surface | None = None
        self.qr_done: pygame.Surface | None = None
        self.error: str | None = None
        self.run_results: list[RunPresentationResult] = []
        self._current_result_recorded = False
        self._presentation_finished = False
        self._stop_requested = False

    @property
    def spec(self) -> RunSpec:
        return self.runs[self.run_number]

    def start(self) -> None:
        validate_grid_vectors()
        validate_qr_vectors()
        pygame.init()
        self._prepare_run(0)

    def _prepare_run(self, index: int) -> None:
        self.state = CampaignState.PREPARING
        self.run_number = index
        self.run_token = self.next_token
        self.next_token = (self.next_token % 0xFFFF) + 1
        self.frame_index = 0
        self.grid_sequence = None
        self.grid_matrix = None
        self.qr_native.clear()
        self.qr_ready = None
        self.qr_done = None
        self._current_result_recorded = False
        spec = self.spec
        if self.display is None:
            self.display = LabDisplayController(dwell_epochs=spec.dwell_epochs)
            self.display.setup_display(self.display_index, self.fullscreen, self.marker_size)
        else:
            self.display.configure_dwell(spec.dwell_epochs)
        self.renderer = LabRenderer(self.marker_size)
        if spec.profile in grid_profiles():
            self.grid_sequence = GridFrameSequence(spec.profile)
            index_zero, self.grid_matrix = self.grid_sequence.next_frame()
            if index_zero != 0:
                raise RuntimeError("grid sequence did not start at zero")
        else:
            control = qr_controls()[spec.profile]
            quiet = int(control["quiet_zone_modules"])
            for frame_index in range(spec.frame_count):
                if self._stop_requested:
                    self.state = CampaignState.STOPPED
                    return
                matrix = build_qr_matrix(
                    control, frame_index, run_token=self.run_token,
                    frame_count=spec.frame_count, dwell_epochs=spec.dwell_epochs,
                )
                self.qr_native.append(self.renderer.build_qr_native_surface(matrix, quiet))
            self.qr_ready = self.renderer.build_qr_native_surface(
                build_qr_matrix(
                    control, 0, run_token=self.run_token, state=RunState.READY,
                    frame_count=spec.frame_count, dwell_epochs=spec.dwell_epochs,
                ), quiet,
            )
            self.qr_done = self.renderer.build_qr_native_surface(
                build_qr_matrix(
                    control, spec.frame_count - 1, run_token=self.run_token, state=RunState.DONE,
                    frame_count=spec.frame_count, dwell_epochs=spec.dwell_epochs,
                ), quiet,
            )
        self.state = CampaignState.READY
        self.state_started = time.perf_counter()
        self._render(RunState.READY)

    def _render(self, state: RunState) -> None:
        assert self.renderer is not None
        spec = self.spec
        if self.grid_sequence is not None:
            envelope = build_run_envelope(
                spec.profile, self.run_token, self.frame_index,
                spec.frame_count, spec.dwell_epochs, state,
            )
            sync = self.manifest["run_sync"]
            self.renderer.prepare_logical_frame(
                self.grid_matrix,
                payload_bbox=self.manifest["payload_bbox"],
                sync_bits=envelope.bits(),
                sync_bboxes=(sync["top_bbox"], sync["bottom_bbox"]),
                sync_rows=int(sync["rows"]),
                sync_cols=int(sync["cols"]),
            )
        else:
            if state == RunState.READY:
                native = self.qr_ready
            elif state == RunState.DONE:
                native = self.qr_done
            else:
                native = self.qr_native[self.frame_index]
            assert native is not None
            self.renderer.prepare_qr_native_surface(native)

    def tick(self) -> bool:
        """Present once. Returns False after a user close/escape request."""
        try:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
                ):
                    self.stop()
                    return False
            if self.state not in (CampaignState.READY, CampaignState.RUNNING, CampaignState.DONE):
                return self.state not in (CampaignState.STOPPED, CampaignState.ERROR)
            assert self.display is not None and self.renderer is not None
            surface = self.renderer.cached_frame_display
            if surface is not None:
                self.display.present(surface)
            now = time.perf_counter()
            if self.state == CampaignState.READY:
                if now - self.state_started >= self.ready_seconds:
                    self.state = CampaignState.RUNNING
                    self.state_started = now
                    self.run_started = now
                    self.last_advance = now
                    self.display.reset_measurement()
                    self._render(RunState.RUNNING)
            elif self.state == CampaignState.RUNNING and self._should_advance(now):
                self.display.record_dwell_complete()
                self.frame_index += 1
                if self.frame_index >= self.spec.frame_count:
                    self.frame_index = self.spec.frame_count - 1
                    self.state = CampaignState.DONE
                    self.state_started = now
                    self._render(RunState.DONE)
                    self._record_run_result(now)
                else:
                    if self.grid_sequence is not None:
                        sequence_index, self.grid_matrix = self.grid_sequence.next_frame()
                        if sequence_index != self.frame_index:
                            raise RuntimeError("grid sequence index drift")
                    self._render(RunState.RUNNING)
            elif self.state == CampaignState.DONE and now - self.state_started >= self.done_seconds:
                if self.run_number + 1 < len(self.runs):
                    self._prepare_run(self.run_number + 1)
                else:
                    self._presentation_finished = True
                    if self.display is not None:
                        self.display.close()
                    return False
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.state = CampaignState.ERROR
            return False

    def _should_advance(self, now: float) -> bool:
        assert self.display is not None
        if self.spec.profile in grid_profiles() and self.display.diag.timing_mode == TimingMode.VSYNC_MODE:
            return self.display.dwell.record_present()
        fps = (
            float(qr_controls()[self.spec.profile]["target_fps"])
            if self.spec.profile in qr_controls()
            else self.display.diag.reported_refresh_hz / self.spec.dwell_epochs
        )
        if now - self.last_advance < 1.0 / fps:
            return False
        self.last_advance += 1.0 / fps
        return True

    def snapshot(self) -> PresentationSnapshot:
        now = time.perf_counter()
        spec = self.spec
        diag = self.display.diag if self.display is not None else None
        elapsed = max(0.0, now - self.run_started) if self.run_started else 0.0
        completed = self.frame_index if self.state == CampaignState.RUNNING else (
            spec.frame_count if self.state == CampaignState.DONE else 0
        )
        intervals = diag.recent_intervals if diag else []
        mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
        return PresentationSnapshot(
            state=self.state, profile=spec.profile, dwell_epochs=spec.dwell_epochs,
            run_token=self.run_token, run_number=self.run_number + 1, run_total=len(self.runs),
            frame_index=self.frame_index, frame_count=spec.frame_count,
            ready_remaining_s=max(0.0, self.ready_seconds - (now - self.state_started))
                if self.state == CampaignState.READY else 0.0,
            present_count=diag.present_count if diag else 0,
            logical_fps=completed / elapsed if elapsed else 0.0,
            present_fps=1000.0 / mean_interval if mean_interval > 0 else 0.0,
            late_presents=diag.late_present_count if diag else 0,
            render_prepare_ms=(self.renderer.timings.total_prepare_us / 1000.0) if self.renderer else 0.0,
            timing_mode=(
                "VSYNC_VERIFYING"
                if diag and diag.timing_mode == TimingMode.VSYNC_MODE and not diag.vsync_verified
                else diag.timing_mode.name if diag else "UNKNOWN"
            ),
            vsync_verified=diag.vsync_verified if diag else False,
            present_interval_ms=diag.present_interval_ms if diag else 0.0,
            timing_note=diag.timing_note if diag else "display not open",
            error=self.error,
        )

    def _record_run_result(self, now: float) -> None:
        if self._current_result_recorded or self.display is None:
            return
        diag = self.display.diag
        intervals = sorted(diag.all_intervals)
        p95_index = max(0, int(len(intervals) * 0.95 + 0.999) - 1)
        p95 = intervals[p95_index] if intervals else 0.0
        elapsed = max(0.0, now - self.run_started)
        self.run_results.append(RunPresentationResult(
            profile=self.spec.profile,
            dwell_epochs=self.spec.dwell_epochs,
            run_token=self.run_token,
            frame_count=self.spec.frame_count,
            elapsed_s=elapsed,
            present_count=diag.present_count,
            present_fps=diag.present_count / elapsed if elapsed else 0.0,
            interval_p95_ms=p95,
            interval_max_ms=max(intervals) if intervals else 0.0,
            late_presents=diag.late_present_count,
            estimated_skipped_refreshes=diag.estimated_skipped_refreshes,
            timing_mode=diag.timing_mode.name,
            vsync_verified=diag.vsync_verified,
            reported_refresh_hz=diag.reported_refresh_hz,
            timing_note=diag.timing_note,
        ))
        self._current_result_recorded = True

    def export_payload(self) -> dict:
        return {
            "schema": "superqr-phy-lab-sender-v2",
            "production_wire_frozen": False,
            "state": self.state.value,
            "runs_completed": len(self.run_results),
            "runs_total": len(self.runs),
            "runs": [asdict(result) for result in self.run_results],
            "current": asdict(self.snapshot()),
        }

    def stop(self) -> None:
        self._stop_requested = True
        if self.state != CampaignState.DONE:
            self.state = CampaignState.STOPPED
        if self.display is not None:
            self.display.close()

    def request_stop(self) -> None:
        """Signal lengthy frame preparation without touching SDL cross-thread."""
        self._stop_requested = True


class Phase1CampaignWorker:
    """Owns all Pygame calls on a dedicated presentation thread."""

    def __init__(self, presenter: Phase1CampaignPresenter):
        self.presenter = presenter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: PresentationSnapshot | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("campaign worker already started")
        self._thread = threading.Thread(target=self._run, name="superqr-phy-present", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.presenter.start()
            while not self._stop.is_set():
                keep_running = self.presenter.tick()
                with self._lock:
                    self._snapshot = self.presenter.snapshot()
                if not keep_running:
                    break
        except Exception as exc:
            self.presenter.error = f"{type(exc).__name__}: {exc}"
            self.presenter.state = CampaignState.ERROR
        finally:
            with self._lock:
                self._snapshot = self.presenter.snapshot()
            if self._stop.is_set():
                self.presenter.stop()

    def snapshot(self) -> PresentationSnapshot | None:
        with self._lock:
            return self._snapshot

    def export_payload(self) -> dict:
        with self._lock:
            return self.presenter.export_payload()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self.presenter.request_stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        if thread is not None and thread.is_alive():
            raise RuntimeError("presentation thread did not stop")
