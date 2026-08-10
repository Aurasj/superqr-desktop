"""Clean controller wrapping the V7 streaming sender session.

Manages file selection, profile/interval configuration, and a child-process
transfer presentation worker. Manual Prev/Next work synchronously in-process
when no worker is active.
"""

from __future__ import annotations

from enum import Enum

from superqr_desktop.presentation.transfer_worker import (
    TransferLaunchConfig,
    TransferPresentationWorker,
    TransferSnapshot,
)
from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.sender import V7SenderSession


class TransferLifecycle(str, Enum):
    IDLE = "IDLE"
    PRESENTING = "PRESENTING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransferController:
    INTERVAL_PRESETS = V7SenderSession.INTERVAL_PRESETS

    def __init__(self):
        self._session = V7SenderSession()
        self._worker: TransferPresentationWorker | None = None
        self._lifecycle = TransferLifecycle.IDLE
        self._display_reclaimed = False

    # -- lifecycle -----------------------------------------------------------------

    @property
    def lifecycle(self) -> TransferLifecycle:
        return self._lifecycle

    @property
    def needs_display_reclaim(self) -> bool:
        return (self._lifecycle in (TransferLifecycle.COMPLETED, TransferLifecycle.FAILED)
                and not self._display_reclaimed)

    def _transition(self, target: TransferLifecycle) -> None:
        self._lifecycle = target
        self._display_reclaimed = False

    # -- configuration ------------------------------------------------------------

    def select_file(self, path: str) -> None:
        self._session.prepare_transfer(path)

    def set_profile(self, profile: OpticalProfile | int | str) -> None:
        self._session.set_profile(profile)

    def set_interval(self, ms: int) -> None:
        self._session.set_interval(ms)

    # -- manual frame navigation (only valid when NOT presenting) -----------------

    def get_frame_symbols(self) -> list[int]:
        return self._session.get_frame_symbols()

    def prev_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.prev_frame()

    def next_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.next_frame()

    # -- worker-based presentation ------------------------------------------------

    def start_presenting(self, display_index: int, fullscreen: bool, marker_size: int) -> bool:
        """Launch the transfer worker. Caller must release SDL display first."""
        if self._lifecycle != TransferLifecycle.IDLE:
            return False
        if not self.has_file:
            return False
        config = TransferLaunchConfig(
            file_path=self._session.file_path,
            profile_key=self._session.profile.key,
            interval_ms=self._session.interval_ms,
            display_index=display_index,
            fullscreen=fullscreen,
            marker_size=marker_size,
        )
        self._worker = TransferPresentationWorker()
        self._worker.start(config)
        self._transition(TransferLifecycle.PRESENTING)
        return True

    def request_stop(self) -> None:
        if self._lifecycle != TransferLifecycle.PRESENTING:
            return
        if self._worker is not None:
            self._worker.request_stop()
        self._transition(TransferLifecycle.STOPPING)

    def reclaim_display(self) -> TransferSnapshot | None:
        """Call exactly once when needs_display_reclaim is True."""
        if self._lifecycle not in (TransferLifecycle.COMPLETED, TransferLifecycle.FAILED):
            return None
        snapshot = self.snapshot()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._display_reclaimed = True
        self._transition(TransferLifecycle.IDLE)
        return snapshot

    # -- polling ------------------------------------------------------------------

    def poll(self) -> None:
        if self._lifecycle in (TransferLifecycle.IDLE, TransferLifecycle.COMPLETED, TransferLifecycle.FAILED):
            return
        if self._worker is None:
            self._transition(TransferLifecycle.FAILED)
            return

        snapshot = self._worker.snapshot()

        if self._lifecycle == TransferLifecycle.PRESENTING:
            if snapshot is not None and snapshot.error:
                self._transition(TransferLifecycle.FAILED)
            elif not self._worker.is_alive():
                self._transition(TransferLifecycle.COMPLETED)
            return

        if self._lifecycle == TransferLifecycle.STOPPING:
            if not self._worker.is_alive():
                self._transition(TransferLifecycle.COMPLETED)
            return

    def snapshot(self) -> TransferSnapshot | None:
        if self._worker is not None:
            return self._worker.snapshot()
        return None

    # -- read-only state ----------------------------------------------------------

    @property
    def state(self) -> str:
        return self._session.transfer_state

    @property
    def profile(self) -> OpticalProfile:
        return self._session.profile

    @property
    def interval_ms(self) -> int:
        return self._session.interval_ms

    @property
    def current_frame_idx(self) -> int:
        return self._session.current_frame_idx

    @property
    def total_frames(self) -> int:
        return self._session.total_frames

    @property
    def filename(self) -> str | None:
        return self._session.filename

    @property
    def file_size(self) -> int:
        return self._session.file_size

    @property
    def mime_type(self) -> str:
        return self._session.mime_type

    @property
    def file_crc32(self) -> int:
        return self._session.file_crc32

    @property
    def session_id(self) -> int | None:
        return self._session.session_id

    @property
    def has_file(self) -> bool:
        return self._session.file_path is not None
