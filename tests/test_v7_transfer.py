import hashlib
import os
import struct
import zlib

from superqr_desktop.v7.sender import V7SenderSession
from superqr_desktop.v7.transport import (
    CELL_COUNT,
    FRAME_SIZE,
    GRID_SIZE,
    PAYLOAD_SIZE,
    V7TransportError,
    build_frame,
    build_package,
    bytes_to_symbols,
    parse_frame,
    parse_package,
    symbols_to_bytes,
)


def test_golden_frame_matches_shared_contract():
    frame = build_frame(1, 0, 1, b"abc")
    assert len(frame) == 400
    assert struct.unpack(">I", frame[-4:])[0] == 0x9BAFCBAB
    assert hashlib.sha256(frame).hexdigest() == "8048032cd8f495c68903fbe05c9ae032e0965a7d7faab3dac279ff2f112d4025"


def test_400_bytes_map_exactly_to_40x40_symbols():
    frame = bytes((i * 37) & 0xFF for i in range(FRAME_SIZE))
    symbols = bytes_to_symbols(frame)
    assert GRID_SIZE == 40
    assert len(symbols) == CELL_COUNT == 1600
    assert symbols_to_bytes(symbols) == frame


def test_frame_crc_detects_corruption():
    frame = bytearray(build_frame(7, 0, 1, b"hello"))
    frame[100] ^= 1
    try:
        parse_frame(bytes(frame))
        assert False, "corruption must fail CRC32"
    except V7TransportError:
        pass


def test_package_round_trip_preserves_metadata_and_binary_payload():
    data = bytes(range(256)) * 4
    package = build_package("photo.bin", "application/octet-stream", data)
    parsed = parse_package(package)
    assert parsed.filename == "photo.bin"
    assert parsed.mime_type == "application/octet-stream"
    assert parsed.file_data == data
    assert parsed.file_crc32 == (zlib.crc32(data) & 0xFFFFFFFF)


def test_streaming_sender_reconstructs_exact_package(tmp_path):
    data = (b"SuperQR-V7-" * 1000) + bytes(range(251))
    path = tmp_path / "sample.bin"
    path.write_bytes(data)

    sender = V7SenderSession()
    sender.prepare_transfer(str(path))
    assert sender.interval_ms == 67
    assert sender.total_frames >= 1
    assert sender.package_size == len(sender.package_prefix) + len(data)

    payloads = []
    for frame_id in range(sender.total_frames):
        parsed = parse_frame(sender.get_frame_bytes(frame_id))
        assert parsed.frame_id == frame_id
        assert parsed.total_frames == sender.total_frames
        payloads.append(parsed.payload)

    package = parse_package(b"".join(payloads))
    assert package.filename == "sample.bin"
    assert package.file_data == data


def test_sender_matrix_matches_current_transport_frame(tmp_path):
    path = tmp_path / "tiny.txt"
    path.write_bytes(b"hello optical world")
    sender = V7SenderSession()
    sender.prepare_transfer(str(path))

    matrix = sender.get_current_matrix()
    assert matrix.rows == 40
    assert matrix.cols == 40
    flat = [s for row in matrix.symbols for s in row]
    assert symbols_to_bytes(flat) == sender.get_frame_bytes(0)


def test_sender_does_not_precompute_frame_carousel(tmp_path):
    path = tmp_path / "largeish.bin"
    path.write_bytes(os.urandom(PAYLOAD_SIZE * 20 + 17))
    sender = V7SenderSession()
    sender.prepare_transfer(str(path))
    assert not hasattr(sender, "frames")
    assert sender.total_frames > 20
