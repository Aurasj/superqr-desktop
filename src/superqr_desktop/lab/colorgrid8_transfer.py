"""Bounded-memory ColorGrid8 v2 LAB file transport.

The optical transport is deliberately separate from production V40.  It keeps
the proven SQP7 file envelope so Android can reuse the same bounded verification
and preview-before-save path after the experimental channel has completed.
"""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import struct
import zlib

import numpy as np

from superqr_desktop.lab.colorgrid8_core import (
    ColorGrid8Profile,
    TRANSFER_HEADER_VERSION,
    build_payload_symbol_frame,
)

TRANSPORT_MAGIC = b"SQG2"
TRANSPORT_VERSION = 2
KIND_DATA = 0
KIND_XOR_PARITY = 1
XOR_GROUP_SIZE = 8
TRANSPORT_HEADER = struct.Struct(">4sBBBBIIIIII")
TRANSPORT_HEADER_SIZE = TRANSPORT_HEADER.size
BLOCK_DATA_BYTES = 512
BLOCK_CRC_BYTES = 4
PACKAGE_MAGIC = b"SQP7"
MAX_FILENAME_BYTES = 1024
MAX_MIME_BYTES = 255
MAX_DATA_FRAMES = 2_000_000


def encoded_payload_size(payload_length: int) -> int:
    if payload_length <= 0:
        return 0
    blocks = (payload_length + BLOCK_DATA_BYTES - 1) // BLOCK_DATA_BYTES
    return payload_length + blocks * BLOCK_CRC_BYTES


def logical_chunk_capacity(profile: ColorGrid8Profile) -> int:
    encoded_capacity = profile.byte_capacity - TRANSPORT_HEADER_SIZE
    logical = encoded_capacity
    while encoded_payload_size(logical) > encoded_capacity:
        logical -= 1
    return logical


@dataclass(frozen=True)
class ColorGrid8TransferInfo:
    filename: str
    mime_type: str
    file_size: int
    file_crc32: int
    session_id: int
    total_data_frames: int
    chunk_bytes: int
    carousel_frames: int
    channel_kib_s: float
    protected_kib_s: float


@dataclass(frozen=True)
class ColorGrid8TransportFrame:
    kind: int
    profile_id: int
    session_id: int
    frame_id: int
    total_data_frames: int
    chunk_capacity: int
    payload: bytes


