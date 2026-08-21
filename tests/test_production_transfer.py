from __future__ import annotations

import hashlib
from importlib import resources
import json
import math

import numpy as np
import zxingcpp

from superqr_desktop.presentation.transfer import PREPARED_QR_CACHE_BUDGET_BYTES, _QrFrameProducer
from superqr_desktop.receive.accumulator import ProductionQrAccumulator
from superqr_desktop.transfer.controller import TransferController
from superqr_desktop.v7.profiles import DEFAULT_PROFILE
from superqr_desktop.v7.sender import V7SenderSession
from superqr_desktop.v7.transport import parse_frame, parse_package


def test_canonical_production_qr_golden_vector():
    vectors = json.loads(
        resources.files("superqr_desktop.contract")
        .joinpath("v7_production_qr_vectors.json")
        .read_text(encoding="utf-8")
    )
    vector = vectors["frame_vector"]
    from superqr_desktop.v7.transport import build_frame

    frame = build_frame(
        vector["session_id"],
        vector["frame_id"],
        vector["total_frames"],
        bytes.fromhex(vector["payload_hex"]),
        vector["profile_id"],
    )
    assert hashlib.sha256(frame).hexdigest().upper() == vector["frame_sha256"]


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
            "Auto / safe — V40-L · 15 FPS": ("v40_l_15fps", "L", 2953, 15.0),
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


def test_prepared_qr_cache_reuses_frames_when_complete_working_set_fits():
    producer = _QrFrameProducer(
        frame_provider=lambda _idx: b"frame",
        total_frames=2,
        session_id=7,
        profile=DEFAULT_PROFILE,
        queue_size=1,
    )
    calls = 0

    def encode(_frame_bytes):
        nonlocal calls
        calls += 1
        return 185, b"prepared"

    producer._encode_rgb = encode
    first = producer._prepare(0, 0, b"frame")
    repeated = producer._prepare(0, 1, b"frame")

    assert producer.cache_enabled
    assert calls == 1
    assert first.rgb is repeated.rgb
    assert repeated.loop_index == 1


def test_prepared_qr_cache_is_disabled_when_working_set_exceeds_budget():
    total_modules = DEFAULT_PROFILE.qr_version * 4 + 17 + 8
    estimated_entry_bytes = total_modules * total_modules * 3 + 256
    total_frames = PREPARED_QR_CACHE_BUDGET_BYTES // estimated_entry_bytes + 1
    producer = _QrFrameProducer(
        frame_provider=lambda _idx: b"frame",
        total_frames=total_frames,
        session_id=7,
        profile=DEFAULT_PROFILE,
        queue_size=1,
    )
    calls = 0

    def encode(_frame_bytes):
        nonlocal calls
        calls += 1
        return 185, b"prepared"

    producer._encode_rgb = encode
    producer._prepare(0, 0, b"frame")
    producer._prepare(0, 1, b"frame")

    assert not producer.cache_enabled
    assert calls == 2


def test_every_production_profile_encodes_to_exact_decodable_qr(tmp_path):
    source_path = tmp_path / "wire.bin"
    source_path.write_bytes(bytes(range(251)) * 20)
    controller = TransferController()
    try:
        controller.select_file(str(source_path))
        for mode in controller.mode_options:
            controller.set_mode(mode)
            raw = controller.get_frame_bytes(0)
            producer = _QrFrameProducer(
                frame_provider=lambda _idx: raw,
                total_frames=1,
                session_id=controller.session_id or 1,
                profile=controller.profile,
                queue_size=1,
            )
            prepared = producer._prepare(0, 0, raw)
            image = np.frombuffer(prepared.rgb, dtype=np.uint8).reshape(
                prepared.total_modules, prepared.total_modules, 3
            )
            decoded = zxingcpp.read_barcode(image, formats=zxingcpp.QRCode, is_pure=True)
            assert decoded is not None
            assert decoded.bytes == raw
    finally:
        controller.close()


def test_selected_mode_has_expected_nominal_payload_rate():
    expected = DEFAULT_PROFILE.payload_size * 15.0 / 1024.0
    assert DEFAULT_PROFILE.payload_size == 2933
    assert math.isclose(expected, 42.9638671875, rel_tol=0.0, abs_tol=1e-12)


def test_disk_backed_receiver_recovers_interrupted_shuffled_carousel(tmp_path):
    source = bytes((index * 41 + 7) & 0xFF for index in range(1_750_321))
    source_path = tmp_path / "large payload.bin"
    source_path.write_bytes(source)
    sender = V7SenderSession()
    receiver = ProductionQrAccumulator(tmp_path)
    try:
        sender.prepare_transfer(str(source_path))
        order = list(range(sender.total_frames))
        first_attempt = order[::3]
        for frame_id in first_attempt:
            assert receiver.accept(sender.get_frame_bytes(frame_id))
        for frame_id in reversed(order):
            receiver.accept(sender.get_frame_bytes(frame_id))
        # A repeated carousel frame is ignored and accounted for.
        receiver.accept(sender.get_frame_bytes(0))

        artifact = receiver.artifact
        assert artifact is not None
        assert artifact.filename == source_path.name
        assert artifact.file_size == len(source)
        assert artifact.path.read_bytes() == source
        assert artifact.sha256 == hashlib.sha256(source).hexdigest()
        assert receiver.progress.unique_frames == sender.total_frames
        assert receiver.progress.duplicate_frames >= len(first_attempt) - 1
    finally:
        receiver.close()
        sender.close()


def test_receiver_sanitizes_wire_filename_and_requires_explicit_save(tmp_path):
    from superqr_desktop.v7.transport import build_frame, build_package

    source = b"preview before save\n" * 100
    package = build_package("../unsafe.txt", "text/plain", source)
    profile = DEFAULT_PROFILE
    chunks = [package[i:i + profile.payload_size] for i in range(0, len(package), profile.payload_size)]
    receiver = ProductionQrAccumulator(tmp_path)
    try:
        for frame_id, payload in enumerate(chunks):
            receiver.accept(build_frame(1234, frame_id, len(chunks), payload, profile))
        artifact = receiver.artifact
        assert artifact is not None
        assert artifact.filename == "unsafe.txt"
        destination = tmp_path / "saved" / artifact.filename
        assert not destination.exists()
        artifact.save_to(destination)
        assert destination.read_bytes() == source
    finally:
        receiver.close()
