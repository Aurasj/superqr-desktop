import zlib

class Xorshift32:
    def __init__(self, seed: int = 42):
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state ^= (self.state << 13) & 0xFFFFFFFF
        self.state ^= (self.state >> 17) & 0xFFFFFFFF
        self.state ^= (self.state << 5) & 0xFFFFFFFF
        return self.state

def get_pattern_bytes(mode: str, rows: int = 20, cols: int = 20) -> list[int]:
    """
    Returns palette index integers (0=BLACK, 1=WHITE, 2=RED, 3=BLUE) for 20x20 data grid.
    """
    total = rows * cols
    if mode == "black":
        return [0] * total
    elif mode == "white":
        return [1] * total
    elif mode == "checkerboard":
        return [(r + c) % 4 for r in range(rows) for c in range(cols)]
    else:  # deterministic_random / default
        prng = Xorshift32(42)
        pattern = []
        for _ in range(total):
            val = (prng.next() >> 16) & 3
            pattern.append(val)
        return pattern

def get_pattern_crc32(pattern_bytes: list[int]) -> int:
    """
    Calculates CRC32 over the raw byte array of palette indexes.
    """
    return zlib.crc32(bytes(pattern_bytes)) & 0xFFFFFFFF
