from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolMatrix:
    """Small production V7 symbol-matrix value object.

    Capacity Lab keeps its own experimental model. Production transfer code must
    not depend on the lab package merely to move a row-major matrix to a renderer
    or a test.
    """

    rows: int
    cols: int
    palette_name: str
    symbols: list[list[int]]
