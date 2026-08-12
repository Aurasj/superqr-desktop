"""Clean controller wrapping the V7 streaming sender session.

Transfer presentation is in-process: frames are rendered on the main SDL
display via the tick loop, matching the original ControlApp approach.
Campaign presentation remains child-process for timing isolation.
"""

from __future__ import annotations

from enum import Enum

from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.sender import V7SenderSession


class TransferLifecycle(str, Enum):
    IDLE = "IDLE"
    PRESENTING = "PRESENTING"


class TransferController:
    INTERVAL_PRESETS = V7SenderSession.INTERVAL_PRESETS

    def __init__(self):
        self._session = V7SenderSession()
        self._lifecycle = TransferLifecycle.IDLE

    # -- lifecycle ---------------------------------------------------------

    @property
    def lifecycle(self) -> TransferLifecycle:
        return self._lifecycle

    # -- configuration -----------------------------------------------------

    def select_file(self, path: str) -> None:
        self._session.prepare_transfer(path)

    def set_profile(self, profile: OpticalProfile | int | str) -> None:
        self._session.set_profile(profile)

    def set_interval(self, ms: int) -> None:
        self._session.set_interval(ms)

    # -- presentation (in-process) ----------------------------------------

    def start_presenting(self) -> bool:
        """Begin in-process presentation. Caller must own the SDL display."""
        if self._lifecycle != TransferLifecycle.IDLE:
            return False
        if not self.has_file:
            return False
        self._session.start_transfer()
        self._lifecycle = TransferLifecycle.PRESENTING
        return True

    def stop_presenting(self) -> None:
        """Stop in-process presentation and return to IDLE."""
        self._session.stop_transfer()
        self._lifecycle = TransferLifecycle.IDLE

    # -- frame data --------------------------------------------------------

    def get_frame_symbols(self) -> list[int]:
        return self._session.get_frame_symbols()

    def get_frame_bytes(self) -> bytes:
        return self._session.get_frame_bytes()

    def advance_frame(self) -> int:
        return self._session.advance_frame()

    def prev_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.prev_frame()

    def next_frame(self) -> int:
        self._session.stop_transfer()
        return self._session.next_frame()

    # -- read-only state ---------------------------------------------------

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
