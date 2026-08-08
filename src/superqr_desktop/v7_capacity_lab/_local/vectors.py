"""Local vector/hash computation matching protocol.v7_capacity_lab.vectors.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

import hashlib
import zlib

from superqr_desktop.v7_capacity_lab._local.model import (
    SymbolMatrix, LabProfile, ReferenceVector,
)
from superqr_desktop.v7_capacity_lab._local.palettes import get_palette
from superqr_desktop.v7_capacity_lab._local.geometry import build_geometry
from superqr_desktop.v7_capacity_lab._local.profiles import build_frame_sequence


def lab_serialize(matrix: SymbolMatrix) -> bytes:
    data = bytearray()
    for row in matrix.symbols:
        for symbol in row:
            if not (0 <= symbol <= 255):
                raise ValueError(f"Symbol index {symbol} out of byte range")
            data.append(symbol)
    return bytes(data)


def compute_symbol_hashes(matrix: SymbolMatrix) -> dict[str, str]:
    data = lab_serialize(matrix)
    crc32_val = zlib.crc32(data) & 0xFFFFFFFF
    sha256_val = hashlib.sha256(data).hexdigest()
    return {"symbol_crc32": f"{crc32_val:08X}", "symbol_sha256": sha256_val}


def generate_reference_vector(profile: LabProfile, frame_index: int = 0) -> ReferenceVector:
    palette = get_palette(profile.palette_name)
    geometry = build_geometry(profile.grid_size)

    seq = build_frame_sequence(profile, num_data_frames=frame_index + 1)
    data_frames = [f for f in seq.frames if not f.is_calibration]
    if not data_frames:
        raise ValueError(f"No data frames in profile {profile.name}")
    matrix = data_frames[frame_index].symbol_matrix

    symbols_per_frame = geometry.rows * geometry.cols

    flat = []
    for row in matrix.symbols:
        flat.extend(row)

    first_20 = flat[:20]
    last_20 = flat[-20:] if len(flat) >= 20 else flat

    hashes = compute_symbol_hashes(matrix)

    return ReferenceVector(
        profile_name=profile.name,
        grid_size=profile.grid_size,
        palette_name=profile.palette_name,
        seed=profile.seed,
        symbols_per_frame=symbols_per_frame,
        first_20=first_20,
        last_20=last_20,
        symbol_crc32=hashes["symbol_crc32"],
        symbol_sha256=hashes["symbol_sha256"],
    )


def verify_symbol_matrix_from_reference(rv: ReferenceVector, matrix: SymbolMatrix) -> bool:
    hashes = compute_symbol_hashes(matrix)
    return (hashes["symbol_crc32"] == rv.symbol_crc32
            and hashes["symbol_sha256"] == rv.symbol_sha256)
