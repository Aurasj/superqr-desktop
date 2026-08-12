from __future__ import annotations

import segno

from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    CHROMA_QR_MAGIC,
    CHROMA_QR_MODULE_COUNT,
    CHROMA_QR_NAME,
    build_qr_control_payload,
    build_qr_matrix,
    chromaqr_seed,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.run_sync import RunState


def test_chromaqr_overlay_preserves_binary_qr_and_adds_color_bit():
    chroma = qr_controls()[CHROMA_QR_NAME]
    kwargs = dict(run_token=1234, state=RunState.RUNNING, frame_count=256, dwell_epochs=3.0)
    payload = build_qr_control_payload(chroma, 17, **kwargs)
    raw_qr = segno.make_qr(
        payload,
        version=int(chroma["version"]),
        error=chroma["error_correction"],
        mask=int(chroma["mask_pattern"]),
        mode="byte",
        boost_error=False,
    )
    base_matrix = tuple(bytes(row) for row in raw_qr.matrix)
    color_matrix = build_qr_matrix(chroma, 17, **kwargs)

    assert len(color_matrix) == CHROMA_QR_MODULE_COUNT
    symbols = {value for row in color_matrix for value in row}
    assert symbols == {0, 1, 2, 3}

    for base_row, color_row in zip(base_matrix, color_matrix):
        for base_value, color_value in zip(base_row, color_row):
            # 1/3 are dark; 0/2 are light. Chroma does not alter the QR bit.
            assert bool(base_value) == (color_value in (1, 3))


def test_chromaqr_payload_self_identifies_and_is_deterministic():
    control = qr_controls()[CHROMA_QR_NAME]
    payload = build_qr_control_payload(
        control,
        9,
        run_token=4321,
        state=RunState.RUNNING,
        frame_count=256,
        dwell_epochs=2.5,
    )
    assert payload[26:30] == CHROMA_QR_MAGIC
    assert payload[30] == 1
    assert payload[31] == 1
    assert int.from_bytes(payload[32:34], "little") == CHROMA_QR_MODULE_COUNT
    assert payload[34] == 24
    assert chromaqr_seed(9) == chromaqr_seed(9)
    assert chromaqr_seed(9) != chromaqr_seed(10)


def test_ready_frame_remains_plain_black_white_for_easy_acquisition():
    control = qr_controls()[CHROMA_QR_NAME]
    matrix = build_qr_matrix(
        control,
        0,
        run_token=1,
        state=RunState.READY,
        frame_count=256,
        dwell_epochs=4.0,
    )
    assert {value for row in matrix for value in row} <= {0, 1}
