"""Clean controller for Phase 1 physical test campaigns.

Wraps campaign building and the child-process Phase1CampaignWorker so the UI
never touches v7_capacity_lab internals directly.
"""

from __future__ import annotations

from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    Phase1CampaignWorker,
    PresentationSnapshot,
    RunSpec,
    build_campaign,
)
from superqr_desktop.v7_capacity_lab.phase1_profiles import grid_profiles, qr_controls


class CampaignController:
    PRESETS = [
        "Selected profile",
        "All canonical profiles",
        "Monochrome density sweep",
        "Full grid dwell sweep",
    ]

    DWELL_OPTIONS = [2, 3]

    def __init__(self):
        self._preset = "Selected profile"
        self._profile = "mono_64x50_matched"
        self._dwell = 3
        self._frames = 256
        self._display_index = 0
        self._fullscreen = False
        self._marker_size = 800
        self._runs: list[RunSpec] = []
        self._worker: Phase1CampaignWorker | None = None
        self._rebuild_runs()

    # -- configuration --

    @property
    def preset(self) -> str:
        return self._preset

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def dwell(self) -> int:
        return self._dwell

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def available_profiles(self) -> list[str]:
        return list(grid_profiles()) + list(qr_controls())

    @property
    def runs(self) -> list[RunSpec]:
        return self._runs

    @property
    def run_count(self) -> int:
        return len(self._runs)

    def set_display(self, index: int, fullscreen: bool, marker_size: int) -> None:
        self._display_index = index
        self._fullscreen = fullscreen
        self._marker_size = marker_size

    def set_preset(self, preset: str) -> None:
        if preset not in self.PRESETS:
            raise ValueError(f"unknown preset: {preset}")
        self._preset = preset
        self._rebuild_runs()

    def set_profile(self, profile: str) -> None:
        self._profile = profile
        if self._preset == "Selected profile":
            self._rebuild_runs()

    def set_dwell(self, dwell: int) -> None:
        self._dwell = dwell
        self._rebuild_runs()

    def set_frames(self, frames: int) -> None:
        self._frames = max(1, min(256, frames))
        self._rebuild_runs()

    # -- lifecycle --

    def start(self) -> bool:
        if not self._runs:
            return False
        presenter = Phase1CampaignPresenter(
            self._runs,
            display_index=self._display_index,
            fullscreen=self._fullscreen,
            marker_size=self._marker_size,
            ready_seconds=4.0,
            done_seconds=2.0,
        )
        self._worker = Phase1CampaignWorker(presenter)
        self._worker.start()
        return True

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

    def request_stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self) -> PresentationSnapshot | None:
        if self._worker is not None:
            return self._worker.snapshot()
        return None

    # -- internal --

    def _rebuild_runs(self) -> None:
        self._runs = build_campaign(
            self._preset, self._profile, self._dwell, self._frames,
        )
