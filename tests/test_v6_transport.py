import os
import json
import pytest

from superqr_desktop.v6.transport import (
    crc16_ccitt_false,
    bytes_to_palette_indexes,
    build_transfer_package,
    parse_transfer_package,
    build_frame,
    parse_frame,
    create_frames
)

@pytest.fixture
def vectors():
    vectors_path = os.path.join(os.path.dirname(__file__), "transport-vectors.json")
    with open(vectors_path, "r") as f:
        return json.load(f)

def test_crc16(vectors):
    vec = vectors["crc16_ccitt_false_reference"]
    data = bytes.fromhex(vec["input_hex"])
    expected = vec["expected_crc16_int"]
    
    assert crc16_ccitt_false(data) == expected

def test_optical_frame_vector(vectors):
    vec = vectors["optical_frame_vector"]
    payload = bytes.fromhex(vec["payload_hex"])
    
    frame = build_frame(
        session_id=vec["session_id"],
        frame_id=vec["frame_id"],
        total_frames=vec["total_frames"],
        payload=payload
    )
    
    assert frame.hex().upper() == vec["frame_hex"].upper()
    
    parsed = parse_frame(frame)
    assert parsed["session_id"] == vec["session_id"]
    assert parsed["frame_id"] == vec["frame_id"]
    assert parsed["total_frames"] == vec["total_frames"]
    assert parsed["payload"] == payload

def test_bytes_to_palette_indexes(vectors):
    vec = vectors["optical_frame_vector"]
    frame = bytes.fromhex(vec["frame_hex"])
    
    indexes = bytes_to_palette_indexes(frame)
    assert indexes == vec["expected_400_palette_indexes"]

def test_tiny_transfer_package(vectors):
    vec = vectors["tiny_transfer_package"]
    filename = vec["filename"]
    file_data = bytes.fromhex(vec["file_data_hex"])
    
    package = build_transfer_package(filename, file_data)
    assert package.hex().upper() == vec["package_hex"].upper()
    
    parsed_filename, parsed_data = parse_transfer_package(package)
    assert parsed_filename == filename
    assert parsed_data == file_data

def test_multi_frame_transfer(vectors):
    vec = vectors["multi_frame_transfer"]
    
    # We must construct a dummy package_data that matches the payload split
    # Wait, the vectors don't give the raw file data for multi_frame_transfer.
    # It gives total_frames and frames_hex.
    # But wait, create_frames requires package_data. We can parse the frames to extract it.
    
    expected_frames = [bytes.fromhex(f) for f in vec["frames_hex"]]
    
    # Extract package data by concatenating data frame payloads
    # Frame 0 is header, Frames 1.. are data
    package_data = bytearray()
    for frame_bytes in expected_frames[1:]:
        parsed = parse_frame(frame_bytes)
        package_data.extend(parsed["payload"])
        
    # Trim the padding. We know package_length = 218
    package_data = package_data[:vec["package_length"]]
    
    frames = create_frames(vec["session_id"], bytes(package_data))
    
    assert len(frames) == vec["total_frames"]
    for i in range(len(frames)):
        assert frames[i] == expected_frames[i]
