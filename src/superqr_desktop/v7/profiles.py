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

    @property
    def bits_per_cell(self) -> int:
        return 2 if self.palette_name == "v6_reference_4" else 3

    @property
    def color_count(self) -> int:
        return 1 << self.bits_per_cell

    @property
    def cell_count(self) -> int:
        return self.grid * self.grid

    @property
    def frame_size(self) -> int:
        return (self.cell_count * self.bits_per_cell) // 8

    @property
    def payload_size(self) -> int:
        return self.frame_size - 20

    @property
    def cell_width(self) -> float:
        return (PAYLOAD_BBOX[2] - PAYLOAD_BBOX[0]) / self.grid

    @property
    def cell_height(self) -> float:
        return (PAYLOAD_BBOX[3] - PAYLOAD_BBOX[1]) / self.grid

    def raw_kib_s(self, interval_ms: int) -> float:
        return self.frame_size * (1000.0 / interval_ms) / 1024.0

    def payload_kib_s(self, interval_ms: int) -> float:
        return self.payload_size * (1000.0 / interval_ms) / 1024.0


PROFILES = (
    OpticalProfile(0, "safe_40_4", "40×40 • 4 colors • Safe", 40, "v6_reference_4"),
    OpticalProfile(1, "balanced_48_4", "48×48 • 4 colors • Balanced", 48, "v6_reference_4"),
    OpticalProfile(2, "fast_56_4", "56×56 • 4 colors • Fast", 56, "v6_reference_4"),
    OpticalProfile(3, "turbo_64_4", "64×64 • 4 colors • Turbo", 64, "v6_reference_4"),
    OpticalProfile(4, "stress_72_4", "72×72 • 4 colors • Stress", 72, "v6_reference_4"),
    OpticalProfile(5, "stress_80_4", "80×80 • 4 colors • Stress+", 80, "v6_reference_4"),
    OpticalProfile(6, "color_40_8", "40×40 • 8 colors • Color", 40, "candidate_8_a"),
    OpticalProfile(7, "color_48_8", "48×48 • 8 colors • Color Fast", 48, "candidate_8_a"),
    OpticalProfile(8, "color_56_8", "56×56 • 8 colors • Color Turbo", 56, "candidate_8_a"),
    OpticalProfile(9, "color_64_8", "64×64 • 8 colors • Color Stress", 64, "candidate_8_a"),
)

BY_ID = {p.id: p for p in PROFILES}
BY_KEY = {p.key: p for p in PROFILES}
BY_LABEL = {p.label: p for p in PROFILES}
DEFAULT_PROFILE = BY_KEY["balanced_48_4"]


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
