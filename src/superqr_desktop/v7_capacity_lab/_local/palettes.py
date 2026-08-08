"""Local palette definitions matching protocol.v7_capacity_lab.palettes.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import PaletteCandidate

V6_REFERENCE_4 = PaletteCandidate(
    name="v6_reference_4",
    bits_per_cell=2,
    symbol_count=4,
    color_map={
        0: "#000000",
        1: "#FFFFFF",
        2: "#FF0000",
        3: "#0000FF",
    },
)

CANDIDATE_8_A = PaletteCandidate(
    name="candidate_8_a",
    bits_per_cell=3,
    symbol_count=8,
    color_map={
        0: "#000000",
        1: "#FFFFFF",
        2: "#FF0000",
        3: "#00FF00",
        4: "#0000FF",
        5: "#FFFF00",
        6: "#00FFFF",
        7: "#FF00FF",
    },
)

PALETTES: dict[str, PaletteCandidate] = {
    "v6_reference_4": V6_REFERENCE_4,
    "candidate_8_a": CANDIDATE_8_A,
}


def get_palette(name: str) -> PaletteCandidate:
    if name not in PALETTES:
        raise KeyError(f"Unknown palette: {name}. Available: {list(PALETTES.keys())}")
    return PALETTES[name]
