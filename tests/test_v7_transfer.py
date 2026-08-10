import hashlib
import os
import struct
import zlib

from superqr_desktop.v7.profiles import PROFILES, get_profile
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
    frame = build_frame(1, 0, 1, b"abc", 0)
    assert len(frame) == 400
    assert struct.unpack(">I", frame[-4:])[0] == 0x9BAFCBAB
    assert hashlib.sha256(frame).hexdigest() == "8048032cd8f495c68903fbe05c9ae032e0965a7d7faab3dac279ff2f112d4025"


def test_baseline_400_bytes_map_exactly_to_40x40_symbols():
    frame = bytes((i * 37) & 0xFF for i in range(FRAME_SIZE))
    symbols = bytes_to_symbols(frame, 0)
    assert GRID_SIZE == 40
    assert len(symbols) == CELL_COUNT == 1600
    assert symbols_to_bytes(symbols, 0) == frame


def test_every_profile_symbol_pack_round_trip():
    for profile in PROFILES:
        data = bytes((i * 29 + profile.id) & 0xFF for i in range(profile.frame_size))
        symbols = bytes_to_symbols(data, profile)
        assert len(symbols) == profile.cell_count
        assert symbols_to_bytes(symbols, profile) == data


def test_frame_crc_detects_corruption():
    frame = bytearray(build_frame(7, 0, 1, b"hello", 0))
    frame[100] ^= 1
    try:
        parse_frame(bytes(frame))
        assert False, "corruption must fail CRC32"
    except V7TransportError:
        pass


def test_profile_id_is_carried_in_wire_header():
    p = get_profile("color_48_8")
    frame = build_frame(4, 0, 1, b"hello", p)
    assert frame[3] == p.id
    parsed = parse_frame(frame, p)
    assert parsed.profile_id == p.id


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
    assert sender.interval_ms == 100
    assert sender.transfer_state == "READY"
    assert sender.total_frames >= 1
    payloads = []
    for frame_id in range(sender.total_frames):
        parsed = parse_frame(sender.get_frame_bytes(frame_id), sender.profile)
        assert parsed.frame_id == frame_id
        assert parsed.profile_id == sender.profile.id
        payloads.append(parsed.payload)
    package = parse_package(b"".join(payloads))
    assert package.filename == "sample.bin"
    assert package.file_data == data


def test_prepare_start_stop_restart_lifecycle(tmp_path):
    path = tmp_path / "tiny.bin"
    path.write_bytes(b"lifecycle")
    sender = V7SenderSession()

    sender.prepare_transfer(str(path))
    assert sender.transfer_state == "READY"
    assert sender.current_frame_idx == 0

    assert sender.start_transfer() is True
    assert sender.transfer_state == "SENDING"
    sender.advance_frame()
    sender.stop_transfer()
    assert sender.transfer_state == "STOPPED"

    assert sender.start_transfer() is True
    assert sender.transfer_state == "SENDING"
    assert sender.current_frame_idx == 0


def test_sender_matrix_matches_selected_profile(tmp_path):
    path = tmp_path / "tiny.txt"
    path.write_bytes(b"hello optical world")
    sender = V7SenderSession()
    sender.set_profile("fast_56_4")
    sender.prepare_transfer(str(path))
    matrix = sender.get_current_matrix()
    assert matrix.rows == sender.profile.grid == 56
    assert matrix.cols == 56
    flat = [s for row in matrix.symbols for s in row]
    assert symbols_to_bytes(flat, sender.profile) == sender.get_frame_bytes(0)


def test_sender_does_not_precompute_frame_carousel(tmp_path):
    path = tmp_path / "largeish.bin"
    sender = V7SenderSession()
    sender.set_profile(0)
    path.write_bytes(os.urandom(PAYLOAD_SIZE * 20 + 17))
    sender.prepare_transfer(str(path))
    assert not hasattr(sender, "frames")
    assert sender.total_frames > 20


def test_switching_profile_recomputes_transfer_geometry(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(os.urandom(5000))
    sender = V7SenderSession()
    sender.set_profile(0)
    sender.prepare_transfer(str(path))
    safe_frames = sender.total_frames
    sender.set_profile("turbo_64_4")
    assert sender.total_frames < safe_frames
    assert sender.profile.grid == 64
    assert sender.transfer_state == "READY"
