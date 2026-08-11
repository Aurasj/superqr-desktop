"""Canonical geometry helpers for the lab-only Chroma4 ShapeGrid candidate."""
from __future__ import annotations

MAX_CANONICAL_TILE_PITCH = 6.0


def canonical_grid_bbox(profile: dict, payload_bbox: list[float]) -> tuple[float, float, float, float]:
    """Return the sender-independent grid rectangle in carrier coordinates."""
    left, top, right, bottom = map(float, payload_bbox)
    cols = int(profile["grid_cols"])
    rows = int(profile["grid_rows"])
    pitch = min(
        MAX_CANONICAL_TILE_PITCH,
        (right - left) / cols,
        (bottom - top) / rows,
    )
    width = cols * pitch
    height = rows * pitch
    x0 = (left + right - width) * 0.5
    y0 = (top + bottom - height) * 0.5
    return x0, y0, x0 + width, y0 + height


def canonical_tile_pitch(profile: dict, payload_bbox: list[float]) -> float:
    x0, y0, x1, y1 = canonical_grid_bbox(profile, payload_bbox)
    pitch_x = (x1 - x0) / int(profile["grid_cols"])
    pitch_y = (y1 - y0) / int(profile["grid_rows"])
    if abs(pitch_x - pitch_y) > 1e-9:
        raise ValueError("ShapeGrid canonical tiles are not square")
    return pitch_x
