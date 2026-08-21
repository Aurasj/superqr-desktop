from __future__ import annotations

import math

from superqr_desktop.presentation.transfer import PreparedQrFrame, _QrFrameProducer
from superqr_desktop.transfer.controller import TransferController
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


def test_all_production_modes_reframe_file_and_set_expected_cadence(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(bytes(range(251)) * 80)
    controller = TransferController()
    try:
        controller.select_file(str(path))
        expected = {
            "Best tested — V40-L · 15 FPS": ("v40_l_15fps", "L", 2953, 15.0),
            "Faster — V40-L · 20 FPS": ("v40_l_20fps", "L", 2953, 20.0),
            "30 FPS test — V40-L · 30 FPS": ("v40_l_30fps", "L", 2953, 30.0),
            "Extra ECC — V40-M · 15 FPS": ("v40_m_15fps", "M", 2331, 15.0),
            "Extra ECC faster — V40-M · 20 FPS": ("v40_m_20fps", "M", 2331, 20.0),
            "30 FPS ECC test — V40-M · 30 FPS": ("v40_m_30fps", "M", 2331, 30.0),
        }
        for mode, (key, ecc, frame_size, fps) in expected.items():
            controller.set_mode(mode)
            assert controller.mode == mode
            assert controller.profile.key == key
            assert controller.profile.qr_version == 40
            assert controller.profile.qr_ecc == ecc
            assert controller.profile.frame_size == frame_size
            assert math.isclose(controller.target_fps, fps)
            assert math.isclose(controller.interval_ms, 1000.0 / fps)
            raw = controller.get_frame_bytes(0)
            assert len(raw) == frame_size
            parsed = parse_frame(raw, controller.profile)
            assert parsed.profile_id == controller.profile.id
    finally:
        controller.close()


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


def test_prepared_qr_cache_reuses_first_pass_work_when_carousel_fits_budget():
    provider_calls: list[int] = []
    prepare_calls: list[tuple[int, int]] = []

    def provider(frame_id: int) -> bytes:
        provider_calls.append(frame_id)
        return bytes([frame_id])

    producer = _QrFrameProducer(
        frame_provider=provider,
        total_frames=2,
        session_id=7,
        profile=DEFAULT_PROFILE,
        queue_size=1,
        cache_budget_bytes=1024 * 1024,
    )
    assert producer.cache_enabled

    def fake_prepare(frame_id: int, loop_index: int, _raw: bytes) -> PreparedQrFrame:
        prepare_calls.append((frame_id, loop_index))
        return PreparedQrFrame(frame_id, loop_index, 185, bytes([frame_id + 1]) * 8)

    producer._prepare = fake_prepare  # type: ignore[method-assign]
    first = producer._prepared_for(1, 0)
    later = producer._prepared_for(1, 4)

    assert provider_calls == [1]
    assert prepare_calls == [(1, 0)]
    assert first.rgb is later.rgb
    assert later.frame_id == 1
    assert later.loop_index == 4


def test_prepared_qr_cache_stays_disabled_when_full_working_set_exceeds_budget():
    producer = _QrFrameProducer(
        frame_provider=lambda _idx: b"",
        total_frames=256,
        session_id=7,
        profile=DEFAULT_PROFILE,
        queue_size=1,
        cache_budget_bytes=1,
    )
    assert not producer.cache_enabled


def test_selected_mode_has_expected_nominal_payload_rate():
    expected = DEFAULT_PROFILE.payload_size * 15.0 / 1024.0
    assert DEFAULT_PROFILE.payload_size == 2933
    assert math.isclose(expected, 42.9638671875, rel_tol=0.0, abs_tol=1e-12)
