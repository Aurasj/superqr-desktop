"""Local model types matching protocol.v7_capacity_lab.model.

CONSUMER IMPLEMENTATION — NOT a second protocol source of truth.
"""

from dataclasses import dataclass, field


@dataclass
class PaletteCandidate:
    name: str
    bits_per_cell: int
    symbol_count: int
    color_map: dict[int, str]

    def __post_init__(self):
        if len(self.color_map) != self.symbol_count:
            raise ValueError(
                f"Palette {self.name}: color_map has {len(self.color_map)} entries, "
                f"expected {self.symbol_count}"
            )

    def binary_label(self, symbol_index: int) -> int:
        if not (0 <= symbol_index < self.symbol_count):
            raise ValueError(f"Symbol index {symbol_index} out of range [0, {self.symbol_count})")
        return symbol_index


@dataclass
class GridGeometry:
    grid_size: int
    canvas_w: float
    canvas_h: float
    payload_bbox: tuple[float, float, float, float]
    cell_size: float
    rows: int
    cols: int

    def cell_bbox(self, row: int, col: int) -> tuple[float, float, float, float]:
        px1, py1, _, _ = self.payload_bbox
        x1 = px1 + col * self.cell_size
        y1 = py1 + row * self.cell_size
        return (x1, y1, x1 + self.cell_size, y1 + self.cell_size)


@dataclass
class SymbolMatrix:
    rows: int
    cols: int
    palette_name: str
    symbols: list[list[int]]

    def __post_init__(self):
        if len(self.symbols) != self.rows:
            raise ValueError(f"SymbolMatrix: expected {self.rows} rows, got {len(self.symbols)}")
        for r, row in enumerate(self.symbols):
            if len(row) != self.cols:
                raise ValueError(f"SymbolMatrix: row {r} has {len(row)} cols, expected {self.cols}")


@dataclass
class PayloadRegion:
    region_id: int
    row_start: int
    row_end: int
    col_start: int
    col_end: int

    @property
    def rows(self) -> int:
        return self.row_end - self.row_start

    @property
    def cols(self) -> int:
        return self.col_end - self.col_start

    @property
    def cell_count(self) -> int:
        return self.rows * self.cols


@dataclass
class PayloadLayout:
    name: str
    regions: list[PayloadRegion]


@dataclass
class CalibrationConfig:
    solid_frames: bool = True
    preamble_frames: int = 0
    reference_cell_density: int = 0


@dataclass
class LabProfile:
    name: str
    grid_size: int
    palette_name: str
    layout_name: str
    seed: int
    dwell_epochs: int
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)


@dataclass
class LabFrame:
    frame_index: int
    frame_type: str
    symbol_matrix: SymbolMatrix
    dwell_epochs: int
    logical_epoch: int
    is_calibration: bool


@dataclass
class FrameSequence:
    profile_name: str
    frames: list[LabFrame]


@dataclass
class ReferenceVector:
    profile_name: str
    grid_size: int
    palette_name: str
    seed: int
    symbols_per_frame: int
    first_20: list[int]
    last_20: list[int]
    symbol_crc32: str
    symbol_sha256: str
