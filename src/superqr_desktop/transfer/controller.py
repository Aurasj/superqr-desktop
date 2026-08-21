"""Production transfer controller for selectable V40 optical modes."""

from __future__ import annotations

from enum import Enum

from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.sender import V7SenderSession


class TransferLifecycle(str, Enum):
    IDLE = "IDLE"
    PRESENTING = "PRESENTING"


class TransferController:
    MODES = {
        "Auto / safe — V40-L · 15 FPS": "v40_l_15fps",
        "Faster — V40-L · 20 FPS": "v40_l_20fps",
        "30 FPS test — V40-L · 30 FPS": "v40_l_30fps",
        "Extra ECC — V40-M · 15 FPS": "v40_m_15fps",
        "Extra ECC faster — V40-M · 20 FPS": "v40_m_20fps",
        "30 FPS ECC test — V40-M · 30 FPS": "v40_m_30fps",
    }
    DEFAULT_MODE = "Auto / safe — V40-L · 15 FPS"
    MODE_NOTES = {
        "Auto / safe — V40-L · 15 FPS": "Recommended automatic default with the most temporal headroom.",
        "Faster — V40-L · 20 FPS": "Higher nominal speed • less temporal headroom; use when the camera holds up.",
        "30 FPS test — V40-L · 30 FPS": "Experimental • matches the receiver camera target; compare real completion speed and misses.",
        "Extra ECC — V40-M · 15 FPS": "More QR error correction, but less payload per frame than V40-L.",
        "Extra ECC faster — V40-M · 20 FPS": "More QR ECC plus 20 FPS • experimental throughput/robustness tradeoff.",
        "30 FPS ECC test — V40-M · 30 FPS": "Experimental • stronger QR ECC at 30 FPS for a direct robustness comparison.",
    }
    def __init__(self):
        self._session = V7SenderSession()
        self._lifecycle = TransferLifecycle.IDLE
        self._mode = self.DEFAULT_MODE

    @property
    def lifecycle(self) -> TransferLifecycle:
        return self._lifecycle

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def mode_note(self) -> str:
        return self.MODE_NOTES[self._mode]

    @property
    def mode_options(self) -> tuple[str, ...]:
        return tuple(self.MODES.keys())

    def set_mode(self, mode: str) -> None:
        if self._lifecycle == TransferLifecycle.PRESENTING:
            raise RuntimeError("stop the active transfer before changing mode")
        if mode not in self.MODES:
            raise ValueError(f"unknown transfer mode: {mode}")
        self._session.set_profile(self.MODES[mode])
        self._mode = mode

    def select_file(self, path: str) -> None:
        self._session.prepare_transfer(path)

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

    def get_frame_bytes(self, frame_idx: int) -> bytes:
        return self._session.get_frame_bytes(frame_idx)

    @property
    def profile(self) -> OpticalProfile:
        return self._session.profile

    @property
    def interval_ms(self) -> float:
        return self._session.interval_ms

    @property
    def target_fps(self) -> float:
        return self._session.target_fps

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
        return self.profile.payload_size * self.target_fps / 1024.0

    def close(self) -> None:
        self.stop_presenting()
        self._session.close()
