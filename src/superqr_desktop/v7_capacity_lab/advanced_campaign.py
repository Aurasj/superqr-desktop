"""Isolated presenter/worker for the lab-only advanced Phase 0 PHY."""
from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from typing import Any

from superqr_desktop.v7_capacity_lab.advanced_phy import (
    advanced_profile,
    advanced_profiles,
    build_advanced_envelope,
    build_advanced_qr_matrix,
    validate_advanced_phy_vectors,
)
from superqr_desktop.v7_capacity_lab.advanced_renderer import AdvancedFrameComposer
from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignLaunchConfig,
    CampaignState,
    Phase1CampaignPresenter,
    PresentationSnapshot,
    _snapshot_from_wire,
    _snapshot_to_wire,
)
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.run_sync import RunState


class AdvancedCampaignPresenter(Phase1CampaignPresenter):
    """Phase 0 presenter for composite multi-lane profiles.

    It deliberately reuses the proven display timing state machine while keeping
    composite frame construction out of the canonical single-lane presenter.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._advanced: dict | None = None
        self._composer: AdvancedFrameComposer | None = None
        self._lane_frames: dict[int, list] = {}
        self._lane_ready: dict[int, Any] = {}
        self._lane_done: dict[int, Any] = {}

    def start(self) -> None:
        validate_advanced_phy_vectors()
        super().start()

    def _prepare_run(self, index: int) -> None:
        spec = self.runs[index]
        if spec.profile not in advanced_profiles():
            self._advanced = None
            self._composer = None
            self._lane_frames.clear()
            self._lane_ready.clear()
            self._lane_done.clear()
            super()._prepare_run(index)
            return

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
        self.qr_ready = None
        self.qr_done = None
        self._lane_frames.clear()
        self._lane_ready.clear()
        self._lane_done.clear()
        self._current_result_recorded = False

        if self.display is None:
            self.display = LabDisplayController(dwell_epochs=spec.dwell_epochs)
            self.display.setup_display(self.display_index, self.fullscreen, self.marker_size)
        else:
            self.display.configure_dwell(spec.dwell_epochs)
        self.renderer = LabRenderer(self.marker_size)
        self._composer = AdvancedFrameComposer(self.renderer)
        self._advanced = advanced_profile(spec.profile)

        if float(self._advanced["target_fps"]) > 30.0:
            raise RuntimeError("advanced profile exceeds the 30 FPS receiver ceiling")
        if spec.target_fps is None or abs(float(spec.target_fps) - float(self._advanced["target_fps"])) > 1e-9:
            raise RuntimeError("advanced run target_fps must match the manifest")

        for lane in self._advanced["lanes"]:
            if lane["kind"] != "qr":
                continue
            lane_id = int(lane["lane_id"])
            quiet = int(lane["quiet_zone_modules"])
            frames = []
            for frame_index in range(spec.frame_count):
                if self._should_stop():
                    self.state = CampaignState.STOPPED
                    return
                matrix = build_advanced_qr_matrix(
                    self._advanced,
                    lane,
                    frame_index,
                    run_token=self.run_token,
                    frame_count=spec.frame_count,
                    dwell_epochs=spec.dwell_epochs,
                )
                frames.append(self.renderer.build_qr_native_surface(matrix, quiet))
            self._lane_frames[lane_id] = frames
            self._lane_ready[lane_id] = self.renderer.build_qr_native_surface(
                build_advanced_qr_matrix(
                    self._advanced,
                    lane,
                    0,
                    run_token=self.run_token,
                    state=RunState.READY,
                    frame_count=spec.frame_count,
                    dwell_epochs=spec.dwell_epochs,
                ),
                quiet,
            )
            self._lane_done[lane_id] = self.renderer.build_qr_native_surface(
                build_advanced_qr_matrix(
                    self._advanced,
                    lane,
                    spec.frame_count - 1,
                    run_token=self.run_token,
                    state=RunState.DONE,
                    frame_count=spec.frame_count,
                    dwell_epochs=spec.dwell_epochs,
                ),
                quiet,
            )

        self.state = CampaignState.READY
        self.state_started = time.perf_counter()
        self._render(RunState.READY)

    def _render(self, state: RunState) -> None:
        if self._advanced is None:
            super()._render(state)
            return
        assert self._composer is not None
        lane_surfaces = {}
        for lane in self._advanced["lanes"]:
            if lane["kind"] != "qr":
                continue
            lane_id = int(lane["lane_id"])
            if state == RunState.READY:
                lane_surfaces[lane_id] = self._lane_ready[lane_id]
            elif state == RunState.DONE:
                lane_surfaces[lane_id] = self._lane_done[lane_id]
            else:
                lane_surfaces[lane_id] = self._lane_frames[lane_id][self.frame_index]
        sync_bits = None
        if bool(self._advanced["requires_carrier"]):
            sync_bits = build_advanced_envelope(
                self._advanced,
                self.run_token,
                self.frame_index,
                self.spec.frame_count,
                self.spec.dwell_epochs,
                state,
            ).bits()
        self._composer.prepare(
            self._advanced,
            self.frame_index,
            lane_surfaces,
            sync_bits=sync_bits,
        )

    def export_payload(self) -> dict:
        payload = super().export_payload()
        if self._advanced is not None:
            payload["advanced_phy"] = {
                "profile": self._advanced["name"],
                "profile_id": self._advanced["profile_id"],
                "lane_count": self._advanced["lane_count"],
                "target_fps": self._advanced["target_fps"],
                "receiver_max_fps": 30.0,
                "theoretical_mbps": self._advanced["theoretical_mbps"],
                "role": self._advanced["role"],
                "physical_goodput_measured": False,
            }
        return payload


def _publish(updates: Any, presenter: AdvancedCampaignPresenter, *, final: bool = False) -> None:
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
    try:
        updates.get_nowait()
    except queue.Empty:
        pass
    try:
        updates.put(message, timeout=0.1 if final else 0.0)
    except queue.Full:
        pass


def _advanced_process_main(config: CampaignLaunchConfig, stop_event: Any, updates: Any) -> None:
    presenter = AdvancedCampaignPresenter(
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
        _publish(updates, presenter)
        while not stop_event.is_set():
            keep_running = presenter.tick()
            now = time.perf_counter()
            if now - last_publish >= 0.05 or not keep_running:
                _publish(updates, presenter)
                last_publish = now
            if not keep_running:
                break
        if stop_event.is_set() and presenter.state not in (
            CampaignState.DONE,
            CampaignState.ERROR,
            CampaignState.STOPPED,
        ):
            presenter.stop()
    except Exception as exc:
        presenter.error = f"{type(exc).__name__}: {exc}"
        presenter.state = CampaignState.ERROR
    finally:
        if presenter.display is not None:
            presenter.display.close()
        _publish(updates, presenter, final=True)


class AdvancedCampaignWorker:
    """Process-isolated worker with the same UI-facing contract as Phase1CampaignWorker."""

    def __init__(self, presenter: AdvancedCampaignPresenter):
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
            raise RuntimeError("advanced campaign worker already started")
        self._process = self._context.Process(
            target=_advanced_process_main,
            args=(self._config, self._stop, self._updates),
            name="superqr-advanced-phy-present",
            daemon=False,
        )
        self._launch_thread = threading.Thread(
            target=self._launch_process,
            name="superqr-advanced-phy-launch",
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
                timing_note="advanced presentation process did not start",
                error=self._launch_error,
            )
        return self._snapshot

    def export_payload(self) -> dict:
        self._drain_updates()
        if self._export is None:
            raise RuntimeError("advanced presentation has not published metrics yet")
        return self._export

    def is_alive(self) -> bool:
        if self._launch_thread is not None and self._launch_thread.is_alive():
            return True
        return self._process is not None and self._process.is_alive()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        self._stop.set()
        if self._launch_thread is not None:
            self._launch_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        process = self._process
        if process is not None and process.is_alive():
            process.join(timeout=max(0.0, deadline - time.monotonic()))
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=0.5)
        self._drain_updates()
