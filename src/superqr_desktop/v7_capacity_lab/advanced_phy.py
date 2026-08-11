"""Lab-only advanced multi-lane Phase 0 PHY sender helpers.

This module deliberately does not define the production V7 wire. It lets the
physical lab spend a <=30 FPS camera budget spatially across independent lanes.
"""
from __future__ import annotations

import hashlib
import struct
import zlib

import segno

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    get_protocol_prng,
    load_advanced_phy_manifest,
)
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState


class AdvancedPhyError(RuntimeError):
    pass


def advanced_profiles() -> dict[str, dict]:
    manifest = load_advanced_phy_manifest()
    return {entry["name"]: entry for entry in manifest["profiles"]}


def advanced_profile(name: str) -> dict:
    try:
        return advanced_profiles()[name]
    except KeyError as exc:
        raise AdvancedPhyError(f"unknown advanced PHY profile: {name}") from exc


def build_advanced_envelope(
    profile: dict,
    run_token: int,
    frame_index: int,
    frame_count: int,
    dwell_epochs: int,
    state: RunState = RunState.RUNNING,
) -> LabRunEnvelope:
    return LabRunEnvelope(
        state=state,
        profile_id=int(profile["profile_id"]),
        run_token=run_token,
        frame_index=frame_index,
        frame_count=frame_count,
        dwell_epochs=dwell_epochs,
    )


def _mixed_prng(profile_id: int, lane_id: int, frame_index: int):
    seed = int(load_advanced_phy_manifest()["design"]["seed"])
    mixed = (seed ^ (profile_id << 16) ^ (lane_id << 8) ^ frame_index) & 0xFFFFFFFF
    if mixed == 0:
        mixed = 1
    return get_protocol_prng().Xorshift32(mixed)


def build_advanced_qr_payload(
    profile: dict,
    lane: dict,
    frame_index: int,
    *,
    run_token: int = 0,
    state: RunState = RunState.RUNNING,
    frame_count: int = 256,
    dwell_epochs: int = 3,
) -> bytes:
    if lane["kind"] != "qr":
        raise AdvancedPhyError("advanced QR payload requested for non-QR lane")
    frame_bytes = int(lane["frame_bytes"])
    body = bytearray(frame_bytes - 4)
    body[0:4] = b"SQA1"
    body[4] = int(lane["version"])
    body[5] = int(lane["ecc_id"])
    body[6] = int(lane["lane_id"])
    body[7] = int(profile["lane_count"])
    seed = int(load_advanced_phy_manifest()["design"]["seed"])
    struct.pack_into("<I", body, 8, frame_index)
    struct.pack_into("<I", body, 12, seed)
    struct.pack_into("<H", body, 16, frame_bytes)
    body[18:28] = build_advanced_envelope(
        profile, run_token, frame_index, frame_count, dwell_epochs, state,
    ).encode()
    body[28] = 1
    body[29] = 0
    prng = _mixed_prng(int(profile["profile_id"]), int(lane["lane_id"]), frame_index)
    for index in range(30, len(body)):
        body[index] = prng.next() & 0xFF
    return bytes(body) + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def build_advanced_qr_matrix(profile: dict, lane: dict, frame_index: int, **options) -> tuple[bytes, ...]:
    payload = build_advanced_qr_payload(profile, lane, frame_index, **options)
    qr = segno.make_qr(
        payload,
        version=int(lane["version"]),
        error=lane["error_correction"],
        mask=int(lane["mask_pattern"]),
        mode="byte",
        boost_error=False,
    )
    matrix = tuple(bytes(row) for row in qr.matrix)
    expected = int(lane["module_count"])
    if len(matrix) != expected or any(len(row) != expected for row in matrix):
        raise AdvancedPhyError(
            f"advanced QR matrix mismatch for {profile['name']} lane {lane['lane_id']}"
        )
    return matrix


def build_advanced_grid_symbols(profile: dict, lane: dict, frame_index: int) -> tuple[tuple[int, ...], ...]:
    if lane["kind"] != "grid":
        raise AdvancedPhyError("advanced grid symbols requested for non-grid lane")
    rows = int(lane["rows"])
    cols = int(lane["cols"])
    bits = int(lane["bits_per_cell"])
    mask = (1 << bits) - 1
    prng = _mixed_prng(int(profile["profile_id"]), int(lane["lane_id"]), frame_index)
    return tuple(
        tuple((prng.next() >> 16) & mask for _ in range(cols))
        for _ in range(rows)
    )


def validate_advanced_phy_vectors() -> None:
    manifest = load_advanced_phy_manifest()
    if float(manifest["receiver_constraint"]["max_fps"]) > 30.0:
        raise AdvancedPhyError("receiver FPS ceiling exceeds 30")
    profiles = manifest["profiles"]
    if [int(profile["profile_id"]) for profile in profiles] != [14, 15, 16, 17]:
        raise AdvancedPhyError("advanced profile ids are not contiguous from 14")
    for profile in profiles:
        if float(profile["target_fps"]) > 30.0:
            raise AdvancedPhyError(f"{profile['name']} exceeds 30 FPS")
        if len(profile["lanes"]) != int(profile["lane_count"]):
            raise AdvancedPhyError(f"lane-count mismatch for {profile['name']}")
        useful = 0
        for lane in profile["lanes"]:
            useful += int(lane["useful_bytes"])
            if lane["kind"] == "qr":
                payload = build_advanced_qr_payload(profile, lane, 0)
                if hashlib.sha256(payload).hexdigest() != lane["frame_zero_sha256"]:
                    raise AdvancedPhyError(
                        f"advanced QR vector mismatch for {profile['name']} lane {lane['lane_id']}"
                    )
                build_advanced_qr_matrix(profile, lane, 0)
            else:
                symbols = build_advanced_grid_symbols(profile, lane, 0)
                if len(symbols) != int(lane["rows"]) or any(
                    len(row) != int(lane["cols"]) for row in symbols
                ):
                    raise AdvancedPhyError("advanced grid shape mismatch")
        if useful != int(profile["useful_bytes_per_epoch"]):
            raise AdvancedPhyError(f"useful-byte sum mismatch for {profile['name']}")


def default_advanced_profile_name() -> str:
    return str(load_advanced_phy_manifest()["design"]["default_profile"])
