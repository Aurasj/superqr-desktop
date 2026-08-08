"""Local geometry matching protocol.v7_capacity_lab.geometry.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import GridGeometry

CANVAS_W = 1000.0
CANVAS_H = 1000.0
PAYLOAD_BBOX = (200.0, 200.0, 800.0, 800.0)


def _payload_dim() -> float:
    return PAYLOAD_BBOX[2] - PAYLOAD_BBOX[0]


def build_geometry(grid_size: int) -> GridGeometry:
    if grid_size < 1:
        raise ValueError(f"grid_size must be positive, got {grid_size}")

    dim = _payload_dim()
    cell_size = dim / grid_size

    return GridGeometry(
        grid_size=grid_size,
        canvas_w=CANVAS_W,
        canvas_h=CANVAS_H,
        payload_bbox=PAYLOAD_BBOX,
        cell_size=cell_size,
        rows=grid_size,
        cols=grid_size,
    )
