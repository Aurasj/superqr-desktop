"""Phase 5B Macrochroma C1 (QL4-C4) Desktop Sender & Codec Implementation.

Renders 480x388 @ 2 display px / fine cell (960x776 px carrier) with:
- 4-level calibrated Luma (2 bits/cell)
- 4-state Macrochroma (2 bits per 2x2 macroblock)
- RS(180, 176) Berlekamp-Massey inner error correction + CRC-16
- 2D Cauchy spatial parity tiles
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Sequence
import numpy as np

SCHEMA = "superqr.macrochroma.transfer.v4"
MACROCHROMA_VERSION = 4
HEADER_MAGIC = 0xC8F

FINE_LUMA_LEVELS = 4
FINE_LUMA_BITS = 2
MACRO_CHROMA_STATES = 4
MACRO_CHROMA_BITS = 2
MACRO_BLOCK_SIZE = 2

BITS_PER_MACROBLOCK = 10
BITS_PER_FINE_CELL = 2.50

TILE_FINE_W = 24
TILE_FINE_H = 24
TILE_MACRO_W = TILE_FINE_W // MACRO_BLOCK_SIZE
TILE_MACRO_H = TILE_FINE_H // MACRO_BLOCK_SIZE
TILE_MACROBLOCKS = TILE_MACRO_W * TILE_MACRO_H
TILE_RAW_BITS = TILE_MACROBLOCKS * BITS_PER_MACROBLOCK  # 1440 bits = 180 bytes
TILE_RAW_BYTES = TILE_RAW_BITS // 8

TILE_HEADER_BYTES = 2  # tile_index (9 bits) + frame_idx (6 bits) + parity_flag (1 bit)
TILE_CRC_BYTES = 2
TILE_INNER_FEC_BYTES = 4
TILE_PAYLOAD_BYTES = TILE_RAW_BYTES - TILE_HEADER_BYTES - TILE_CRC_BYTES - TILE_INNER_FEC_BYTES  # 172 bytes

HEADER_ROWS = 4

PALETTE_RGB = [
    # L0: Dark
    (0x50, 0x14, 0x10),  # L0-C0: Red
    (0x10, 0x48, 0x14),  # L0-C1: Green
    (0x10, 0x24, 0x88),  # L0-C2: Blue
    (0x44, 0x14, 0x60),  # L0-C3: Magenta

    # L1: Dim
    (0xA8, 0x48, 0x20),  # L1-C0: Red
    (0x20, 0x8C, 0x28),  # L1-C1: Green
    (0x20, 0x64, 0xD4),  # L1-C2: Blue
    (0x8C, 0x30, 0xBC),  # L1-C3: Magenta

    # L2: Bright
    (0xE8, 0x8C, 0x40),  # L2-C0: Red
    (0x40, 0xC8, 0x48),  # L2-C1: Green
    (0x48, 0xAE, 0xFA),  # L2-C2: Blue
    (0xD8, 0x68, 0xFA),  # L2-C3: Magenta

    # L3: High
    (0xFA, 0xCE, 0x90),  # L3-C0: Red
    (0x98, 0xFA, 0xA0),  # L3-C1: Green
    (0x90, 0xE4, 0xFA),  # L3-C2: Blue
    (0xFA, 0xB0, 0xFA),  # L3-C3: Magenta
]

# GF(256) Tables
GF_EXP = [0] * 512
GF_LOG = [0] * 256

def _init_gf() -> None:
    x = 1
    for i in range(255):
        GF_EXP[i] = x
        GF_EXP[i + 255] = x
        GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    GF_LOG[0] = 0

_init_gf()

def gf_add(a: int, b: int) -> int:
    return a ^ b

def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]

GF_MUL_TABLE = np.zeros((256, 256), dtype=np.uint8)
for _a in range(256):
    for _b in range(256):
        GF_MUL_TABLE[_a, _b] = gf_mul(_a, _b) if (_a != 0 and _b != 0) else 0

def gf_inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("GF(256) division by zero")
    return GF_EXP[255 - GF_LOG[a]]

def gf_poly_mul(p: list[int], q: list[int]) -> list[int]:
    res = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            res[i + j] ^= gf_mul(a, b)
    return res

def rs_generator_poly(n_sym: int = TILE_INNER_FEC_BYTES) -> list[int]:
    g = [1]
    for k in range(1, n_sym + 1):
        root = GF_EXP[k]
        next_g = [0] * (len(g) + 1)
        for i, coeff in enumerate(g):
            next_g[i] = gf_add(next_g[i], coeff)
            next_g[i + 1] = gf_add(next_g[i + 1], gf_mul(coeff, root))
        g = next_g
    return g

RS_GEN = rs_generator_poly(TILE_INNER_FEC_BYTES)

CRC16_TABLE = [0] * 256
for _i in range(256):
    _curr = _i << 8
    for _ in range(8):
        if _curr & 0x8000:
            _curr = ((_curr << 1) ^ 0x1021) & 0xFFFF
        else:
            _curr = (_curr << 1) & 0xFFFF
    CRC16_TABLE[_i] = _curr

def crc16_ccitt(data: bytes | bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_TABLE[(crc >> 8) ^ byte]
    return crc


@dataclass(frozen=True)
class MacrochromaTile:
    tile_index: int
    frame_index: int
    payload: bytes
    is_parity: bool = False


@dataclass(frozen=True)
class MacrochromaProfile:
    cols: int = 480
    rows: int = 388
    fps: int = 30
    session_id: int = 0x4D3A1234
    version: int = MACROCHROMA_VERSION
    preset: str = "MEDIUM"

    def __post_init__(self) -> None:
        if self.cols % TILE_FINE_W != 0 or (self.rows - HEADER_ROWS) % TILE_FINE_H != 0:
            raise ValueError(f"grid {self.cols}x{self.rows} payload region must be multiple of tile {TILE_FINE_W}x{TILE_FINE_H}")
        if self.fps not in (30, 45, 60, 90):
            raise ValueError(f"unsupported FPS: {self.fps}")
        if self.preset not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError(f"unsupported preset: {self.preset}")

    @property
    def tiles_x(self) -> int:
        return self.cols // TILE_FINE_W

    @property
    def tiles_y(self) -> int:
        return (self.rows - HEADER_ROWS) // TILE_FINE_H

    @property
    def total_tiles(self) -> int:
        return self.tiles_x * self.tiles_y

    @property
    def data_tiles_per_frame(self) -> int:
        if self.preset == "LOW":
            return 304
        elif self.preset == "HIGH":
            return 288
        return 300

    @property
    def parity_tiles_per_frame(self) -> int:
        return self.total_tiles - self.data_tiles_per_frame

    @property
    def carousel_ratio(self) -> float:
        if self.preset == "LOW":
            return 16.0 / 17.0
        elif self.preset == "HIGH":
            return 8.0 / 9.0
        return 12.0 / 13.0

    @property
    def frame_data_bytes(self) -> int:
        return self.data_tiles_per_frame * TILE_PAYLOAD_BYTES

    @property
    def raw_kib_s(self) -> float:
        return (self.cols * self.rows * BITS_PER_FINE_CELL * self.fps) / 8.0 / 1024.0

    @property
    def pre_carousel_kib_s(self) -> float:
        return (self.frame_data_bytes * self.fps) / 1024.0

    @property
    def protected_goodput_kib_s(self) -> float:
        return self.pre_carousel_kib_s * self.carousel_ratio


def rs_encode(msg: bytes | bytearray, n_sym: int = TILE_INNER_FEC_BYTES) -> bytes:
    parity = bytearray(n_sym)
    for byte in msg:
        feedback = byte ^ parity[0]
        parity = parity[1:] + bytearray(1)
        if feedback != 0:
            for j in range(n_sym):
                parity[j] ^= gf_mul(feedback, RS_GEN[j + 1])
    return bytes(parity)


def rs_calc_syndromes(codeword: bytes | bytearray, n_sym: int = TILE_INNER_FEC_BYTES) -> list[int]:
    n = len(codeword)
    syndromes = [0] * n_sym
    for j in range(n_sym):
        val = 0
        exp_j = j + 1
        for i, byte in enumerate(codeword):
            power = ((n - 1 - i) * exp_j) % 255
            val ^= gf_mul(byte, GF_EXP[power])
        syndromes[j] = val
    return syndromes


def berlekamp_massey(syndromes: list[int], n_sym: int = TILE_INNER_FEC_BYTES) -> list[int]:
    c = [1]
    b = [1]
    l = 0
    m = 1
    for k in range(n_sym):
        d = syndromes[k]
        for i in range(1, l + 1):
            if i < len(c):
                d ^= gf_mul(c[i], syndromes[k - i])
        if d == 0:
            m += 1
        else:
            t = list(c)
            scale = d
            pad = [0] * m
            scaled_b = pad + [gf_mul(scale, x) for x in b]
            while len(c) < len(scaled_b):
                c.append(0)
            for i in range(len(scaled_b)):
                c[i] ^= scaled_b[i]
            if 2 * l <= k:
                l = k + 1 - l
                b = [gf_mul(x, gf_inv(d)) for x in t]
                m = 1
            else:
                m += 1
    return c


def chien_search(lambda_poly: list[int], n: int) -> list[int] | None:
    while len(lambda_poly) > 1 and lambda_poly[-1] == 0:
        lambda_poly.pop()
    deg = len(lambda_poly) - 1
    if deg == 0:
        return []
    error_positions = []
    for i in range(n):
        p = n - 1 - i
        inv_x = GF_EXP[(255 - (p % 255)) % 255]
        val = 0
        term = 1
        for coeff in lambda_poly:
            val ^= gf_mul(coeff, term)
            term = gf_mul(term, inv_x)
        if val == 0:
            error_positions.append(i)
    if len(error_positions) != deg:
        return None
    return error_positions


def forney_algorithm(syndromes: list[int], lambda_poly: list[int], error_positions: list[int], n: int) -> list[int] | None:
    omega = [0] * len(syndromes)
    for i in range(len(syndromes)):
        for j in range(len(lambda_poly)):
            if i - j >= 0:
                omega[i] ^= gf_mul(syndromes[i - j], lambda_poly[j])
    lambda_prime = [0] * len(lambda_poly)
    for i in range(1, len(lambda_poly), 2):
        lambda_prime[i - 1] = lambda_poly[i]
    magnitudes = []
    for pos in error_positions:
        p = n - 1 - pos
        inv_x = GF_EXP[(255 - (p % 255)) % 255]
        omega_val = 0
        term = 1
        for coeff in omega:
            omega_val ^= gf_mul(coeff, term)
            term = gf_mul(term, inv_x)
        lambda_prime_val = 0
        term = 1
        for coeff in lambda_prime:
            lambda_prime_val ^= gf_mul(coeff, term)
            term = gf_mul(term, inv_x)
        if lambda_prime_val == 0:
            return None
        mag = gf_mul(omega_val, gf_inv(lambda_prime_val))
        magnitudes.append(mag)
    return magnitudes


def rs_decode(raw: bytes | bytearray, erasures: list[int] | None = None) -> bytearray | None:
    n = len(raw)
    n_sym = TILE_INNER_FEC_BYTES
    if erasures is None:
        erasures = []
    if len(erasures) > n_sym:
        return None
    syndromes = rs_calc_syndromes(raw, n_sym)
    if all(s == 0 for s in syndromes) and len(erasures) == 0:
        return bytearray(raw)
    gamma = [1]
    for pos in erasures:
        p = n - 1 - pos
        x_val = GF_EXP[p % 255]
        next_gamma = [0] * (len(gamma) + 1)
        for i, coeff in enumerate(gamma):
            next_gamma[i] ^= coeff
            next_gamma[i + 1] ^= gf_mul(coeff, x_val)
        gamma = next_gamma
    t_syndromes = [0] * n_sym
    for i in range(n_sym):
        for j in range(len(gamma)):
            if i - j >= 0:
                t_syndromes[i] ^= gf_mul(syndromes[i - j], gamma[j])
    num_erasures = len(erasures)
    remaining_syndromes = n_sym - num_erasures
    if remaining_syndromes > 0:
        err_lambda = berlekamp_massey(t_syndromes[num_erasures:n_sym], remaining_syndromes)
    else:
        err_lambda = [1]
    total_lambda = gf_poly_mul(gamma, err_lambda)
    err_deg = len(err_lambda) - 1
    if 2 * err_deg + num_erasures > n_sym:
        return None
    all_positions = chien_search(total_lambda, n)
    if all_positions is None:
        return None
    magnitudes = forney_algorithm(syndromes, total_lambda, all_positions, n)
    if magnitudes is None:
        return None
    corrected = bytearray(raw)
    for pos, mag in zip(all_positions, magnitudes):
        corrected[pos] ^= mag
    post_syndromes = rs_calc_syndromes(corrected, n_sym)
    if not all(s == 0 for s in post_syndromes):
        return None
    return corrected


def encode_tile_bytes(tile: MacrochromaTile) -> bytes:
    if len(tile.payload) != TILE_PAYLOAD_BYTES:
        raise ValueError(f"tile payload must be exactly {TILE_PAYLOAD_BYTES} bytes")
    b0 = tile.tile_index & 0xFF
    b1 = ((tile.tile_index >> 8) & 0x01) | ((tile.frame_index & 0x3F) << 1) | (0x80 if tile.is_parity else 0)
    raw_body = bytes([b0, b1]) + tile.payload
    crc = crc16_ccitt(raw_body)
    body_with_crc = raw_body + struct.pack(">H", crc)
    parity = rs_encode(body_with_crc, TILE_INNER_FEC_BYTES)
    return bytes(body_with_crc) + parity


def decode_tile_bytes(raw: bytes | bytearray, erasures: list[int] | None = None) -> MacrochromaTile | None:
    if len(raw) != TILE_RAW_BYTES:
        return None
    corrected = rs_decode(raw, erasures)
    if corrected is None:
        return None
    body_len = TILE_HEADER_BYTES + TILE_PAYLOAD_BYTES
    raw_body = corrected[:body_len]
    expected_crc = struct.unpack(">H", corrected[body_len:body_len + TILE_CRC_BYTES])[0]
    if crc16_ccitt(raw_body) != expected_crc:
        return None
    tile_index = raw_body[0] | ((raw_body[1] & 0x01) << 8)
    frame_index = (raw_body[1] >> 1) & 0x3F
    is_parity = (raw_body[1] & 0x80) != 0
    payload = bytes(raw_body[2:])
    return MacrochromaTile(tile_index, frame_index, payload, is_parity)


def tile_to_macroblocks(tile_bytes: bytes) -> list[tuple[int, int, int, int, int]]:
    macroblocks: list[tuple[int, int, int, int, int]] = []
    bit_buf = 0
    bits_in_buf = 0
    byte_idx = 0
    for _ in range(TILE_MACROBLOCKS):
        while bits_in_buf < BITS_PER_MACROBLOCK and byte_idx < len(tile_bytes):
            bit_buf = (bit_buf << 8) | tile_bytes[byte_idx]
            bits_in_buf += 8
            byte_idx += 1
        bits_in_buf -= BITS_PER_MACROBLOCK
        sym = (bit_buf >> bits_in_buf) & 0x3FF
        y00 = (sym >> 8) & 0x3
        y01 = (sym >> 6) & 0x3
        y10 = (sym >> 4) & 0x3
        y11 = (sym >> 2) & 0x3
        chroma = sym & 0x3
        macroblocks.append((y00, y01, y10, y11, chroma))
    return macroblocks


def macroblocks_to_tile(macroblocks: Sequence[tuple[int, int, int, int, int]]) -> bytes:
    out = bytearray(TILE_RAW_BYTES)
    bit_buf = 0
    bits_in_buf = 0
    byte_idx = 0
    for y00, y01, y10, y11, chroma in macroblocks:
        sym = ((y00 & 3) << 8) | ((y01 & 3) << 6) | ((y10 & 3) << 4) | ((y11 & 3) << 2) | (chroma & 3)
        bit_buf = (bit_buf << BITS_PER_MACROBLOCK) | sym
        bits_in_buf += BITS_PER_MACROBLOCK
        while bits_in_buf >= 8 and byte_idx < len(out):
            bits_in_buf -= 8
            out[byte_idx] = (bit_buf >> bits_in_buf) & 0xFF
            byte_idx += 1
    return bytes(out)


def generate_spatial_parity_tiles(
    data_tiles: Sequence[MacrochromaTile],
    parity_count: int,
    frame_index: int,
) -> list[MacrochromaTile]:
    k = len(data_tiles)
    m = parity_count
    parity_tiles: list[MacrochromaTile] = []

    # 2-block interleaved Cauchy MDS spatial FEC
    m_per_block = m // 2
    for b in range(2):
        block_data = [data_tiles[i] for i in range(b, k, 2)]
        num_tiles = len(block_data)
        block_mat = np.frombuffer(b"".join(dt.payload for dt in block_data), dtype=np.uint8).reshape((num_tiles, TILE_PAYLOAD_BYTES))
        for p_idx in range(m_per_block):
            coeffs = np.array([gf_inv(p_idx ^ (16 + i)) for i in range(num_tiles)], dtype=np.uint8)
            term = GF_MUL_TABLE[coeffs[:, None], block_mat]
            parity_payload = np.bitwise_xor.reduce(term, axis=0).tobytes()
            global_p_idx = b * m_per_block + p_idx
            parity_tiles.append(
                MacrochromaTile(
                    tile_index=k + global_p_idx,
                    frame_index=frame_index,
                    payload=parity_payload,
                    is_parity=True,
                )
            )
    return parity_tiles


def recover_spatial_erased_tiles(
    received_tiles: Sequence[MacrochromaTile],
    data_tiles_count: int,
    parity_tiles_count: int,
    frame_index: int,
) -> list[MacrochromaTile]:
    """Recover missing tiles from available spatial parity tiles using Cauchy GF(256) linear equation solving."""
    by_idx = {t.tile_index: t for t in received_tiles if t.frame_index == frame_index}
    missing_all = [i for i in range(data_tiles_count) if i not in by_idx]
    if not missing_all:
        return [by_idx[i] for i in range(data_tiles_count)]

    m_per_block = parity_tiles_count // 2

    for b in range(2):
        block_missing = [i // 2 for i in missing_all if i % 2 == b]
        if not block_missing:
            continue

        # Available parities for block b
        avail_parities = []
        for p in range(m_per_block):
            g_pidx = data_tiles_count + b * m_per_block + p
            if g_pidx in by_idx:
                avail_parities.append((p, by_idx[g_pidx]))

        if len(block_missing) <= len(avail_parities):
            num_missing = len(block_missing)
            used_parities = avail_parities[:num_missing]

            A = [[0 for _ in range(num_missing)] for _ in range(num_missing)]
            B = [bytearray(p_tile.payload) for _, p_tile in used_parities]

            k_block = (data_tiles_count + 1 - b) // 2

            for r, (p_idx, _) in enumerate(used_parities):
                # Subtract known data tiles in this block
                for i in range(k_block):
                    global_i = 2 * i + b
                    if i not in block_missing and global_i in by_idx:
                        coeff = gf_inv(p_idx ^ (16 + i))
                        src = by_idx[global_i].payload
                        for byte_i in range(TILE_PAYLOAD_BYTES):
                            B[r][byte_i] ^= gf_mul(src[byte_i], coeff)
                # Fill A matrix for missing block tiles
                for c, m_idx in enumerate(block_missing):
                    A[r][c] = gf_inv(p_idx ^ (16 + m_idx))

            # Gaussian elimination over GF(256)
            for i in range(num_missing):
                pivot = i
                while pivot < num_missing and A[pivot][i] == 0:
                    pivot += 1
                if pivot == num_missing:
                    break
                if pivot != i:
                    A[i], A[pivot] = A[pivot], A[i]
                    B[i], B[pivot] = B[pivot], B[i]

                inv_pivot = gf_inv(A[i][i])
                for j in range(i, num_missing):
                    A[i][j] = gf_mul(A[i][j], inv_pivot)
                for byte_i in range(TILE_PAYLOAD_BYTES):
                    B[i][byte_i] = gf_mul(B[i][byte_i], inv_pivot)

                for r in range(num_missing):
                    if r != i and A[r][i] != 0:
                        factor = A[r][i]
                        for j in range(i, num_missing):
                            A[r][j] ^= gf_mul(factor, A[i][j])
                        for byte_i in range(TILE_PAYLOAD_BYTES):
                            B[r][byte_i] ^= gf_mul(factor, B[i][byte_i])

            for c, m_idx in enumerate(block_missing):
                global_idx = 2 * m_idx + b
                by_idx[global_idx] = MacrochromaTile(global_idx, frame_index, bytes(B[c]), is_parity=False)

    return [by_idx[i] for i in range(data_tiles_count) if i in by_idx]


def encode_macrochroma_frame_grid(
    profile: MacrochromaProfile,
    frame_index: int,
    tiles: Sequence[MacrochromaTile],
) -> tuple[list[list[int]], list[list[int]]]:
    luma_grid = [[0 for _ in range(profile.cols)] for _ in range(profile.rows)]
    chroma_mb_cols = profile.cols // MACRO_BLOCK_SIZE
    chroma_mb_rows = profile.rows // MACRO_BLOCK_SIZE
    chroma_grid = [[0 for _ in range(chroma_mb_cols)] for _ in range(chroma_mb_rows)]

    header_raw = struct.pack(">HBBHH", HEADER_MAGIC, (profile.version << 4) | ((frame_index >> 8) & 0x0F), frame_index & 0xFF, (profile.session_id >> 16) & 0xFFFF, profile.session_id & 0xFFFF)
    header_crc = crc16_ccitt(header_raw)
    header_payload = header_raw + struct.pack(">H", header_crc)
    header_bits = []
    for b in header_payload:
        for bit_i in range(7, -1, -1):
            header_bits.append((b >> bit_i) & 1)
    for r in range(HEADER_ROWS):
        for c in range(profile.cols):
            bit_val = header_bits[c % len(header_bits)]
            luma_grid[r][c] = 3 if bit_val else 0

    tiles_map = {t.tile_index: t for t in tiles}
    for ty in range(profile.tiles_y):
        for tx in range(profile.tiles_x):
            t_idx = ty * profile.tiles_x + tx
            if t_idx in tiles_map:
                t_bytes = encode_tile_bytes(tiles_map[t_idx])
            else:
                t_bytes = bytes(TILE_RAW_BYTES)
            mbs = tile_to_macroblocks(t_bytes)
            for mb_y in range(TILE_MACRO_H):
                for mb_x in range(TILE_MACRO_W):
                    mb_idx = mb_y * TILE_MACRO_W + mb_x
                    y00, y01, y10, y11, chroma = mbs[mb_idx]
                    top_r = HEADER_ROWS + ty * TILE_FINE_H + mb_y * 2
                    left_c = tx * TILE_FINE_W + mb_x * 2
                    luma_grid[top_r][left_c] = y00
                    luma_grid[top_r][left_c + 1] = y01
                    luma_grid[top_r + 1][left_c] = y10
                    luma_grid[top_r + 1][left_c + 1] = y11
                    chroma_grid[top_r // 2][left_c // 2] = chroma

    return luma_grid, chroma_grid


def decode_macrochroma_frame_grid(
    profile: MacrochromaProfile,
    luma_grid: Sequence[Sequence[int]],
    chroma_grid: Sequence[Sequence[int]],
    expected_frame_index: int = 0,
) -> list[MacrochromaTile]:
    decoded_tiles: list[MacrochromaTile] = []
    for ty in range(profile.tiles_y):
        for tx in range(profile.tiles_x):
            t_idx = ty * profile.tiles_x + tx
            mbs: list[tuple[int, int, int, int, int]] = []
            for mb_y in range(TILE_MACRO_H):
                for mb_x in range(TILE_MACRO_W):
                    top_r = HEADER_ROWS + ty * TILE_FINE_H + mb_y * 2
                    left_c = tx * TILE_FINE_W + mb_x * 2
                    y00 = luma_grid[top_r][left_c] & 3
                    y01 = luma_grid[top_r][left_c + 1] & 3
                    y10 = luma_grid[top_r + 1][left_c] & 3
                    y11 = luma_grid[top_r + 1][left_c + 1] & 3
                    chroma = chroma_grid[top_r // 2][left_c // 2] & 3
                    mbs.append((y00, y01, y10, y11, chroma))
            tile_raw = macroblocks_to_tile(mbs)
            tile = decode_tile_bytes(tile_raw)
            if tile is not None:
                raw_mod64 = tile.frame_index
                delta = raw_mod64 - (expected_frame_index & 0x3F)
                if delta > 32:
                    delta -= 64
                elif delta < -32:
                    delta += 64
                resolved_frame = expected_frame_index + delta
                decoded_tiles.append(MacrochromaTile(tile.tile_index, resolved_frame, tile.payload, tile.is_parity))
    return decoded_tiles


def render_macrochroma_rgb_image(
    profile: MacrochromaProfile,
    luma_grid: Sequence[Sequence[int]] | np.ndarray,
    chroma_grid: Sequence[Sequence[int]] | np.ndarray,
    cell_px: int = 2,
) -> np.ndarray:
    luma_arr = np.asarray(luma_grid, dtype=np.uint8) & 3
    chroma_arr = np.asarray(chroma_grid, dtype=np.uint8) & 3
    chroma_upsampled = np.repeat(np.repeat(chroma_arr, 2, axis=0), 2, axis=1)
    state_idx = (luma_arr * 4) + chroma_upsampled
    palette_arr = np.array(PALETTE_RGB, dtype=np.uint8)
    rgb_grid = palette_arr[state_idx]
    if cell_px > 1:
        return np.repeat(np.repeat(rgb_grid, cell_px, axis=0), cell_px, axis=1)
    return rgb_grid
