"""Local Xorshift32 PRNG matching protocol.v7_capacity_lab.prng.

CONSUMER IMPLEMENTATION — cross-validated against canonical golden vectors.
"""


class Xorshift32:
    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFF
        if self._state == 0:
            raise ValueError("Xorshift32 seed must be non-zero")

    def next(self) -> int:
        x = self._state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        self._state = x
        return x

    def next_symbol(self, bits_per_cell: int) -> int:
        symbol_count = 1 << bits_per_cell
        return (self.next() >> 16) % symbol_count
