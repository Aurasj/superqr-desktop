from __future__ import annotations

import math

from superqr_desktop.presentation.transfer import _QrFrameProducer
from superqr_desktop.v7.profiles import DEFAULT_PROFILE
from superqr_desktop.v7.sender import V7SenderSession
from superqr_desktop.v7.transport import parse_frame, parse_package


def test_v40_l_sender_round_trips_arbitrary_binary_file(tmp_path):
    source = bytes((index * 73 + 19) & 0xFF for index in range(19_321))
    path = tmp_path / "camera_clip.mp4"
    path.write_bytes(source)

    sender = V7SenderSession()
    try:
        sender.prepare_transfer(str(path))
        assert sender.profile.key == "v40_l_15fps"
        assert sender.profile.qr_version == 40
        assert sender.profile.qr_ecc == "L"
        assert sender.interval_ms == 1000.0 / 15.0

        payloads = []
        for frame_id in range(sender.total_frames):
            raw = sender.get_frame_bytes(frame_id)
            assert len(raw) == 2953
            frame = parse_frame(raw, sender.profile)
            assert frame.session_id == sender.session_id
            assert frame.frame_id == frame_id
            assert frame.total_frames == sender.total_frames
            payloads.append(frame.payload)

        package = parse_package(b"".join(payloads))
        assert package.filename == "camera_clip.mp4"
        assert package.mime_type == "video/mp4"
        assert package.file_data == source
    finally:
        sender.close()


def test_later_carousels_are_bijective_and_change_frame_phase():
    total = 256
    producer = _QrFrameProducer(
        frame_provider=lambda _idx: b"",
        total_frames=total,
        session_id=32123,
        profile=DEFAULT_PROFILE,
        queue_size=1,
    )

    first = [producer._frame_id(position, 0) for position in range(total)]
    second = [producer._frame_id(position, 1) for position in range(total)]
    third = [producer._frame_id(position, 2) for position in range(total)]

    assert first == list(range(total))
    assert sorted(second) == list(range(total))
    assert sorted(third) == list(range(total))
    assert second != first
    assert third != second


def test_selected_mode_has_expected_nominal_payload_rate():
    expected = DEFAULT_PROFILE.payload_size * 15.0 / 1024.0
    assert DEFAULT_PROFILE.payload_size == 2933
    assert math.isclose(expected, 42.9638671875, rel_tol=0.0, abs_tol=1e-12)
