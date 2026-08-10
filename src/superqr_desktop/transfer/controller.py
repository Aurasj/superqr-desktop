"""Clean controller wrapping the V7 streaming sender session."""

from __future__ import annotations

from superqr_desktop.v7.profiles import OpticalProfile, get_profile
from superqr_desktop.v7.sender import V7SenderSession


class TransferController:
    """Adapter around V7SenderSession with a UI-friendly interface."""

    INTERVAL_PRESETS = V7SenderSession.INTERVAL_PRESETS

    def __init__(self):
        self._session = V7SenderSession()

    # -- file / transfer lifecycle --

    def select_file(self, path: str) -> None:
        self._session.prepare_transfer(path)

    def start(self) -> bool:
        return self._session.start_transfer()

    def stop(self) -> None:
        self._session.stop_transfer()

    # -- profile & timing --

    def set_profile(self, profile: OpticalProfile | int | str) -> None:
        self._session.set_profile(profile)

    def set_interval(self, ms: int) -> None:
        self._session.set_interval(ms)

    # -- frame data --

    def get_frame_symbols(self) -> list[int]:
        return self._session.get_frame_symbols()

    def advance_frame(self) -> int:
        return self._session.advance_frame()

    def prev_frame(self) -> int:
        return self._session.prev_frame()

    def next_frame(self) -> int:
        return self._session.next_frame()

    # -- read-only state --

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
