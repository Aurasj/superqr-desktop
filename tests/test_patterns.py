import pytest
from superqr_desktop.v6.patterns import Xorshift32, get_pattern_bytes, get_pattern_crc32

def test_xorshift32_golden_vector():
    pattern = get_pattern_bytes("deterministic_random", 20, 20)
    assert len(pattern) == 400
    
    first_20 = pattern[:20]
    expected_first_20 = [1, 2, 3, 0, 0, 2, 3, 3, 2, 1, 0, 0, 0, 3, 1, 1, 2, 0, 2, 1]
    assert first_20 == expected_first_20, f"Expected {expected_first_20}, got {first_20}"

def test_crc32_golden_vector():
    pattern = get_pattern_bytes("deterministic_random", 20, 20)
    crc = get_pattern_crc32(pattern)
    crc_hex = f"{crc:08X}"
    assert crc_hex == "BEAFE8A7", f"Expected BEAFE8A7, got {crc_hex}"

def test_pattern_modes():
    black = get_pattern_bytes("black", 20, 20)
    assert all(val == 0 for val in black)
    
    white = get_pattern_bytes("white", 20, 20)
    assert all(val == 1 for val in white)
    
    checker = get_pattern_bytes("checkerboard", 20, 20)
    assert len(checker) == 400
    assert checker[0] == 0
    assert checker[1] == 1
    assert checker[2] == 2
    assert checker[3] == 3
