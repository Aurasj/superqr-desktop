import os
from superqr_desktop.v6.transport import (
    build_transfer_package,
    create_frames,
    bytes_to_palette_indexes,
    MAX_PACKAGE_SIZE
)

class V6SenderSession:
    INTERVAL_PRESETS = [50, 67, 75, 100, 200, 500]

    def __init__(self):
        self.session_id_counter = 0
        self.transfer_state = "IDLE"  # IDLE, READY, SENDING, STOPPED
        self.filename = None
        self.file_size = 0
        self.package_size = 0
        self.session_id = None
        self.frames = []
        self.total_frames = 0
        self.current_frame_idx = 0
        self.interval_ms = 100

    def next_session_id(self) -> int:
        self.session_id_counter = (self.session_id_counter % 255) + 1
        return self.session_id_counter

    def prepare_transfer(self, filename: str, file_data: bytes) -> int:
        pkg = build_transfer_package(filename, file_data)
        sid = self.next_session_id()
        raw_frames = create_frames(sid, pkg)
        palette_frames = [bytes_to_palette_indexes(f) for f in raw_frames]

        self.filename = filename
        self.file_size = len(file_data)
        self.package_size = len(pkg)
        self.session_id = sid
        self.frames = palette_frames
        self.total_frames = len(palette_frames)
        self.current_frame_idx = 0
        self.transfer_state = "READY"
        return sid

    def start_transfer(self) -> bool:
        if not self.frames or self.transfer_state not in ("READY", "STOPPED"):
            return False
        self.transfer_state = "SENDING"
        self.current_frame_idx = 0
        return True

    def stop_transfer(self):
        if self.transfer_state == "SENDING":
            self.transfer_state = "STOPPED"

    def set_static_pattern(self):
        if self.transfer_state == "SENDING":
            self.transfer_state = "STOPPED"

    def advance_frame(self) -> int:
        if self.total_frames == 0:
            return 0
        idx = self.current_frame_idx
        self.current_frame_idx = (self.current_frame_idx + 1) % self.total_frames
        return idx

    def prev_frame(self) -> int:
        if self.total_frames == 0 or self.transfer_state == "SENDING":
            return self.current_frame_idx
        self.current_frame_idx = (self.current_frame_idx - 1) % self.total_frames
        return self.current_frame_idx

    def next_frame(self) -> int:
        if self.total_frames == 0 or self.transfer_state == "SENDING":
            return self.current_frame_idx
        self.current_frame_idx = (self.current_frame_idx + 1) % self.total_frames
        return self.current_frame_idx

    def get_current_frame_indexes(self) -> list[int] | None:
        if self.frames and 0 <= self.current_frame_idx < self.total_frames:
            return self.frames[self.current_frame_idx]
        return None

    def set_interval(self, ms: int):
        if ms in self.INTERVAL_PRESETS:
            self.interval_ms = ms

