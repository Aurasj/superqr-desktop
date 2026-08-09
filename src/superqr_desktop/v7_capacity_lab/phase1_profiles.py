"""Desktop implementation of canonical V7 Phase 1 experiment frames."""

from __future__ import annotations

import hashlib
import struct
import zlib

import segno

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    get_protocol_model,
    get_protocol_prng,
    load_phy_selection_manifest,
)
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState


class Phase1ManifestError(RuntimeError):
    pass


def grid_profiles() -> dict[str, dict]:
    manifest = load_phy_selection_manifest()
    return {entry["name"]: entry for entry in manifest["grid_profiles"]}


def qr_controls() -> dict[str, dict]:
    manifest = load_phy_selection_manifest()
    return {entry["name"]: entry for entry in manifest["qr_controls"]}


def profile_id(profile_name: str) -> int:
    names = list(grid_profiles()) + list(qr_controls())
    try:
        return names.index(profile_name)
    except ValueError as error:
        raise Phase1ManifestError(f"Unknown profile: {profile_name}") from error


def build_run_envelope(
    profile_name: str,
    run_token: int,
    frame_index: int,
    frame_count: int,
    dwell_epochs: int,
    state: RunState = RunState.RUNNING,
) -> LabRunEnvelope:
    return LabRunEnvelope(
        state, profile_id(profile_name), run_token, frame_index, frame_count, dwell_epochs,
    )


class GridFrameSequence:
    """Continuous deterministic grid sequence with golden-vector validation."""

    def __init__(self, profile_name: str):
        self.manifest = load_phy_selection_manifest()
        try:
            self.profile = grid_profiles()[profile_name]
        except KeyError as error:
            raise Phase1ManifestError(f"Unknown grid profile: {profile_name}") from error
        prng_mod = get_protocol_prng()
        self._prng = prng_mod.Xorshift32(int(self.manifest["seed"]))
        self._next_index = 0

    def next_frame(self):
        frame_index = self._next_index % 256
        self._next_index += 1
        rows = int(self.profile["rows"])
        cols = int(self.profile["cols"])
        bits = int(self.profile["bits_per_cell"])
        symbols = [
            [self._prng.next_symbol(bits) for _ in range(cols)]
            for _ in range(rows)
        ]
        model = get_protocol_model()
        matrix = model.SymbolMatrix(
            rows=rows,
            cols=cols,
            palette_name=self.profile["palette_name"],
            symbols=symbols,
        )
        return frame_index, matrix


def validate_grid_vectors() -> None:
    manifest = load_phy_selection_manifest()
    for profile in manifest["grid_profiles"]:
        sequence = GridFrameSequence(profile["name"])
        expected = manifest["vectors"][profile["name"]]["frames"]
        for vector in expected:
            _, matrix = sequence.next_frame()
            raw = bytes(symbol for row in matrix.symbols for symbol in row)
            crc = f"{zlib.crc32(raw) & 0xFFFFFFFF:08X}"
            sha = hashlib.sha256(raw).hexdigest()
            if crc != vector["crc32"] or sha != vector["sha256"]:
                raise Phase1ManifestError(
                    f"Golden-vector mismatch for {profile['name']} frame {vector['frame_index']}"
                )


def build_qr_control_payload(
    control: dict,
    frame_index: int,
    *,
    run_token: int = 0,
    state: RunState = RunState.RUNNING,
    frame_count: int = 256,
    dwell_epochs: int = 3,
) -> bytes:
    frame_bytes = int(control["frame_bytes"])
    body = bytearray(frame_bytes - 4)
    body[0:4] = b"SQP1"
    body[4] = int(control["version"])
    body[5] = 1
    seed = int(load_phy_selection_manifest()["seed"])
    struct.pack_into("<I", body, 6, frame_index)
    struct.pack_into("<I", body, 10, seed)
    struct.pack_into("<H", body, 14, frame_bytes)
    body[16:26] = build_run_envelope(
        control["name"], run_token, frame_index, frame_count, dwell_epochs, state,
    ).encode()
    prng_mod = get_protocol_prng()
    prng = prng_mod.Xorshift32((seed ^ int(control["version"]) ^ frame_index) or 1)
    for index in range(26, len(body)):
        body[index] = prng.next() & 0xFF
    return bytes(body) + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def build_qr_matrix(control: dict, frame_index: int, **payload_options) -> tuple[bytes, ...]:
    """Encode an exact-version QR frame and return its matrix without quiet zone."""
    payload = build_qr_control_payload(control, frame_index, **payload_options)
    qr = segno.make_qr(
        payload,
        version=int(control["version"]),
        error=control["error_correction"],
        mask=int(control["mask_pattern"]),
        mode="byte",
        boost_error=False,
    )
    expected_modules = int(control["module_count"])
    if qr.version != int(control["version"]):
        raise Phase1ManifestError(f"QR version changed: expected {control['version']}, got {qr.version}")
    matrix = tuple(bytes(row) for row in qr.matrix)
    if len(matrix) != expected_modules or any(len(row) != expected_modules for row in matrix):
        raise Phase1ManifestError(
            f"QR matrix size mismatch: expected {expected_modules}, got {len(matrix)}"
        )
    return matrix


def validate_qr_vectors() -> None:
    for control in qr_controls().values():
        payload = build_qr_control_payload(control, 0)
        expected = control["frame_zero"]
        if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
            raise Phase1ManifestError(f"QR payload vector mismatch for {control['name']}")
        build_qr_matrix(control, 0)
