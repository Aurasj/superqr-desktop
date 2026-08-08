"""SuperQR V7 adaptive optical transport.

The wire header is stable across profiles. Byte 3 carries the optical profile id.
Frame size is derived from grid density and bits per cell; package semantics stay
identical across profiles.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

from superqr_desktop.v7.profiles import OpticalProfile, get_profile, BY_ID

MAGIC = b"SQ"
VERSION = 0x07
HEADER_SIZE = 16
CRC_SIZE = 4
PACKAGE_MAGIC = b"SQP7"
PACKAGE_HEADER_SIZE = 20
MAX_FILENAME_BYTES = 1024
MAX_MIME_BYTES = 255

# Backward-compatible baseline constants (profile 0).
_BASELINE = get_profile(0)
GRID_SIZE = _BASELINE.grid
BITS_PER_CELL = _BASELINE.bits_per_cell
CELL_COUNT = _BASELINE.cell_count
FRAME_SIZE = _BASELINE.frame_size
PAYLOAD_SIZE = _BASELINE.payload_size
FLAGS = 0


class V7TransportError(Exception):
    pass


@dataclass(frozen=True)
class V7Frame:
    session_id: int
    frame_id: int
    total_frames: int
    payload: bytes
    profile_id: int = 0


@dataclass(frozen=True)
class V7Package:
    filename: str
    mime_type: str
    file_size: int
    file_crc32: int
    file_data: bytes


def bytes_to_symbols(data: bytes, profile: OpticalProfile | int | str = 0) -> list[int]:
    p = get_profile(profile)
    if len(data) != p.frame_size:
        raise ValueError(f"frame must be exactly {p.frame_size} bytes for {p.key}")
    bits = p.bits_per_cell
    mask = (1 << bits) - 1
    out = [0] * p.cell_count
    bit_pos = 0
    for i in range(p.cell_count):
        value = 0
        for _ in range(bits):
            byte_idx = bit_pos >> 3
            shift = 7 - (bit_pos & 7)
            value = (value << 1) | ((data[byte_idx] >> shift) & 1)
            bit_pos += 1
        out[i] = value & mask
    return out


def symbols_to_bytes(symbols: list[int], profile: OpticalProfile | int | str = 0) -> bytes:
    p = get_profile(profile)
    if len(symbols) != p.cell_count:
        raise ValueError(f"expected {p.cell_count} symbols for {p.key}")
    bits = p.bits_per_cell
    max_symbol = (1 << bits) - 1
    out = bytearray(p.frame_size)
    bit_pos = 0
    for symbol in symbols:
        if not 0 <= symbol <= max_symbol:
            raise ValueError(f"symbol outside 0..{max_symbol}")
        for shift_in_symbol in range(bits - 1, -1, -1):
            if (symbol >> shift_in_symbol) & 1:
                byte_idx = bit_pos >> 3
                shift = 7 - (bit_pos & 7)
                out[byte_idx] |= 1 << shift
            bit_pos += 1
    return bytes(out)


def build_frame(
    session_id: int,
    frame_id: int,
    total_frames: int,
    payload: bytes,
    profile: OpticalProfile | int | str = 0,
) -> bytes:
    p = get_profile(profile)
    if not (1 <= session_id <= 0xFFFF):
        raise ValueError("session_id must be 1..65535")
    if not (1 <= total_frames <= 0xFFFFFFFF):
        raise ValueError("total_frames must be 1..2^32-1")
    if not (0 <= frame_id < total_frames):
        raise ValueError("frame_id out of range")
    if len(payload) > p.payload_size:
        raise ValueError(f"payload exceeds {p.payload_size} bytes for {p.key}")

    header = (
        MAGIC
        + bytes((VERSION, p.id))
        + struct.pack(">HIIH", session_id, frame_id, total_frames, len(payload))
    )
    padded = payload + (b"\x00" * (p.payload_size - len(payload)))
    body = header + padded
    crc = zlib.crc32(body) & 0xFFFFFFFF
    frame = body + struct.pack(">I", crc)
    if len(frame) != p.frame_size:
        raise AssertionError("internal V7 frame size error")
    return frame


def parse_frame(frame_data: bytes, profile: OpticalProfile | int | str | None = None) -> V7Frame:
    if len(frame_data) < HEADER_SIZE + CRC_SIZE:
        raise V7TransportError("truncated V7 frame")
    if frame_data[:2] != MAGIC:
        raise V7TransportError("invalid V7 frame magic")
    if frame_data[2] != VERSION:
        raise V7TransportError("invalid V7 version")
    profile_id = frame_data[3]
    if profile_id not in BY_ID:
        raise V7TransportError(f"unknown V7 profile id {profile_id}")
    p = BY_ID[profile_id]
    if profile is not None and get_profile(profile).id != profile_id:
        raise V7TransportError("optical profile does not match frame header")
    if len(frame_data) != p.frame_size:
        raise V7TransportError(f"frame must be exactly {p.frame_size} bytes for {p.key}")

    expected_crc = struct.unpack(">I", frame_data[-4:])[0]
    actual_crc = zlib.crc32(frame_data[:-4]) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise V7TransportError("frame CRC32 mismatch")

    session_id, frame_id, total_frames, payload_len = struct.unpack(">HIIH", frame_data[4:16])
    if session_id == 0:
        raise V7TransportError("session_id 0 is invalid")
    if total_frames < 1 or frame_id >= total_frames:
        raise V7TransportError("invalid frame numbering")
    if payload_len > p.payload_size:
        raise V7TransportError("invalid payload length")

    return V7Frame(
        session_id=session_id,
        frame_id=frame_id,
        total_frames=total_frames,
        payload=frame_data[HEADER_SIZE:HEADER_SIZE + payload_len],
        profile_id=profile_id,
    )


def build_package_prefix(filename: str, mime_type: str, file_size: int, file_crc32: int) -> bytes:
    filename_bytes = filename.encode("utf-8")
    mime_bytes = mime_type.encode("utf-8")
    if not (1 <= len(filename_bytes) <= MAX_FILENAME_BYTES):
        raise ValueError(f"filename must be 1..{MAX_FILENAME_BYTES} UTF-8 bytes")
    if len(mime_bytes) > MAX_MIME_BYTES:
        raise ValueError(f"mime type exceeds {MAX_MIME_BYTES} UTF-8 bytes")
    if file_size < 0:
        raise ValueError("file_size must be non-negative")
    return (
        PACKAGE_MAGIC
        + struct.pack(">HHQI", len(filename_bytes), len(mime_bytes), file_size, file_crc32 & 0xFFFFFFFF)
        + filename_bytes
        + mime_bytes
    )


def build_package(filename: str, mime_type: str, file_data: bytes) -> bytes:
    crc = zlib.crc32(file_data) & 0xFFFFFFFF
    return build_package_prefix(filename, mime_type, len(file_data), crc) + file_data


def parse_package(package_data: bytes) -> V7Package:
    if len(package_data) < PACKAGE_HEADER_SIZE:
        raise V7TransportError("truncated V7 package")
    if package_data[:4] != PACKAGE_MAGIC:
        raise V7TransportError("invalid V7 package magic")
    filename_len, mime_len, file_size, expected_crc = struct.unpack(">HHQI", package_data[4:20])
    if filename_len < 1 or filename_len > MAX_FILENAME_BYTES:
        raise V7TransportError("invalid filename length")
    if mime_len > MAX_MIME_BYTES:
        raise V7TransportError("invalid mime length")
    meta_end = PACKAGE_HEADER_SIZE + filename_len + mime_len
    expected_total = meta_end + file_size
    if len(package_data) != expected_total:
        raise V7TransportError("package length does not match declared file size")
    try:
        filename = package_data[20:20 + filename_len].decode("utf-8")
        mime_type = package_data[20 + filename_len:meta_end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise V7TransportError("invalid UTF-8 metadata") from exc
    file_data = package_data[meta_end:]
    actual_crc = zlib.crc32(file_data) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise V7TransportError(f"file CRC32 mismatch: expected {expected_crc:08X}, got {actual_crc:08X}")
    return V7Package(filename, mime_type, file_size, expected_crc, file_data)
