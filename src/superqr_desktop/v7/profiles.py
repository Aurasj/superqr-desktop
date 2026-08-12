from __future__ import annotations

from dataclasses import dataclass

PAYLOAD_BBOX = (100.0, 190.0, 900.0, 810.0)
PROFILE_CODE_CELLS = (
    (430.0, 145.0, 455.0, 175.0),
    (465.0, 145.0, 490.0, 175.0),
    (500.0, 145.0, 525.0, 175.0),
    (535.0, 145.0, 560.0, 175.0),
)
EXTRA_PILOTS = {
    "GREEN": (200.0, 145.0, 230.0, 175.0),
    "YELLOW": (240.0, 145.0, 270.0, 175.0),
    "CYAN": (730.0, 145.0, 760.0, 175.0),
    "MAGENTA": (770.0, 145.0, 800.0, 175.0),
}

PALETTES = {
    "v6_reference_4": (
        "#000000", "#FFFFFF", "#FF0000", "#0000FF",
    ),
    "candidate_8_a": (
        "#000000", "#FFFFFF", "#FF0000", "#00FF00",
        "#0000FF", "#FFFF00", "#00FFFF", "#FF00FF",
    ),
}


@dataclass(frozen=True)
class OpticalProfile:
    id: int
    key: str
    label: str
    grid: int
    palette_name: str
    is_qr: bool = False
    qr_version: int = 0
    qr_ecc: str = "L"
    qr_mask: int = 4
    qr_frame_bytes: int = 0

    _bits_per_cell: int = 0
    _color_count: int = 0
    _cell_count: int = 0
    _frame_size: int = 0
    _payload_size: int = 0
    _cell_width: float = 0.0
    _cell_height: float = 0.0

    def __post_init__(self):
        bp = 2 if self.palette_name == "v6_reference_4" else 3
        cc = 1 << bp
        cnt = self.grid * self.grid
        fs = self.qr_frame_bytes if self.is_qr else (cnt * bp) // 8
        ps = fs - 20
        cw = (PAYLOAD_BBOX[2] - PAYLOAD_BBOX[0]) / self.grid if self.grid > 0 else 0.0
        ch = (PAYLOAD_BBOX[3] - PAYLOAD_BBOX[1]) / self.grid if self.grid > 0 else 0.0
        object.__setattr__(self, "_bits_per_cell", bp)
        object.__setattr__(self, "_color_count", cc)
        object.__setattr__(self, "_cell_count", cnt)
        object.__setattr__(self, "_frame_size", fs)
        object.__setattr__(self, "_payload_size", ps)
        object.__setattr__(self, "_cell_width", cw)
        object.__setattr__(self, "_cell_height", ch)

    @property
    def bits_per_cell(self) -> int: return self._bits_per_cell
    @property
    def color_count(self) -> int: return self._color_count
    @property
    def cell_count(self) -> int: return self._cell_count
    @property
    def frame_size(self) -> int: return self._frame_size
    @property
    def payload_size(self) -> int: return self._payload_size
    @property
    def cell_width(self) -> float: return self._cell_width
    @property
    def cell_height(self) -> float: return self._cell_height

    def raw_kib_s(self, interval_ms: int) -> float:
        return self.frame_size * (1000.0 / interval_ms) / 1024.0

    def payload_kib_s(self, interval_ms: int) -> float:
        return self.payload_size * (1000.0 / interval_ms) / 1024.0


PROFILES = (
    OpticalProfile(0, "v40_l_15fps", "V40-L 15fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="L", qr_mask=4, qr_frame_bytes=2953),
    OpticalProfile(1, "v40_m_15fps", "V40-M 15fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="M", qr_mask=4, qr_frame_bytes=2331),
    OpticalProfile(2, "v40_l_20fps", "V40-L 20fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="L", qr_mask=4, qr_frame_bytes=2953),
    OpticalProfile(3, "v40_m_20fps", "V40-M 20fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="M", qr_mask=4, qr_frame_bytes=2331),
    OpticalProfile(4, "v40_l_30fps", "V40-L 30fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="L", qr_mask=4, qr_frame_bytes=2953),
    OpticalProfile(5, "v40_m_30fps", "V40-M 30fps", 0, "",
                  is_qr=True, qr_version=40, qr_ecc="M", qr_mask=4, qr_frame_bytes=2331),
)

BY_ID = {p.id: p for p in PROFILES}
BY_KEY = {p.key: p for p in PROFILES}
BY_LABEL = {p.label: p for p in PROFILES}

# Physical captures currently establish V40-L 15 FPS as the reliable baseline.
# Faster V40 modes remain explicit user-selectable experiments until physical
# transfer tests prove they should replace the default.
DEFAULT_PROFILE = BY_KEY["v40_l_15fps"]


def get_profile(value: int | str | OpticalProfile) -> OpticalProfile:
    if isinstance(value, OpticalProfile):
        return value
    if isinstance(value, int):
        return BY_ID[value]
    if value in BY_KEY:
        return BY_KEY[value]
    if value in BY_LABEL:
        return BY_LABEL[value]
    raise KeyError(f"unknown V7 optical profile: {value}")
