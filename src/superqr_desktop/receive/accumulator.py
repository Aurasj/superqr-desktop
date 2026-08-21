"""Disk-backed accumulator for the production V40 QR carousel.

Frames may arrive out of order or repeatedly. Only a compact received-frame
bitmap and one frame payload are held in memory; package/file verification and
compaction are streamed so large transfers remain bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tempfile
import zlib

from superqr_desktop.v7.profiles import BY_ID
from superqr_desktop.v7.transport import (
    MAX_FILENAME_BYTES,
    MAX_MIME_BYTES,
    PACKAGE_HEADER_SIZE,
    PACKAGE_MAGIC,
    V7TransportError,
    parse_frame,
)


MAX_TRANSFER_FRAMES = 2_000_000
COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ReceiveProgress:
    session_id: int | None
    profile_id: int | None
    total_frames: int
    unique_frames: int
    duplicate_frames: int
    received_payload_bytes: int

    @property
    def fraction(self) -> float:
        return self.unique_frames / self.total_frames if self.total_frames else 0.0


@dataclass(frozen=True)
class ReceivedArtifact:
    path: Path
    filename: str
    mime_type: str
    file_size: int
    crc32: int
    sha256: str
    session_id: int
    profile_id: int

    def save_to(self, destination: str | os.PathLike[str]) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("rb") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, COPY_CHUNK_SIZE)
        return target

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


class ProductionQrAccumulator:
    """Reassembles one production session and stages its verified file."""

    def __init__(self, temp_dir: str | os.PathLike[str] | None = None):
        self._temp_dir = Path(temp_dir) if temp_dir is not None else None
        self._path: Path | None = None
        self._handle = None
        self._session_id: int | None = None
        self._profile_id: int | None = None
        self._total_frames = 0
        self._received = bytearray()
        self._unique_frames = 0
        self._duplicate_frames = 0
        self._received_payload_bytes = 0
        self._last_payload_length: int | None = None
        self._artifact: ReceivedArtifact | None = None

    @property
    def artifact(self) -> ReceivedArtifact | None:
        return self._artifact

    @property
    def progress(self) -> ReceiveProgress:
        return ReceiveProgress(
            self._session_id,
            self._profile_id,
            self._total_frames,
            self._unique_frames,
            self._duplicate_frames,
            self._received_payload_bytes,
        )

    def accept(self, raw_frame: bytes) -> bool:
        """Accept one exact wire frame. Returns True only for a new frame."""
        if self._artifact is not None:
            return False
        frame = parse_frame(raw_frame)
        if self._session_id is None:
            self._begin(frame.session_id, frame.profile_id, frame.total_frames)
        elif (
            frame.session_id != self._session_id
            or frame.profile_id != self._profile_id
            or frame.total_frames != self._total_frames
        ):
            raise V7TransportError("frame belongs to a different active transfer")

        if self._received[frame.frame_id]:
            self._duplicate_frames += 1
            return False

        profile = BY_ID[frame.profile_id]
        assert self._handle is not None
        self._handle.seek(frame.frame_id * profile.payload_size)
        self._handle.write(frame.payload)
        self._received[frame.frame_id] = 1
        self._unique_frames += 1
        self._received_payload_bytes += len(frame.payload)
        if frame.frame_id == frame.total_frames - 1:
            self._last_payload_length = len(frame.payload)
        if self._unique_frames == self._total_frames:
            self._artifact = self._verify_and_stage()
        return True

    def reset(self, discard_artifact: bool = True) -> None:
        self._close_handle()
        if self._path is not None and (discard_artifact or self._artifact is None):
            self._path.unlink(missing_ok=True)
        self._path = None
        self._session_id = None
        self._profile_id = None
        self._total_frames = 0
        self._received = bytearray()
        self._unique_frames = 0
        self._duplicate_frames = 0
        self._received_payload_bytes = 0
        self._last_payload_length = None
        self._artifact = None

    def close(self) -> None:
        self.reset(discard_artifact=True)

    def _begin(self, session_id: int, profile_id: int, total_frames: int) -> None:
        if total_frames > MAX_TRANSFER_FRAMES:
            raise V7TransportError(
                f"transfer declares {total_frames:,} frames; limit is {MAX_TRANSFER_FRAMES:,}"
            )
        directory = str(self._temp_dir) if self._temp_dir is not None else None
        fd, name = tempfile.mkstemp(prefix="superqr-receive-", suffix=".part", dir=directory)
        self._path = Path(name)
        self._handle = os.fdopen(fd, "w+b", buffering=0)
        self._session_id = session_id
        self._profile_id = profile_id
        self._total_frames = total_frames
        self._received = bytearray(total_frames)

    def _verify_and_stage(self) -> ReceivedArtifact:
        assert self._handle is not None
        assert self._path is not None
        assert self._session_id is not None
        assert self._profile_id is not None
        if self._last_payload_length is None:
            raise V7TransportError("final frame payload length is unavailable")
        profile = BY_ID[self._profile_id]
        package_size = (self._total_frames - 1) * profile.payload_size + self._last_payload_length
        self._handle.flush()
        self._handle.seek(0)
        header = self._handle.read(PACKAGE_HEADER_SIZE)
        if len(header) != PACKAGE_HEADER_SIZE or header[:4] != PACKAGE_MAGIC:
            raise V7TransportError("invalid or truncated V7 package header")
        filename_len, mime_len, file_size, expected_crc = struct.unpack(">HHQI", header[4:20])
        if not 1 <= filename_len <= MAX_FILENAME_BYTES:
            raise V7TransportError("invalid filename length")
        if mime_len > MAX_MIME_BYTES:
            raise V7TransportError("invalid MIME length")
        metadata_end = PACKAGE_HEADER_SIZE + filename_len + mime_len
        if metadata_end + file_size != package_size:
            raise V7TransportError("package length does not match declared file size")
        metadata = self._handle.read(filename_len + mime_len)
        if len(metadata) != filename_len + mime_len:
            raise V7TransportError("truncated V7 package metadata")
        try:
            wire_filename = metadata[:filename_len].decode("utf-8")
            mime_type = metadata[filename_len:].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise V7TransportError("invalid UTF-8 package metadata") from exc
        filename = Path(wire_filename.replace("\\", "/")).name
        if not filename or filename in (".", ".."):
            raise V7TransportError("unsafe or empty received filename")

        crc = 0
        digest = hashlib.sha256()
        remaining = file_size
        while remaining:
            chunk = self._handle.read(min(COPY_CHUNK_SIZE, remaining))
            if not chunk:
                raise V7TransportError("received file is truncated")
            crc = zlib.crc32(chunk, crc)
            digest.update(chunk)
            remaining -= len(chunk)
        crc &= 0xFFFFFFFF
        if crc != expected_crc:
            raise V7TransportError(
                f"file CRC32 mismatch: expected {expected_crc:08X}, got {crc:08X}"
            )

        # Compact the payload over its package prefix. The destination always
        # trails the source read cursor, so one-file forward copying is safe.
        read_offset = metadata_end
        write_offset = 0
        remaining = file_size
        while remaining:
            self._handle.seek(read_offset)
            chunk = self._handle.read(min(COPY_CHUNK_SIZE, remaining))
            if not chunk:
                raise V7TransportError("received file vanished during staging")
            self._handle.seek(write_offset)
            self._handle.write(chunk)
            read_offset += len(chunk)
            write_offset += len(chunk)
            remaining -= len(chunk)
        self._handle.truncate(file_size)
        self._handle.flush()
        self._close_handle()
        return ReceivedArtifact(
            path=self._path,
            filename=filename,
            mime_type=mime_type or "application/octet-stream",
            file_size=file_size,
            crc32=crc,
            sha256=digest.hexdigest(),
            session_id=self._session_id,
            profile_id=self._profile_id,
        )

    def _close_handle(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None
