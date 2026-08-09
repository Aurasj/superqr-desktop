from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from superqr_desktop.v7.modem import (
    build_modem_packet,
    coefficient_words,
    encode_fountain_symbol,
    inner_fec_encode,
    inner_fec_plan,
    plan_generations,
    symbol_payload_capacity,
)
from superqr_desktop.v7.modem_sender import V7ModemSender
from superqr_desktop.v7.package_stream import COMPRESSION_DEFLATE_RAW, COMPRESSION_NONE, PreparedPackageSource


def _vectors() -> dict:
    path = Path(__file__).parents[1] / "src" / "superqr_desktop" / "contract" / "v7_modem_vectors.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase2_cross_platform_packet_and_inner_fec_vector():
    vectors = _vectors()
    coeff = vectors["coefficient_vector"]
    assert [f"{word:016X}" for word in coefficient_words(coeff["session_id"], coeff["generation_id"], coeff["symbol_id"], coeff["source_count"])] == coeff["words_hex"]
    pv = vectors["packet_vector"]
    sources = [bytes.fromhex(value) for value in pv["source_symbols_hex"]]
    payload = encode_fountain_symbol(sources, pv["session_id"], pv["generation_id"], pv["symbol_id"])
    assert payload.hex().upper() == pv["repair_payload_hex"]
    packet = build_modem_packet(session_id=pv["session_id"], generation_id=pv["generation_id"], total_generations=pv["total_generations"], symbol_id=pv["symbol_id"], source_count=pv["source_count"], generation_payload_len=pv["generation_payload_len"], payload=payload)
    assert packet.hex().upper() == pv["packet_hex"]
    iv = vectors["inner_fec_vector"]
    plan = inner_fec_plan(iv["channel_bytes"], iv["parity_ratio"])
    assert (plan.parity_bytes, plan.data_bytes, plan.interleave_stride) == (iv["parity_bytes"], iv["data_bytes"], iv["interleave_stride"])
    physical = inner_fec_encode(packet, iv["channel_bytes"], iv["parity_ratio"])
    assert hashlib.sha256(physical).hexdigest().upper() == iv["physical_sha256"]


def test_symbol_capacity_is_phy_budget_only():
    assert symbol_payload_capacity(400, .15) == 304
    assert symbol_payload_capacity(1600, .15) == 1324
    assert symbol_payload_capacity(2933, .15) == 2457


def test_package_source_compresses_large_repetitive_input_and_cleans_spool(tmp_path):
    path = tmp_path / "compressible.txt"
    original = (b"SuperQR next generation modem\n" * 40000)
    path.write_bytes(original)
    source = PreparedPackageSource.prepare(str(path))
    spool = source.stored_path
    try:
        assert source.info.compression_id == COMPRESSION_DEFLATE_RAW
        assert source.info.stored_size < source.info.original_size // 4
        assert source.info.original_sha256 == hashlib.sha256(original).hexdigest().upper()
        assert source.read_at(0, 4) == b"S7PK"
        assert source.read_at(source.size - 17, 17)
        assert source._handle is not None and not source._handle.closed
        assert spool != str(path) and os.path.exists(spool)
    finally:
        source.close()
    assert not os.path.exists(spool)


def test_package_source_passes_through_entropy_without_spool(tmp_path):
    path = tmp_path / "random.bin"
    original = os.urandom(700000)
    path.write_bytes(original)
    with PreparedPackageSource.prepare(str(path)) as source:
        assert source.info.compression_id == COMPRESSION_NONE
        assert source.stored_path == str(path)
        prefix = source.read_at(0, len(source.prefix))
        assert prefix == source.prefix
        assert source.read_at(len(source.prefix) + 12345, 4096) == original[12345:12345 + 4096]


def test_sender_keeps_generation_memory_bounded_and_has_no_exact_frame_carousel(tmp_path):
    path = tmp_path / "large.bin"
    path.write_bytes(os.urandom(3 * 1024 * 1024))
    with PreparedPackageSource.prepare(str(path), allow_compression=False) as source:
        sender = V7ModemSender(source, channel_bytes=400, session_id=0xA1B2C3D4, initial_repair_fraction=.25)
        assert len(sender.plans) > 10
        assert max(plan.source_count for plan in sender.plans) <= 256
        assert max(plan.source_count * plan.symbol_bytes for plan in sender.plans) <= 128 * 1024 + sender.symbol_bytes
        first = sender.plans[0]
        systematic = sender.physical_frame(0, 0)
        repair_a = sender.repair_frame(0, 0)
        repair_b = sender.repair_frame(0, 1)
        assert len(systematic) == len(repair_a) == len(repair_b) == 400
        assert systematic != repair_a != repair_b
        assert first.source_count <= 256
        snapshot = sender.snapshot()
        assert snapshot.generation_bytes_resident <= 128 * 1024 + sender.symbol_bytes


def test_generation_planning_never_requires_whole_file_memory():
    plans = plan_generations(10 * 1024 * 1024 * 1024, 2457)
    assert len(plans) > 10000
    assert all(plan.source_count <= 256 for plan in plans)
    assert max(plan.payload_len for plan in plans) <= 256 * 2457
