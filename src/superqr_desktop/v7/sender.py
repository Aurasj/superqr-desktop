"""Streaming SuperQR V7 sender session with selectable optical profiles."""

from __future__ import annotations

import mimetypes
import os
import zlib

from superqr_desktop.v7.profiles import DEFAULT_PROFILE, OpticalProfile, get_profile
from superqr_desktop.v7.transport import build_frame, build_package_prefix, bytes_to_symbols
from superqr_desktop.v7_capacity_lab._local.model import SymbolMatrix


class V7SenderSession:
    INTERVAL_PRESETS = [25, 33, 42, 50, 67, 75, 100, 150, 200]

    def __init__(self):
        self._session_counter = 0
        self.transfer_state = "IDLE"
        self.file_path: str | None = None
        self.filename: str | None = None
        self.mime_type = "application/octet-stream"
        self.file_size = 0
        self.file_crc32 = 0
        self.package_prefix = b""
        self.package_size = 0
        self.session_id: int | None = None
        self.total_frames = 0
        self.current_frame_idx = 0
        self.interval_ms = 67
        self.profile: OpticalProfile = DEFAULT_PROFILE

    def _next_session_id(self) -> int:
        self._session_counter = (self._session_counter % 0xFFFF) + 1
        return self._session_counter

    def set_profile(self, profile: OpticalProfile | int | str) -> None:
        p = get_profile(profile)
        if p == self.profile:
            return
        was_prepared = self.file_path is not None
        path = self.file_path
        self.profile = p
        if was_prepared and path is not None:
            self.prepare_transfer(path)

    def prepare_transfer(self, file_path: str) -> int:
        if not os.path.isfile(file_path):
            raise ValueError("selected file does not exist")
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        crc = 0
        with open(file_path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        crc &= 0xFFFFFFFF
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        prefix = build_package_prefix(filename, mime_type, file_size, crc)
        package_size = len(prefix) + file_size
        payload_size = self.profile.payload_size
        total_frames = max(1, (package_size + payload_size - 1) // payload_size)

        self.file_path = file_path
        self.filename = filename
        self.mime_type = mime_type
        self.file_size = file_size
        self.file_crc32 = crc
        self.package_prefix = prefix
        self.package_size = package_size
        self.session_id = self._next_session_id()
        self.total_frames = total_frames
        self.current_frame_idx = 0
        self.transfer_state = "READY"
        return self.session_id

    def _read_package_slice(self, offset: int, length: int) -> bytes:
        if self.file_path is None:
            raise RuntimeError("no V7 transfer prepared")
        if length <= 0:
            return b""
        end = min(offset + length, self.package_size)
        if offset >= end:
            return b""
        out = bytearray()
        prefix_len = len(self.package_prefix)
        if offset < prefix_len:
            p_end = min(end, prefix_len)
            out.extend(self.package_prefix[offset:p_end])
            offset = p_end
        if offset < end:
            file_offset = offset - prefix_len
            remaining = end - offset
            with open(self.file_path, "rb") as fh:
                fh.seek(file_offset)
                chunk = fh.read(remaining)
            if len(chunk) != remaining:
                raise IOError("file changed or became unreadable during transfer")
            out.extend(chunk)
        return bytes(out)

    def get_frame_bytes(self, frame_idx: int | None = None) -> bytes:
        if self.session_id is None or self.total_frames < 1:
            raise RuntimeError("no V7 transfer prepared")
        idx = self.current_frame_idx if frame_idx is None else frame_idx
        if not (0 <= idx < self.total_frames):
            raise IndexError("frame index out of range")
        payload_size = self.profile.payload_size
        offset = idx * payload_size
        payload = self._read_package_slice(offset, payload_size)
        return build_frame(self.session_id, idx, self.total_frames, payload, self.profile)

    def get_frame_symbols(self, frame_idx: int | None = None) -> list[int]:
        return bytes_to_symbols(self.get_frame_bytes(frame_idx), self.profile)

    def get_current_matrix(self) -> SymbolMatrix:
        symbols = self.get_frame_symbols()
        g = self.profile.grid
        rows = [symbols[r * g:(r + 1) * g] for r in range(g)]
        return SymbolMatrix(rows=g, cols=g, palette_name=self.profile.palette_name, symbols=rows)

    def start_transfer(self) -> bool:
        if self.total_frames < 1 or self.transfer_state not in ("READY", "STOPPED"):
            return False
        self.transfer_state = "SENDING"
        self.current_frame_idx = 0
        return True

    def stop_transfer(self) -> None:
        if self.transfer_state == "SENDING":
            self.transfer_state = "STOPPED"

    def advance_frame(self) -> int:
        if self.total_frames < 1:
            return 0
        idx = self.current_frame_idx
        self.current_frame_idx = (self.current_frame_idx + 1) % self.total_frames
        return idx

    def prev_frame(self) -> int:
        if self.total_frames and self.transfer_state != "SENDING":
            self.current_frame_idx = (self.current_frame_idx - 1) % self.total_frames
        return self.current_frame_idx

    def next_frame(self) -> int:
        if self.total_frames and self.transfer_state != "SENDING":
            self.current_frame_idx = (self.current_frame_idx + 1) % self.total_frames
        return self.current_frame_idx

    def set_interval(self, ms: int) -> None:
        if ms in self.INTERVAL_PRESETS:
            self.interval_ms = ms
