from __future__ import annotations

import numpy as np

from superqr_desktop.lab.colorgrid8_core import (
    TRANSFER_HEADER_VERSION,
    ColorGrid8Profile,
    build_payload_symbol_frame,
    is_pilot,
)
from superqr_desktop.lab.colorgrid8_transfer import (
    KIND_DATA,
    KIND_XOR_PARITY,
    ColorGrid8TransferSession,
    bytes_to_symbols,
    encode_transport_frame,
    parse_transport_frame,
    symbols_to_bytes,
)


def transfer_profile() -> ColorGrid8Profile:
    return ColorGrid8Profile(336, 288, 60, version=TRANSFER_HEADER_VERSION)


def payload_symbols(profile: ColorGrid8Profile, matrix: np.ndarray) -> np.ndarray:
    return np.asarray(
        [
            matrix[row, col]
            for row in range(2, profile.rows)
            for col in range(profile.cols)
            if not is_pilot(profile, row, col)
        ],
        dtype=np.uint8,
    )


def test_balanced_profile_has_bounded_xor_channel_budget() -> None:
    profile = transfer_profile()
    assert profile.byte_capacity == 34_594
    assert profile.byte_capacity - 32 == 34_562
    session_payload_bytes = 34_294
    assert session_payload_bytes * 60 * 8 / 9 / 1024 > 1_780


def test_transport_crc_rejects_a_recomputed_symbol_stream_corruption() -> None:
    profile = transfer_profile()
    raw = encode_transport_frame(
        profile,
        kind=KIND_DATA,
        session_id=0x12345678,
        frame_id=0,
        total_data_frames=1,
        payload=b"hello ColorGrid8",
    )
    decoded = parse_transport_frame(profile, symbols_to_bytes(bytes_to_symbols(raw)))
    assert decoded is not None and decoded.payload == b"hello ColorGrid8"
    corrupt = bytearray(raw)
    corrupt[-1] ^= 1
    assert parse_transport_frame(profile, bytes(corrupt)) is None


def test_file_session_emits_data_then_full_xor_parity(tmp_path) -> None:
    selected = tmp_path / "sample.bin"
    selected.write_bytes(bytes(range(251)) * 16)
    profile = transfer_profile()
    session = ColorGrid8TransferSession(selected, profile)
    try:
        data_raw = symbols_to_bytes(payload_symbols(profile, session.symbol_frame(0)))
        data = parse_transport_frame(profile, data_raw)
        assert data is not None
        assert data.kind == KIND_DATA
        assert data.payload.startswith(b"SQP7")

        parity_raw = symbols_to_bytes(payload_symbols(profile, session.symbol_frame(1)))
        parity = parse_transport_frame(profile, parity_raw)
        assert parity is not None
        assert parity.kind == KIND_XOR_PARITY
        assert len(parity.payload) == session.chunk_bytes
    finally:
        session.close()


def test_short_file_padding_is_balanced_without_changing_transport(tmp_path) -> None:
    selected = tmp_path / "small.bin"
    selected.write_bytes(b"small optical baseline")
    profile = ColorGrid8Profile(240, 216, 30, version=TRANSFER_HEADER_VERSION)
    with ColorGrid8TransferSession(selected, profile) as session:
        raw = session._transport_bytes(KIND_DATA, 0)
        encoded = bytes_to_symbols(raw)
        matrix = session.symbol_frame(0)
        cells = payload_symbols(profile, matrix)
        np.testing.assert_array_equal(cells[:encoded.size], encoded)
        decoded = symbols_to_bytes(cells)
        assert decoded[:len(raw)] == raw
        assert parse_transport_frame(profile, decoded) == parse_transport_frame(profile, raw)
        counts = np.bincount(cells[encoded.size:], minlength=8)
        assert counts.min() > counts.sum() * 0.10
        assert counts.max() < counts.sum() * 0.15
        assert session._padding_symbols.nbytes == profile.payload_cells
        legacy = build_payload_symbol_frame(profile, 0, encoded)
        np.testing.assert_array_equal(matrix[:2], legacy[:2])
        for row in range(2, profile.rows):
            for col in range(profile.cols):
                if is_pilot(profile, row, col):
                    assert matrix[row, col] == legacy[row, col]
