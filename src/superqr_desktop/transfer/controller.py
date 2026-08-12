"""Production transfer controller for the selected V40-L optical mode."""

from __future__ import annotations

from enum import Enum

from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.sender import V7SenderSession


class TransferLifecycle(str, Enum):
    IDLE = "IDLE"
    PRESENTING = "PRESENTING"


class TransferController:
    INTERVAL_PRESETS = V7SenderSession.INTERVAL_PRESETS
    TARGET_FPS = V7SenderSession.PRODUCTION_FPS

    def __init__(self):
        self._session = V7SenderSession()
        self._lifecycle = TransferLifecycle.IDLE

    @property
    def lifecycle(self) -> TransferLifecycle:
        return self._lifecycle

    def select_file(self, path: str) -> None:
        self._session.prepare_transfer(path)

    def set_profile(self, profile: OpticalProfile | int | str) -> None:
        self._session.set_profile(profile)

    def set_interval(self, ms: float) -> None:
        self._session.set_interval(ms)

    def start_presenting(self) -> bool:
        if self._lifecycle != TransferLifecycle.IDLE or not self.has_file:
            return False
        if not self._session.start_transfer():
            return False
        self._lifecycle = TransferLifecycle.PRESENTING
        return True

    def stop_presenting(self) -> None:
        self._session.stop_transfer()
        self._lifecycle = TransferLifecycle.IDLE

    def get_frame_symbols(self, frame_idx: int | None = None) -> list[int]:
        return self._session.get_frame_symbols(frame_idx)

    def get_frame_bytes(self, frame_idx: int | None = None) -> bytes:
        return self._session.get_frame_bytes(frame_idx)

    def note_presented(self, frame_idx: int, loop_index: int) -> None:
        self._session.note_presented(frame_idx, loop_index)

    def advance_frame(self) -> int:
        return self._session.advance_frame()

    def prev_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.prev_frame()

    def next_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.next_frame()

    @property
    def state(self) -> str:
        return self._session.transfer_state

    @property
    def profile(self) -> OpticalProfile:
        return self._session.profile

    @property
    def interval_ms(self) -> float:
        return self._session.interval_ms

    @property
    def current_frame_idx(self) -> int:
        return self._session.current_frame_idx

    @property
    def presentation_loop(self) -> int:
        return self._session.presentation_loop

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

    @property
    def nominal_payload_kib_s(self) -> float:
        return self.profile.payload_size * self.TARGET_FPS / 1024.0

    def close(self) -> None:
        self.stop_presenting()
        self._session.close()
