"""Local pattern generators matching protocol.v7_capacity_lab.patterns.

CONSUMER IMPLEMENTATION — NOT a second source of truth.
"""

from superqr_desktop.v7_capacity_lab._local.model import SymbolMatrix
from superqr_desktop.v7_capacity_lab._local.prng import Xorshift32


def random_fill(prng: Xorshift32, rows: int, cols: int,
                palette_name: str, bits_per_cell: int) -> SymbolMatrix:
    symbols = []
    for _ in range(rows):
        row = [prng.next_symbol(bits_per_cell) for _ in range(cols)]
        symbols.append(row)
    return SymbolMatrix(rows=rows, cols=cols, palette_name=palette_name, symbols=symbols)


def solid_fill(color_index: int, rows: int, cols: int,
               palette_name: str, symbol_count: int) -> SymbolMatrix:
    if not (0 <= color_index < symbol_count):
        raise ValueError(f"color_index {color_index} out of range [0, {symbol_count})")
    symbols = [[color_index] * cols for _ in range(rows)]
    return SymbolMatrix(rows=rows, cols=cols, palette_name=palette_name, symbols=symbols)
