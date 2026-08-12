"""Reusable presentation engine for UI and CLI physical PHY campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import multiprocessing
import os
import queue
import secrets
import threading
import time
from typing import Any, Callable

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
    dwell_epochs: float
    frame_count: int
    target_fps: float | None = None


@dataclass(frozen=True)
class PresentationSnapshot:
    state: CampaignState
    profile: str
    dwell_epochs: float
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
    dwell_epochs: float
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


@dataclass(frozen=True)
class CampaignLaunchConfig:
    """Serializable boundary between the Tk controller and SDL presenter."""

    runs: tuple[RunSpec, ...]
    display_index: int
    fullscreen: bool
    marker_size: int
    ready_seconds: float
    done_seconds: float
    first_run_token: int


def build_campaign(preset: str, profile: str, dwell: float, frames: int) -> list[RunSpec]:
    all_profiles = list(grid_profiles()) + list(qr_controls())
    if preset == "V40 sweep":
        return [RunSpec("qr_v40_l_ceiling", round(60.0 / fps, 3), frames, target_fps=fps)
                for fps in (30.0, 24.0, 20.0, 15.0, 12.0, 10.0)]
    if preset == "Selected profile":
        names = [profile]
    elif preset == "All canonical profiles":
        names = all_profiles
    elif preset == "Comprehensive grid+QR sweep":
        names = all_profiles
    elif preset == "Monochrome density sweep":
        names = [name for name in grid_profiles() if name.startswith("mono_")]
    elif preset == "Full grid dwell sweep":
        return [RunSpec(name, epoch, frames) for epoch in (3, 2) for name in grid_profiles()]
    elif preset == "V27+V40 speed test":
        # Canonical: dwell = 60.0 / target_fps. Works on any monitor refresh rate
        # because DwellState normalizes to 60 Hz canonical epochs.
        fps_targets = [30.0, 24.0, 20.0, 15.0, 12.0, 10.0]
        return [
            RunSpec(profile, round(60.0 / fps, 3), frames, target_fps=fps)
            for profile in ("qr_v27_l_safe", "qr_v40_l_ceiling")
            for fps in fps_targets
        ]
    elif preset == "Grid density sweep":
        return [
            RunSpec("mono_64x50_matched", 2, frames),
            RunSpec("mono_96x75_medium", 2, frames),
            RunSpec("mono_128x100_qrlike", 2, frames),
        ]
    elif preset == "V40 cadence sweep":
        return [
            RunSpec("qr_v40_l_ceiling", dwell, frames, target_fps=fps)
            for fps in (24.0, 30.0, 40.0, 60.0)
        ]
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
        stop_requested: Callable[[], bool] | None = None,
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
        self._qr_control: dict | None = None
        self._qr_quiet: int = 4
        self._build_index: int = 0
        self.qr_ready: pygame.Surface | None = None
        self.qr_done: pygame.Surface | None = None
        self.error: str | None = None
        self.run_results: list[RunPresentationResult] = []
        self._current_result_recorded = False
        self._presentation_finished = False
        self._stop_requested = False
        self._external_stop_requested = stop_requested

    @property
    def spec(self) -> RunSpec:
        return self.runs[self.run_number]

    def start(self) -> None:
        validate_grid_vectors()
        validate_qr_vectors()
        if self._should_stop():
            self.state = CampaignState.STOPPED
            return
        pygame.init()
        LabDisplayController._apply_event_filter()
        self._prepare_run(0)

    def _prepare_run(self, index: int) -> None:
        self.state = CampaignState.PREPARING
        if self._should_stop():
            self.state = CampaignState.STOPPED
            return
        self.run_number = index
        self.run_token = self.next_token
        self.next_token = (self.next_token % 0xFFFF) + 1
        self.frame_index = 0
        self.grid_sequence = None
        self.grid_matrix = None
        self.qr_native.clear()
        self._qr_control = None
        self._qr_quiet = 4
        self._build_index = 0
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
            self.state = CampaignState.READY
            self.state_started = time.perf_counter()
            self._render(RunState.READY)
            return
        else:
            control = qr_controls()[spec.profile]
            quiet = int(control["quiet_zone_modules"])
            self._qr_control = control
            self._qr_quiet = quiet
            self._build_index = 0
            # Build READY + DONE immediately; data frames built incrementally in tick().
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
        self.state = CampaignState.PREPARING
        self.state_started = time.perf_counter()
        self._render(RunState.READY)  # show READY QR immediately while data frames build

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
            if self._should_stop():
                self.stop()
                return False
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
                ):
                    self.stop()
                    return False
            if self.state not in (CampaignState.PREPARING, CampaignState.READY, CampaignState.RUNNING, CampaignState.DONE):
                return self.state not in (CampaignState.STOPPED, CampaignState.ERROR)
            assert self.display is not None and self.renderer is not None
            surface = self.renderer.cached_frame_display
            if surface is not None:
                self.display.present(surface)
            now = time.perf_counter()
            if self.state == CampaignState.PREPARING:
                # Build QR frames incrementally so snapshots reach the UI.
                ctrl = self._qr_control
                if ctrl is not None and self._build_index < self.spec.frame_count:
                    for _ in range(8):
                        idx = self._build_index
                        if idx >= self.spec.frame_count or self._should_stop():
                            break
                        matrix = build_qr_matrix(
                            ctrl, idx, run_token=self.run_token,
                            frame_count=self.spec.frame_count, dwell_epochs=self.spec.dwell_epochs,
                        )
                        self.qr_native.append(self.renderer.build_qr_native_surface(matrix, self._qr_quiet))
                        self._build_index = idx + 1
                    if self._build_index >= self.spec.frame_count:
                        self._qr_control = None
                        self.state = CampaignState.READY
                        self.state_started = now
                        self._render(RunState.READY)
            elif self.state == CampaignState.READY:
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
        if self.display.diag.timing_mode == TimingMode.VSYNC_MODE:
            return self.display.dwell.record_present()
        fps = (
            self.spec.target_fps
            if self.spec.target_fps is not None
            else float(qr_controls()[self.spec.profile]["target_fps"])
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
        qr_layouts = {}
        renderer = self.renderer or LabRenderer(self.marker_size)
        for name, control in qr_controls().items():
            qr_layouts[name] = renderer.qr_layout(int(control["total_modules"]))
        payload = {
            "schema": "superqr-phy-lab-sender-v3",
            "production_wire_frozen": False,
            "presentation": {
                "display_index": self.display_index,
                "fullscreen": self.fullscreen,
                "marker_size_px": self.marker_size,
                "ready_seconds": self.ready_seconds,
                "done_seconds": self.done_seconds,
                "qr_layouts": qr_layouts,
            },
            "state": self.state.value,
            "runs_completed": len(self.run_results),
            "runs_total": len(self.runs),
            "runs": [asdict(result) for result in self.run_results],
            "current": asdict(self.snapshot()),
            "runtime_isolation": "process" if self._external_stop_requested else "in_process",
            "presenter_process_id": os.getpid(),
        }
        return payload

    def stop(self) -> None:
        self._stop_requested = True
        if self.state != CampaignState.DONE:
            self.state = CampaignState.STOPPED
        if self.display is not None:
            self.display.close()

    def request_stop(self) -> None:
        """Signal lengthy frame preparation without touching SDL cross-thread."""
        self._stop_requested = True

    def _should_stop(self) -> bool:
        return self._stop_requested or (
            self._external_stop_requested is not None and self._external_stop_requested()
        )

    def launch_config(self) -> CampaignLaunchConfig:
        return CampaignLaunchConfig(
            runs=tuple(self.runs),
            display_index=self.display_index,
            fullscreen=self.fullscreen,
            marker_size=self.marker_size,
            ready_seconds=self.ready_seconds,
            done_seconds=self.done_seconds,
            first_run_token=self.run_token or self.next_token,
        )


def _snapshot_to_wire(snapshot: PresentationSnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload["state"] = snapshot.state.value
    return payload


def _snapshot_from_wire(payload: dict[str, Any]) -> PresentationSnapshot:
    values = dict(payload)
    values["state"] = CampaignState(values["state"])
    return PresentationSnapshot(**values)


def _publish_campaign_update(
    updates: Any,
    presenter: Phase1CampaignPresenter,
    *,
    final: bool = False,
) -> None:
    message = {
        "snapshot": _snapshot_to_wire(presenter.snapshot()),
        "export": presenter.export_payload(),
        "final": final,
    }
    try:
        updates.put_nowait(message)
        return
    except queue.Full:
        pass
    # Live telemetry is latest-value state, not an event log. Discarding one stale
    # sample prevents display timing from ever waiting on a slow Tk consumer.
    try:
        updates.get_nowait()
    except queue.Empty:
        pass
    try:
        updates.put(message, timeout=0.1 if final else 0.0)
    except queue.Full:
        pass


def _campaign_process_main(config: CampaignLaunchConfig, stop_event: Any, updates: Any) -> None:
    """Child entry point: all SDL ownership and blocking swaps stay in this process."""
    presenter = Phase1CampaignPresenter(
        list(config.runs),
        display_index=config.display_index,
        fullscreen=config.fullscreen,
        marker_size=config.marker_size,
        ready_seconds=config.ready_seconds,
        done_seconds=config.done_seconds,
        first_run_token=config.first_run_token,
        stop_requested=stop_event.is_set,
    )
    last_publish = 0.0
    try:
        presenter.start()
        _publish_campaign_update(updates, presenter)
        while not stop_event.is_set():
            keep_running = presenter.tick()
            now = time.perf_counter()
            if now - last_publish >= 0.05 or not keep_running:
                _publish_campaign_update(updates, presenter)
                last_publish = now
            if not keep_running:
                break
        if stop_event.is_set() and presenter.state not in (
            CampaignState.DONE, CampaignState.ERROR, CampaignState.STOPPED,
        ):
            presenter.stop()
    except Exception as exc:
        presenter.error = f"{type(exc).__name__}: {exc}"
        presenter.state = CampaignState.ERROR
    finally:
        if presenter.display is not None:
            presenter.display.close()
        _publish_campaign_update(updates, presenter, final=True)


class Phase1CampaignWorker:
    """Runs Pygame/SDL outside Tk's process and exposes non-blocking snapshots."""

    def __init__(self, presenter: Phase1CampaignPresenter):
        self._config = presenter.launch_config()
        self._context = multiprocessing.get_context("spawn")
        self._stop = self._context.Event()
        self._updates = self._context.Queue(maxsize=8)
        self._process: multiprocessing.Process | None = None
        self._launch_thread: threading.Thread | None = None
        self._launch_error: str | None = None
        self._snapshot: PresentationSnapshot | None = None
        self._export: dict[str, Any] | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("campaign worker already started")
        self._process = self._context.Process(
            target=_campaign_process_main,
            args=(self._config, self._stop, self._updates),
            name="superqr-phy-present",
            daemon=False,
        )
        # Windows spawn may take hundreds of milliseconds on slower machines.
        # Keep that syscall outside the Tk callback; this thread never owns SDL.
        self._launch_thread = threading.Thread(
            target=self._launch_process,
            name="superqr-phy-launch",
            daemon=True,
        )
        self._launch_thread.start()

    def _launch_process(self) -> None:
        try:
            assert self._process is not None
            self._process.start()
        except Exception as exc:
            self._launch_error = f"{type(exc).__name__}: {exc}"

    def _drain_updates(self) -> None:
        while True:
            try:
                message = self._updates.get_nowait()
            except queue.Empty:
                break
            self._snapshot = _snapshot_from_wire(message["snapshot"])
            self._export = message["export"]

    def snapshot(self) -> PresentationSnapshot | None:
        self._drain_updates()
        if self._snapshot is None and self._launch_error is not None:
            first = self._config.runs[0]
            self._snapshot = PresentationSnapshot(
                state=CampaignState.ERROR,
                profile=first.profile,
                dwell_epochs=first.dwell_epochs,
                run_token=self._config.first_run_token,
                run_number=1,
                run_total=len(self._config.runs),
                frame_index=0,
                frame_count=first.frame_count,
                ready_remaining_s=0.0,
                present_count=0,
                logical_fps=0.0,
                present_fps=0.0,
                late_presents=0,
                render_prepare_ms=0.0,
                timing_mode="UNKNOWN",
                vsync_verified=False,
                present_interval_ms=0.0,
                timing_note="presentation process did not start",
                error=self._launch_error,
            )
        return self._snapshot

    def export_payload(self) -> dict:
        self._drain_updates()
        if self._export is None:
            raise RuntimeError("presentation has not published metrics yet")
        return self._export

    def is_alive(self) -> bool:
        if self._launch_thread is not None and self._launch_thread.is_alive():
            return True
        return self._process is not None and self._process.is_alive()

    def request_stop(self) -> None:
        """Request shutdown without blocking the Tk event handler."""
        self._stop.set()

    def stop(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        self._stop.set()
        launch_thread = self._launch_thread
        if launch_thread is not None and launch_thread.is_alive():
            launch_thread.join(max(0.0, deadline - time.monotonic()))
        if launch_thread is not None and launch_thread.is_alive():
            # The launch thread will observe the already-set stop event as soon
            # as spawn returns. Avoid racing Process.is_alive() with start().
            return
        process = self._process
        if process is not None and process.is_alive():
            process.join(max(0.0, deadline - time.monotonic()))
        if process is not None and process.is_alive():
            process.terminate()
            process.join(1.0)
        self._drain_updates()
