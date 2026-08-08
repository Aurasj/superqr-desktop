"""Local calibration builders matching protocol.v7_capacity_lab.calibration.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import (
    SymbolMatrix, LabFrame, PaletteCandidate, GridGeometry,
)


def build_solid_calibration_frames(
    palette: PaletteCandidate, geometry: GridGeometry,
    base_logical_epoch: int = 0, dwell_epochs: int = 2,
) -> list[LabFrame]:
    frames = []
    for idx in range(palette.symbol_count):
        symbols = [[idx] * geometry.cols for _ in range(geometry.rows)]
        matrix = SymbolMatrix(
            rows=geometry.rows, cols=geometry.cols,
            palette_name=palette.name, symbols=symbols,
        )
        frame = LabFrame(
            frame_index=len(frames), frame_type="calibration",
            symbol_matrix=matrix, dwell_epochs=dwell_epochs,
            logical_epoch=base_logical_epoch + len(frames) * dwell_epochs,
            is_calibration=True,
        )
        frames.append(frame)
    return frames
