"""SuperQR V7 baseline optical transport.

Canonical source of truth: superqr-protocol/contracts/v7_transport_contract.json

The baseline deliberately keeps the physically validated V6 carrier while
upgrading the payload to a 40x40, 4-colour grid (1600 symbols = 400 bytes).
Frames are independently CRC32 protected and can be collected in any order.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

MAGIC = b"SQ"
VERSION = 0x07
FLAGS = 0x00
GRID_SIZE = 40
BITS_PER_CELL = 2
CELL_COUNT = GRID_SIZE * GRID_SIZE
FRAME_SIZE = 400
HEADER_SIZE = 16
CRC_SIZE = 4
PAYLOAD_SIZE = FRAME_SIZE - HEADER_SIZE - CRC_SIZE  # 380

PACKAGE_MAGIC = b"SQP7"
PACKAGE_HEADER_SIZE = 20
MAX_FILENAME_BYTES = 1024
MAX_MIME_BYTES = 255


class V7TransportError(Exception):
    pass


@dataclass(frozen=True)
class V7Frame:
    session_id: int
    frame_id: int
    total_frames: int
    payload: bytes


@dataclass(frozen=True)
class V7Package:
    filename: str
    mime_type: str
    file_size: int
    file_crc32: int
    file_data: bytes


def bytes_to_symbols(data: bytes) -> list[int]:
    """Map exactly 400 bytes to 1600 row-major 2-bit palette symbols."""
    if len(data) != FRAME_SIZE:
        raise ValueError(f"frame must be exactly {FRAME_SIZE} bytes")
    out: list[int] = [0] * CELL_COUNT
    j = 0
    for b in data:
        out[j] = (b >> 6) & 0x03
        out[j + 1] = (b >> 4) & 0x03
        out[j + 2] = (b >> 2) & 0x03
        out[j + 3] = b & 0x03
        j += 4
    return out


def symbols_to_bytes(symbols: list[int]) -> bytes:
    if len(symbols) != CELL_COUNT:
        raise ValueError(f"expected {CELL_COUNT} symbols")
    out = bytearray(FRAME_SIZE)
    for i in range(FRAME_SIZE):
        j = i * 4
        a, b, c, d = symbols[j:j + 4]
        if not all(0 <= x <= 3 for x in (a, b, c, d)):
            raise ValueError("symbol outside 0..3")
        out[i] = (a << 6) | (b << 4) | (c << 2) | d
    return bytes(out)


def build_frame(session_id: int, frame_id: int, total_frames: int, payload: bytes) -> bytes:
    if not (1 <= session_id <= 0xFFFF):
        raise ValueError("session_id must be 1..65535")
    if not (1 <= total_frames <= 0xFFFFFFFF):
        raise ValueError("total_frames must be 1..2^32-1")
    if not (0 <= frame_id < total_frames):
        raise ValueError("frame_id out of range")
    if len(payload) > PAYLOAD_SIZE:
        raise ValueError(f"payload exceeds {PAYLOAD_SIZE} bytes")

    header = (
        MAGIC
        + bytes((VERSION, FLAGS))
        + struct.pack(">HIIH", session_id, frame_id, total_frames, len(payload))
    )
    padded = payload + (b"\x00" * (PAYLOAD_SIZE - len(payload)))
    body = header + padded
    crc = zlib.crc32(body) & 0xFFFFFFFF
    frame = body + struct.pack(">I", crc)
    if len(frame) != FRAME_SIZE:
        raise AssertionError("internal V7 frame size error")
    return frame


def parse_frame(frame_data: bytes) -> V7Frame:
    if len(frame_data) != FRAME_SIZE:
        raise V7TransportError(f"frame must be exactly {FRAME_SIZE} bytes")
    if frame_data[:2] != MAGIC:
        raise V7TransportError("invalid V7 frame magic")
    if frame_data[2] != VERSION:
        raise V7TransportError("invalid V7 version")
    if frame_data[3] != FLAGS:
        raise V7TransportError("unsupported V7 flags")

    expected_crc = struct.unpack(">I", frame_data[-4:])[0]
    actual_crc = zlib.crc32(frame_data[:-4]) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise V7TransportError("frame CRC32 mismatch")

    session_id, frame_id, total_frames, payload_len = struct.unpack(">HIIH", frame_data[4:16])
    if session_id == 0:
        raise V7TransportError("session_id 0 is invalid")
    if total_frames < 1 or frame_id >= total_frames:
        raise V7TransportError("invalid frame numbering")
    if payload_len > PAYLOAD_SIZE:
        raise V7TransportError("invalid payload length")

    return V7Frame(
        session_id=session_id,
        frame_id=frame_id,
        total_frames=total_frames,
        payload=frame_data[HEADER_SIZE:HEADER_SIZE + payload_len],
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
        raise V7TransportError(
            f"file CRC32 mismatch: expected {expected_crc:08X}, got {actual_crc:08X}"
        )

    return V7Package(filename, mime_type, file_size, expected_crc, file_data)