class _PackageSource:
    """Read arbitrary slices of a virtual ``prefix + file`` package."""

    def __init__(self, path: Path):
        self.path = path
        self.file_size = path.stat().st_size
        self.file_crc32 = self._scan_crc32()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        filename_bytes = path.name.encode("utf-8")
        mime_bytes = mime_type.encode("utf-8")
        if not 1 <= len(filename_bytes) <= MAX_FILENAME_BYTES:
            raise ValueError(f"filename must be 1..{MAX_FILENAME_BYTES} UTF-8 bytes")
        if len(mime_bytes) > MAX_MIME_BYTES:
            raise ValueError(f"MIME type exceeds {MAX_MIME_BYTES} UTF-8 bytes")
        self.mime_type = mime_type
        self.prefix = (
            PACKAGE_MAGIC
            + struct.pack(
                ">HHQI",
                len(filename_bytes),
                len(mime_bytes),
                self.file_size,
                self.file_crc32,
            )
            + filename_bytes
            + mime_bytes
        )
        self.package_size = len(self.prefix) + self.file_size
        self._handle = path.open("rb")

    def _scan_crc32(self) -> int:
        crc = 0
        with self.path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                crc = zlib.crc32(chunk, crc)
        return crc & 0xFFFFFFFF

    def read_slice(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("package slice must be non-negative")
        if offset >= self.package_size or size == 0:
            return b""
        remaining = min(size, self.package_size - offset)
        chunks: list[bytes] = []
        if offset < len(self.prefix):
            prefix_end = min(len(self.prefix), offset + remaining)
            chunks.append(self.prefix[offset:prefix_end])
            consumed = prefix_end - offset
            offset += consumed
            remaining -= consumed
        if remaining:
            file_offset = offset - len(self.prefix)
            self._handle.seek(file_offset)
            file_chunk = self._handle.read(remaining)
            if len(file_chunk) != remaining:
                raise OSError("selected file ended while preparing ColorGrid8 frame")
            chunks.append(file_chunk)
        return b"".join(chunks)

    def close(self) -> None:
        self._handle.close()


def bytes_to_symbols(data: bytes) -> np.ndarray:
    if not data:
        return np.empty(0, dtype=np.uint8)
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")
    remainder = bits.size % 3
    if remainder:
        bits = np.pad(bits, (0, 3 - remainder))
    triples = bits.reshape((-1, 3))
    return ((triples[:, 0] << 2) | (triples[:, 1] << 1) | triples[:, 2]).astype(
        np.uint8,
        copy=False,
    )


def symbols_to_bytes(symbols: np.ndarray) -> bytes:
    accumulator = 0
    bit_count = 0
    output = bytearray()
    for raw_symbol in np.asarray(symbols, dtype=np.uint8).reshape(-1):
        symbol = int(raw_symbol)
        if symbol > 7:
            raise ValueError("ColorGrid8 symbols must be in [0, 7]")
        accumulator = (accumulator << 3) | symbol
        bit_count += 3
        while bit_count >= 8:
            bit_count -= 8
            output.append((accumulator >> bit_count) & 0xFF)
            accumulator = accumulator & ((1 << bit_count) - 1) if bit_count else 0
    return bytes(output)


def encode_transport_frame(
    profile: ColorGrid8Profile,
    *,
    kind: int,
    session_id: int,
    frame_id: int,
    total_data_frames: int,
    payload: bytes,
) -> bytes:
    if profile.version != TRANSFER_HEADER_VERSION:
        raise ValueError("transport frames require ColorGrid8 v2")
    if kind not in (KIND_DATA, KIND_XOR_PARITY):
        raise ValueError("invalid ColorGrid8 transport kind")
    chunk_capacity = logical_chunk_capacity(profile)
    if not 0 < len(payload) <= chunk_capacity:
        raise ValueError("invalid ColorGrid8 transport payload length")
    if kind == KIND_XOR_PARITY and (len(payload) != chunk_capacity or frame_id % XOR_GROUP_SIZE):
        raise ValueError("invalid ColorGrid8 XOR parity frame")
    if not 0 < session_id <= 0xFFFFFFFF or not 0 <= frame_id < total_data_frames <= MAX_DATA_FRAMES:
        raise ValueError("invalid ColorGrid8 frame numbering")
    prefix = TRANSPORT_HEADER.pack(
        TRANSPORT_MAGIC,
        TRANSPORT_VERSION,
        kind,
        profile.profile_id,
        XOR_GROUP_SIZE,
        session_id,
        frame_id,
        total_data_frames,
        len(payload),
        chunk_capacity,
        0,
    )
    header_crc = zlib.crc32(prefix[:-4]) & 0xFFFFFFFF
    encoded = bytearray()
    for offset in range(0, len(payload), BLOCK_DATA_BYTES):
        block = payload[offset:offset + BLOCK_DATA_BYTES]
        encoded += block
        encoded += struct.pack(">I", zlib.crc32(block) & 0xFFFFFFFF)
    return prefix[:-4] + struct.pack(">I", header_crc) + encoded


def parse_transport_frame(profile: ColorGrid8Profile, raw: bytes) -> ColorGrid8TransportFrame | None:
    if profile.version != TRANSFER_HEADER_VERSION or len(raw) < TRANSPORT_HEADER_SIZE:
        return None
    values = TRANSPORT_HEADER.unpack_from(raw)
    magic, version, kind, profile_id, group_size = values[:5]
    session_id, frame_id, total_data_frames, payload_length, chunk_capacity, declared_crc = values[5:]
    expected_capacity = logical_chunk_capacity(profile)
    if (
        magic != TRANSPORT_MAGIC
        or version != TRANSPORT_VERSION
        or kind not in (KIND_DATA, KIND_XOR_PARITY)
        or profile_id != profile.profile_id
        or group_size != XOR_GROUP_SIZE
        or session_id == 0
        or not 0 <= frame_id < total_data_frames <= MAX_DATA_FRAMES
        or chunk_capacity != expected_capacity
        or not 0 < payload_length <= chunk_capacity
        or TRANSPORT_HEADER_SIZE + encoded_payload_size(payload_length) > len(raw)
        or (kind == KIND_XOR_PARITY and (payload_length != chunk_capacity or frame_id % XOR_GROUP_SIZE))
    ):
        return None
    if zlib.crc32(raw[:TRANSPORT_HEADER_SIZE - 4]) & 0xFFFFFFFF != declared_crc:
        return None
    payload = bytearray()
    cursor = TRANSPORT_HEADER_SIZE
    remaining = payload_length
    while remaining:
        block_length = min(BLOCK_DATA_BYTES, remaining)
        block = raw[cursor:cursor + block_length]
        cursor += block_length
        block_crc = struct.unpack_from(">I", raw, cursor)[0]
        cursor += BLOCK_CRC_BYTES
        if zlib.crc32(block) & 0xFFFFFFFF != block_crc:
            return None
        payload += block
        remaining -= block_length
    return ColorGrid8TransportFrame(
        kind,
        profile_id,
        session_id,
        frame_id,
        total_data_frames,
        chunk_capacity,
        bytes(payload),
    )


class ColorGrid8TransferSession:
    """Prepare a repeated 8-data + 1-XOR-parity optical carousel."""

    def __init__(self, path: Path, profile: ColorGrid8Profile):
        if profile.version != TRANSFER_HEADER_VERSION:
            raise ValueError("file transport requires a ColorGrid8 v2 profile")
        self.profile = profile
        self.source = _PackageSource(path.resolve())
        self.chunk_bytes = logical_chunk_capacity(profile)
        if self.chunk_bytes <= 0:
            self.source.close()
            raise ValueError("ColorGrid8 profile is too small for the transfer header")
        self.total_data_frames = max(
            1,
            (self.source.package_size + self.chunk_bytes - 1) // self.chunk_bytes,
        )
        if self.total_data_frames > MAX_DATA_FRAMES:
            self.source.close()
            raise ValueError("file needs too many ColorGrid8 data frames")
        self.group_count = (self.total_data_frames + XOR_GROUP_SIZE - 1) // XOR_GROUP_SIZE
        self.carousel_frames = self.total_data_frames + self.group_count
        self.session_id = int.from_bytes(os.urandom(4), "big") or 1
        # Unused optical cells must not turn a short file into a mostly-green
        # calibration scene. Padding is outside the CRC-declared transport and
        # is ignored by receivers. One profile-sized template bounds memory.
        self._padding_symbols = np.random.default_rng(profile.seed).integers(
            0, 8, size=profile.payload_cells, dtype=np.uint8,
        )

        channel_kib_s = self.chunk_bytes * profile.fps / 1024.0
        protected_kib_s = channel_kib_s * XOR_GROUP_SIZE / (XOR_GROUP_SIZE + 1)
        self.info = ColorGrid8TransferInfo(
            filename=path.name,
            mime_type=self.source.mime_type,
            file_size=self.source.file_size,
            file_crc32=self.source.file_crc32,
            session_id=self.session_id,
            total_data_frames=self.total_data_frames,
            chunk_bytes=self.chunk_bytes,
            carousel_frames=self.carousel_frames,
            channel_kib_s=channel_kib_s,
            protected_kib_s=protected_kib_s,
        )

    def _schedule_item(self, logical_index: int) -> tuple[int, int]:
        position = logical_index % self.carousel_frames
        full_groups = self.total_data_frames // XOR_GROUP_SIZE
        full_span = full_groups * (XOR_GROUP_SIZE + 1)
        if position < full_span:
            group = position // (XOR_GROUP_SIZE + 1)
            within = position % (XOR_GROUP_SIZE + 1)
            if within < XOR_GROUP_SIZE:
                return KIND_DATA, group * XOR_GROUP_SIZE + within
            return KIND_XOR_PARITY, group * XOR_GROUP_SIZE

        group_start = full_groups * XOR_GROUP_SIZE
        within = position - full_span
        remaining = self.total_data_frames - group_start
        if within < remaining:
            return KIND_DATA, group_start + within
        return KIND_XOR_PARITY, group_start

    def _data_payload(self, frame_id: int) -> bytes:
        return self.source.read_slice(frame_id * self.chunk_bytes, self.chunk_bytes)

    def _parity_payload(self, group_start: int) -> bytes:
        parity = np.zeros(self.chunk_bytes, dtype=np.uint8)
        for frame_id in range(group_start, min(group_start + XOR_GROUP_SIZE, self.total_data_frames)):
            chunk = self._data_payload(frame_id)
            parity[: len(chunk)] ^= np.frombuffer(chunk, dtype=np.uint8)
        return parity.tobytes()

    def _transport_bytes(self, kind: int, frame_id: int) -> bytes:
        payload = self._data_payload(frame_id) if kind == KIND_DATA else self._parity_payload(frame_id)
        return encode_transport_frame(
            self.profile,
            kind=kind,
            session_id=self.session_id,
            frame_id=frame_id,
            total_data_frames=self.total_data_frames,
            payload=payload,
        )

    def symbol_frame(self, logical_index: int) -> np.ndarray:
        kind, frame_id = self._schedule_item(logical_index)
        transport = self._transport_bytes(kind, frame_id)
        symbols = bytes_to_symbols(transport)
        if symbols.size < self.profile.payload_cells:
            padded = self._padding_symbols.copy()
            padded[: symbols.size] = symbols
            symbols = padded
        return build_payload_symbol_frame(
            self.profile,
            logical_index & 0xFFFF,
            symbols,
        )

    def close(self) -> None:
        self.source.close()

    def __enter__(self) -> ColorGrid8TransferSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
