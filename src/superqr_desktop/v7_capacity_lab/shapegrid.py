"""Lab-only V7 Phase 0 Chroma4 ShapeGrid sender codec.

The JSON artifact in superqr-protocol is authoritative. This module is a local,
performance-conscious implementation that must reproduce its canonical vectors
byte-for-byte while allowing READY/RUNNING/DONE run state at presentation time.
"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib

from superqr_desktop.v7_capacity_lab.protocol_bridge import load_shapegrid_manifest
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState

MAGIC = b"SQS1"
CODEC_VERSION = 1
SHAPE_BITS = 4
COLOR_BITS = 2
SYMBOL_BITS = 6
BLOCK_COUNT = 8
RS_N = 255
RS_K = 207
RS_PARITY = 48
GF_PRIMITIVE = 0x11D
INTERLEAVER_MULTIPLIER = 73
FRAME_OFFSET_MULTIPLIER = 17
BLOCK_OFFSET_MULTIPLIER = 131
SEED = 42
INACTIVE = 0xFF


class ShapeGridError(RuntimeError):
    pass


_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= GF_PRIMITIVE
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _poly_mul(left: list[int], right: list[int]) -> list[int]:
    output = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            output[i + j] ^= _gf_mul(a, b)
    return output


def _rs_generator() -> tuple[int, ...]:
    generator = [1]
    for index in range(RS_PARITY):
        generator = _poly_mul(generator, [1, _GF_EXP[index]])
    return tuple(generator)


_RS_GENERATOR = _rs_generator()
_RS_MUL_TABLES = tuple(
    bytes(_gf_mul(coefficient, value) for value in range(256))
    for coefficient in _RS_GENERATOR[1:]
)


def shapegrid_profiles() -> dict[str, dict]:
    return {entry["name"]: entry for entry in load_shapegrid_manifest()["profiles"]}


def shapegrid_profile(name: str) -> dict:
    try:
        return shapegrid_profiles()[name]
    except KeyError as exc:
        raise ShapeGridError(f"unknown ShapeGrid profile: {name}") from exc


def default_shapegrid_profile_name() -> str:
    for profile in load_shapegrid_manifest()["profiles"]:
        if profile["role"] == "DEFAULT_FAST":
            return str(profile["name"])
    raise ShapeGridError("ShapeGrid manifest has no DEFAULT_FAST profile")


def deterministic_payload(
    profile_id: int,
    block_id: int,
    frame_index: int,
    length: int,
    *,
    seed: int = SEED,
) -> bytes:
    state = (seed ^ (profile_id << 16) ^ (block_id << 8) ^ frame_index) & 0xFFFFFFFF
    if state == 0:
        state = 1
    output = bytearray(length)
    for index in range(length):
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        output[index] = state & 0xFF
    return bytes(output)


def build_shapegrid_block_data(
    profile: dict,
    block_id: int,
    frame_index: int,
    *,
    run_token: int = 0xBEEF,
    state: RunState = RunState.RUNNING,
    frame_count: int = 256,
    dwell_epochs: int = 3,
    seed: int = SEED,
) -> bytes:
    if not 0 <= block_id < BLOCK_COUNT:
        raise ShapeGridError("block_id must be in [0, 7]")
    useful_bytes = int(profile["useful_bytes_per_block"])
    codewords = int(profile["rs_codewords_per_block"])
    header = bytearray(26)
    header[0:4] = MAGIC
    header[4] = CODEC_VERSION
    header[5] = block_id
    header[6] = BLOCK_COUNT
    header[7] = 0
    header[8:18] = LabRunEnvelope(
        state=state,
        profile_id=int(profile["profile_id"]),
        run_token=run_token,
        frame_index=frame_index,
        frame_count=frame_count,
        dwell_epochs=dwell_epochs,
    ).encode()
    struct.pack_into("<I", header, 18, seed)
    struct.pack_into("<H", header, 22, useful_bytes)
    header[24] = SHAPE_BITS
    header[25] = COLOR_BITS

    payload = deterministic_payload(
        int(profile["profile_id"]), block_id, frame_index, useful_bytes, seed=seed
    )
    body = bytes(header) + payload
    protected = body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
    expected = codewords * RS_K
    if len(protected) != expected:
        raise ShapeGridError(
            f"block protected size {len(protected)} != RS data capacity {expected}"
        )
    return protected


def rs_encode(data: bytes) -> bytes:
    if len(data) + RS_PARITY > RS_N:
        raise ShapeGridError("RS codeword exceeds GF(256) maximum")
    work = bytearray(data) + bytearray(RS_PARITY)
    for index in range(len(data)):
        coefficient = work[index]
        if coefficient:
            for offset, table in enumerate(_RS_MUL_TABLES, start=1):
                work[index + offset] ^= table[coefficient]
    return data + bytes(work[-RS_PARITY:])


def rs_encode_block(block_data: bytes, codewords: int) -> bytes:
    if len(block_data) != codewords * RS_K:
        raise ShapeGridError("wrong ShapeGrid block data length")
    return b"".join(
        rs_encode(block_data[index * RS_K:(index + 1) * RS_K])
        for index in range(codewords)
    )


def bytes_to_symbols6(data: bytes) -> list[int]:
    if (len(data) * 8) % SYMBOL_BITS:
        raise ShapeGridError("encoded stream does not align to six-bit symbols")
    accumulator = 0
    bit_count = 0
    output: list[int] = []
    for value in data:
        accumulator = (accumulator << 8) | value
        bit_count += 8
        while bit_count >= SYMBOL_BITS:
            bit_count -= SYMBOL_BITS
            output.append((accumulator >> bit_count) & 0x3F)
            accumulator &= (1 << bit_count) - 1 if bit_count else 0
    if bit_count:
        raise AssertionError("unexpected ShapeGrid tail bits")
    return output


def symbol_to_shape_color(symbol: int) -> tuple[int, int]:
    if not 0 <= symbol < 64:
        raise ShapeGridError("ShapeGrid symbol must be in [0, 63]")
    return symbol >> COLOR_BITS, symbol & 0x03


def interleave_symbols(
    symbols: list[int], block_cells: int, block_id: int, frame_index: int
) -> bytes:
    if math.gcd(INTERLEAVER_MULTIPLIER, block_cells) != 1:
        raise ShapeGridError("interleaver multiplier is not coprime with block size")
    if len(symbols) > block_cells:
        raise ShapeGridError("encoded symbols exceed physical block cells")
    output = bytearray([INACTIVE] * block_cells)
    offset = (
        FRAME_OFFSET_MULTIPLIER * frame_index + BLOCK_OFFSET_MULTIPLIER * block_id
    ) % block_cells
    for index, symbol in enumerate(symbols):
        position = (INTERLEAVER_MULTIPLIER * index + offset) % block_cells
        if output[position] != INACTIVE:
            raise AssertionError("ShapeGrid interleaver collision")
        output[position] = symbol
    return bytes(output)


def build_shapegrid_block_cells(
    profile: dict,
    block_id: int,
    frame_index: int,
    *,
    run_token: int = 0xBEEF,
    state: RunState = RunState.RUNNING,
    frame_count: int = 256,
    dwell_epochs: int = 3,
) -> bytes:
    block_data = build_shapegrid_block_data(
        profile,
        block_id,
        frame_index,
        run_token=run_token,
        state=state,
        frame_count=frame_count,
        dwell_epochs=dwell_epochs,
    )
    encoded = rs_encode_block(block_data, int(profile["rs_codewords_per_block"]))
    symbols = bytes_to_symbols6(encoded)
    return interleave_symbols(
        symbols, int(profile["block_cells"]), block_id, frame_index
    )


def build_shapegrid_frame_cells(
    profile: dict,
    frame_index: int,
    *,
    run_token: int = 0xBEEF,
    state: RunState = RunState.RUNNING,
    frame_count: int = 256,
    dwell_epochs: int = 3,
) -> bytes:
    cols = int(profile["grid_cols"])
    rows = int(profile["grid_rows"])
    block_cols = int(profile["block_cols"])
    block_rows = int(profile["block_rows"])
    output = bytearray([INACTIVE] * (cols * rows))
    for block_id in range(BLOCK_COUNT):
        cells = build_shapegrid_block_cells(
            profile,
            block_id,
            frame_index,
            run_token=run_token,
            state=state,
            frame_count=frame_count,
            dwell_epochs=dwell_epochs,
        )
        block_x = (block_id % 4) * block_cols
        block_y = (block_id // 4) * block_rows
        for row in range(block_rows):
            source = row * block_cols
            target = (block_y + row) * cols + block_x
            output[target:target + block_cols] = cells[source:source + block_cols]
    return bytes(output)


def validate_shapegrid_vectors() -> None:
    manifest = load_shapegrid_manifest()
    if manifest["artifact"] != "v7_phase0_chroma4_shapegrid":
        raise ShapeGridError("wrong ShapeGrid artifact")
    if manifest["production_phy_frozen"] is not False:
        raise ShapeGridError("lab ShapeGrid must not freeze production PHY")
    if float(manifest["receiver_constraint"]["design_target_fps"]) != 20.0:
        raise ShapeGridError("ShapeGrid design target is not 20 FPS")
    modulation = manifest["modulation"]
    if (int(modulation["shape_bits"]), int(modulation["color_bits"])) != (4, 2):
        raise ShapeGridError("ShapeGrid alphabet must remain S16 x Chroma4")
    if len(modulation["glyphs"]) != 16 or len(modulation["data_palette"]["colors"]) != 4:
        raise ShapeGridError("ShapeGrid alphabet cardinality mismatch")

    profiles = manifest["profiles"]
    if [int(profile["profile_id"]) for profile in profiles] != [18, 19, 20]:
        raise ShapeGridError("ShapeGrid profile ids must be 18..20")
    if any(float(profile["target_fps"]) != 20.0 for profile in profiles):
        raise ShapeGridError("every ShapeGrid profile must run at 20 FPS")

    by_id = {int(profile["profile_id"]): profile for profile in profiles}
    vectors = manifest["vectors"]
    for entry in vectors["entries"]:
        profile = by_id[int(entry["profile_id"])]
        block_data = build_shapegrid_block_data(
            profile,
            int(entry["block_id"]),
            int(entry["frame_index"]),
            run_token=int(vectors["run_token"]),
            frame_count=int(vectors["frame_count"]),
            dwell_epochs=int(vectors["dwell_epochs"]),
        )
        encoded = rs_encode_block(block_data, int(profile["rs_codewords_per_block"]))
        symbols = bytes_to_symbols6(encoded)
        cells = interleave_symbols(
            symbols,
            int(profile["block_cells"]),
            int(entry["block_id"]),
            int(entry["frame_index"]),
        )
        checks = {
            "block_data_sha256": hashlib.sha256(block_data).hexdigest(),
            "encoded_sha256": hashlib.sha256(encoded).hexdigest(),
            "symbols_sha256": hashlib.sha256(bytes(symbols)).hexdigest(),
            "cells_sha256": hashlib.sha256(cells).hexdigest(),
        }
        for key, actual in checks.items():
            if actual != entry[key]:
                raise ShapeGridError(
                    f"ShapeGrid vector mismatch {profile['name']} block {entry['block_id']} {key}"
                )
        if cells.count(INACTIVE) != int(entry["inactive_cells"]):
            raise ShapeGridError("ShapeGrid inactive-cell vector mismatch")

    default = shapegrid_profile(default_shapegrid_profile_name())
    ready = build_shapegrid_block_data(default, 0, 0, state=RunState.READY)
    running = build_shapegrid_block_data(default, 0, 0, state=RunState.RUNNING)
    done = build_shapegrid_block_data(default, 0, 0, state=RunState.DONE)
    if [ready[10], running[10], done[10]] != [0, 1, 2]:
        raise ShapeGridError("ShapeGrid block run state is not carried in the inner envelope")
