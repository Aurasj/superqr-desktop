"""Clean controller for Phase 1 physical test campaigns.

Exposes a deterministic lifecycle state machine so the UI never infers state
from worker.is_alive() alone.
"""

from __future__ import annotations

from enum import Enum

from superqr_desktop.campaign.qr_capacity_map import build_qr_capacity_map_runs
from superqr_desktop.campaign.qr_ecc_map import build_qr_ecc_map_runs
from superqr_desktop.v7_capacity_lab.advanced_campaign import (
    AdvancedCampaignPresenter,
    AdvancedCampaignWorker,
)
from superqr_desktop.v7_capacity_lab.advanced_phy import (
    advanced_profile,
    advanced_profiles,
    default_advanced_profile_name,
)
from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    Phase1CampaignWorker,
    PresentationSnapshot,
    RunSpec,
    build_campaign,
)
from superqr_desktop.v7_capacity_lab.phase1_profiles import grid_profiles, qr_controls


class CampaignLifecycle(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CampaignController:
    PRESETS = [
        "Selected profile",
        "All canonical profiles",
        "Monochrome density sweep",
        "Full grid dwell sweep",
        "V40 cadence sweep",
        "QR capacity cadence map",
        "QR ECC focused map",
        "Phase 0 advanced FAST",
        "Phase 0 advanced selection",
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
        self._worker: Phase1CampaignWorker | AdvancedCampaignWorker | None = None
        self._lifecycle = CampaignLifecycle.IDLE
        self._display_reclaimed = False
        self._rebuild_runs()

    @property
    def lifecycle(self) -> CampaignLifecycle:
        return self._lifecycle

    @property
    def needs_display_reclaim(self) -> bool:
        """True exactly once when the UI must reopen the main SDL display."""
        return self._lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED) and not self._display_reclaimed

    def _transition(self, target: CampaignLifecycle) -> None:
        self._lifecycle = target
        self._display_reclaimed = False

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
        return list(grid_profiles()) + list(qr_controls()) + list(advanced_profiles())

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

    def start(self, *, ready_seconds: float = 4.0, done_seconds: float = 2.0) -> bool:
        """Begin a campaign. Returns False if no runs configured.

        Advanced profiles run in their own process-isolated presenter so the
        canonical single-lane campaign engine remains behaviorally frozen.
        """
        if self._lifecycle != CampaignLifecycle.IDLE:
            return False
        if not self._runs:
            return False
        is_advanced = any(run.profile in advanced_profiles() for run in self._runs)
        if is_advanced and not all(run.profile in advanced_profiles() for run in self._runs):
            raise ValueError("advanced and canonical profiles cannot share one campaign")
        presenter_kwargs = dict(
            display_index=self._display_index,
            fullscreen=self._fullscreen,
            marker_size=self._marker_size,
            ready_seconds=ready_seconds,
            done_seconds=done_seconds,
        )
        if is_advanced:
            presenter = AdvancedCampaignPresenter(self._runs, **presenter_kwargs)
            self._worker = AdvancedCampaignWorker(presenter)
        else:
            presenter = Phase1CampaignPresenter(self._runs, **presenter_kwargs)
            self._worker = Phase1CampaignWorker(presenter)
        self._worker.start()
        self._transition(CampaignLifecycle.STARTING)
        return True

    def request_stop(self) -> None:
        if self._lifecycle not in (CampaignLifecycle.STARTING, CampaignLifecycle.RUNNING):
            return
        if self._worker is not None:
            self._worker.request_stop()
        self._transition(CampaignLifecycle.STOPPING)

    def reclaim_display(self) -> PresentationSnapshot | None:
        if self._lifecycle not in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
            return None
        snapshot = self.snapshot()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._display_reclaimed = True
        self._transition(CampaignLifecycle.IDLE)
        return snapshot

    def poll(self) -> None:
        if self._lifecycle == CampaignLifecycle.IDLE:
            return
        if self._worker is None:
            self._transition(CampaignLifecycle.FAILED)
            return
        snapshot = self._worker.snapshot()
        if self._lifecycle == CampaignLifecycle.STARTING:
            if not self._worker.is_alive():
                self._transition(CampaignLifecycle.FAILED)
            elif snapshot is not None and snapshot.state in (
                CampaignState.READY, CampaignState.RUNNING,
            ):
                self._transition(CampaignLifecycle.RUNNING)
            return
        if self._lifecycle == CampaignLifecycle.RUNNING:
            if snapshot is not None and snapshot.error:
                self._transition(CampaignLifecycle.FAILED)
            elif not self._worker.is_alive():
                self._transition(CampaignLifecycle.COMPLETED)
            return
        if self._lifecycle == CampaignLifecycle.STOPPING:
            if not self._worker.is_alive():
                self._transition(CampaignLifecycle.COMPLETED)
            return

    def snapshot(self) -> PresentationSnapshot | None:
        if self._worker is not None:
            return self._worker.snapshot()
        return None

    def _advanced_run(self, name: str) -> RunSpec:
        profile = advanced_profile(name)
        fps = float(profile["target_fps"])
        if fps > 30.0:
            raise ValueError("advanced receiver design ceiling is 30 FPS")
        return RunSpec(name, self._dwell, self._frames, target_fps=fps)

    def _rebuild_runs(self) -> None:
        if self._preset == "QR capacity cadence map":
            self._runs = build_qr_capacity_map_runs(self._dwell, self._frames)
            return
        if self._preset == "QR ECC focused map":
            self._runs = build_qr_ecc_map_runs(self._dwell, self._frames)
            return
        if self._preset == "Phase 0 advanced FAST":
            self._runs = [self._advanced_run(default_advanced_profile_name())]
            return
        if self._preset == "Phase 0 advanced selection":
            names = [
                "advanced_quad_qr_v27_l_fast20",
                "advanced_hybrid_qr2_c4_c8_20",
                "advanced_hybrid_qr2_c8_c16_20",
                "advanced_quad_qr_v27_l_ceiling30",
            ]
            self._runs = [self._advanced_run(name) for name in names]
            return
        if self._preset == "Selected profile" and self._profile in advanced_profiles():
            self._runs = [self._advanced_run(self._profile)]
            return
        self._runs = build_campaign(
            self._preset, self._profile, self._dwell, self._frames,
        )
