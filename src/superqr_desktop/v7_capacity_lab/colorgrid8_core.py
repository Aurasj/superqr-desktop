"""Desktop-side ColorGrid8 LAB generator.

This is a sender-only mirror of the protocol reference model. It deliberately
lives under ``v7_capacity_lab`` and has no imports from production V7.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BITS_PER_CELL = 3
CHROMA_BITS = 2
HEADER_MAGIC = 0xC8D
HEADER_VERSION = 1
HEADER_PAYLOAD_BITS = 51
HEADER_CRC_BITS = 5
HEADER_BITS = 56
HEADER_REPETITION = 2
HEADER_CELLS = 112
PILOT_PERIOD = 25
DEFAULT_SEED = 0x4D3A
GOLDEN_STEP = 0x9E3779B1
GRID_SWEEP = ((128, 96), (144, 112), (160, 136), (168, 144), (176, 144))
FPS_SWEEP = (15, 20, 24, 30)
PROFILE_IDS = {dims: index for index, dims in enumerate(GRID_SWEEP)}
FPS_CODES = {fps: index for index, fps in enumerate(FPS_SWEEP)}

PALETTE_RGB = np.asarray(
    [
        (0x10, 0x72, 0x01),
        (0x80, 0x39, 0x01),
        (0x10, 0x57, 0x8F),
        (0x80, 0x1E, 0x8F),
        (0x84, 0xE6, 0x75),
        (0xF4, 0xAD, 0x75),
        (0x84, 0xCB, 0xFF),
        (0xF4, 0x92, 0xFF),
    ],
    dtype=np.uint8,
)


@dataclass(frozen=True)
class ColorGrid8Profile:
    cols: int = 168
    rows: int = 144
    fps: int = 30
    seed: int = DEFAULT_SEED

    def __post_init__(self) -> None:
        if (self.cols, self.rows) not in PROFILE_IDS:
            raise ValueError(f"unsupported ColorGrid8 grid: {self.cols}x{self.rows}")
        if self.fps not in FPS_CODES:
            raise ValueError(f"unsupported ColorGrid8 FPS: {self.fps}")
        if self.cols < HEADER_CELLS:
            raise ValueError("grid is too narrow for the repeated header")
        if not 0 <= self.seed <= 0xFFFF:
            raise ValueError("seed must fit 16 bits")

    @property
    def profile_id(self) -> int:
        return PROFILE_IDS[(self.cols, self.rows)]

    @property
    def name(self) -> str:
        return f"colorgrid8_{self.cols}x{self.rows}_{self.fps}fps"

    @property
    def total_cells(self) -> int:
        return self.cols * self.rows

    @property
    def pilot_cells(self) -> int:
        usable = (self.rows - 1) * self.cols
        return (usable + PILOT_PERIOD - 1) // PILOT_PERIOD

    @property
    def payload_cells(self) -> int:
        return self.total_cells - self.cols - self.pilot_cells

    @property
    def raw_kib_s(self) -> float:
        return self.total_cells * 3 * self.fps / 8.0 / 1024.0

    @property
    def payload_kib_s(self) -> float:
        return self.payload_cells * 3 * self.fps / 8.0 / 1024.0

    def post_fec_kib_s(self, fec_fraction: float = 0.20) -> float:
        return self.payload_kib_s * (1.0 - fec_fraction)


def _crc5(bits: list[int]) -> int:
    reg = 0x1F
    for bit in bits:
        feedback = ((reg >> 4) & 1) ^ (bit & 1)
        reg = (reg << 1) & 0x1F
        if feedback:
            reg ^= 0x05
    return reg ^ 0x1F


def _append_bits(out: list[int], value: int, width: int) -> None:
    for shift in range(width - 1, -1, -1):
        out.append((value >> shift) & 1)


def header_bits(profile: ColorGrid8Profile, frame_index: int) -> list[int]:
    bits: list[int] = []
    _append_bits(bits, HEADER_MAGIC, 12)
    _append_bits(bits, HEADER_VERSION, 2)
    _append_bits(bits, profile.profile_id, 3)
    _append_bits(bits, FPS_CODES[profile.fps], 2)
    _append_bits(bits, frame_index & 0xFFFF, 16)
    _append_bits(bits, profile.seed, 16)
    if len(bits) != HEADER_PAYLOAD_BITS:
        raise AssertionError("header width mismatch")
    _append_bits(bits, _crc5(bits), HEADER_CRC_BITS)
    return bits


def header_symbols(profile: ColorGrid8Profile, frame_index: int) -> np.ndarray:
    out = np.zeros(profile.cols, dtype=np.uint8)
    cursor = 0
    for bit in header_bits(profile, frame_index):
        symbol = 4 if bit else 0
        out[cursor] = symbol
        out[cursor + 1] = symbol
        cursor += 2
    for index in range(cursor, profile.cols):
        out[index] = 4 if index & 1 else 0
    return out


def is_pilot(profile: ColorGrid8Profile, row: int, col: int) -> bool:
    if row == 0:
        return False
    flat = (row - 1) * profile.cols + col
    return flat % PILOT_PERIOD == 0


def pilot_symbol(profile: ColorGrid8Profile, row: int, col: int, frame_index: int) -> int:
    flat = (row - 1) * profile.cols + col
    return ((flat // PILOT_PERIOD) + frame_index) & 7


class Xorshift32:
    __slots__ = ("state",)

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF or 1

    def next(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state


def payload_seed(profile: ColorGrid8Profile, frame_index: int) -> int:
    return ((profile.seed << 16) ^ ((frame_index * GOLDEN_STEP) & 0xFFFFFFFF) ^ 0xC0180A8D) & 0xFFFFFFFF


def build_symbol_frame(profile: ColorGrid8Profile, frame_index: int) -> np.ndarray:
    matrix = np.zeros((profile.rows, profile.cols), dtype=np.uint8)
    matrix[0, :] = header_symbols(profile, frame_index)
    prng = Xorshift32(payload_seed(profile, frame_index))
    for row in range(1, profile.rows):
        for col in range(profile.cols):
            if is_pilot(profile, row, col):
                matrix[row, col] = pilot_symbol(profile, row, col, frame_index)
            else:
                matrix[row, col] = prng.next() & 7
    return matrix


def rgb_frame(profile: ColorGrid8Profile, frame_index: int) -> np.ndarray:
    """Return an HxWx3 cell-color image before pixel scaling."""
    return PALETTE_RGB[build_symbol_frame(profile, frame_index)]


def golden_crc32(profile: ColorGrid8Profile, frame_index: int) -> int:
    import zlib

    return zlib.crc32(build_symbol_frame(profile, frame_index).tobytes()) & 0xFFFFFFFF
