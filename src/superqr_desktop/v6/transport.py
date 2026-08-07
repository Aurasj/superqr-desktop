import struct
import zlib

MAGIC = 0xA5
VERSION = 0x06
PAYLOAD_SIZE = 91
FRAME_SIZE = 100
MAX_FRAMES = 65535
MAX_PACKAGE_SIZE = (MAX_FRAMES - 1) * PAYLOAD_SIZE

class TransportError(Exception):
    pass

def crc16_ccitt_false(data: bytes) -> int:
    """
    CRC16/CCITT-FALSE
    Polynomial: 0x1021
    Initial value: 0xFFFF
    No reflection, no final XOR.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc

def bytes_to_palette_indexes(data: bytes) -> list[int]:
    """
    Maps exactly 100 bytes to 400 2-bit palette indexes (0..3).
    MSB first, so bits 7,6 are cell 0, bits 5,4 are cell 1, etc.
    00 -> 0 BLACK
    01 -> 1 WHITE
    10 -> 2 RED
    11 -> 3 BLUE
    """
    if len(data) != 100:
        raise ValueError("Data must be exactly 100 bytes")
    
    indexes = []
    for b in data:
        indexes.append((b >> 6) & 0x03)
        indexes.append((b >> 4) & 0x03)
        indexes.append((b >> 2) & 0x03)
        indexes.append(b & 0x03)
    return indexes

def palette_indexes_to_bytes(indexes: list[int]) -> bytes:
    """
    Inverse of bytes_to_palette_indexes.
    Takes exactly 400 ints (0..3) and returns 100 bytes.
    """
    if len(indexes) != 400:
        raise ValueError("Must provide exactly 400 palette indexes")
        
    out = bytearray()
    for i in range(0, 400, 4):
        b = (indexes[i] << 6) | (indexes[i+1] << 4) | (indexes[i+2] << 2) | indexes[i+3]
        out.append(b)
    return bytes(out)

def build_transfer_package(filename: str, file_data: bytes) -> bytes:
    """
    Builds the V6 TransferPackage:
    offset 0: filename_length uint8
    offset 1..4: file_size uint32 big-endian
    offset 5..8: file_crc32 uint32 big-endian
    offset 9..: UTF-8 filename bytes
    then: raw file bytes
    """
    filename_bytes = filename.encode('utf-8')
    fn_len = len(filename_bytes)
    
    if not (1 <= fn_len <= 255):
        raise ValueError("Filename length must be between 1 and 255 bytes after UTF-8 encoding")
        
    file_size = len(file_data)
    file_crc32 = zlib.crc32(file_data) & 0xFFFFFFFF
    
    package = bytearray()
    package.append(fn_len)
    package.extend(struct.pack(">I", file_size))
    package.extend(struct.pack(">I", file_crc32))
    package.extend(filename_bytes)
    package.extend(file_data)
    
    if len(package) > MAX_PACKAGE_SIZE:
        raise ValueError(f"Package too large. Max {MAX_PACKAGE_SIZE} bytes, got {len(package)}")
        
    return bytes(package)

def parse_transfer_package(package_data: bytes) -> tuple[str, bytes]:
    """
    Parses a V6 TransferPackage and returns (filename, file_data).
    Validates limits, exact lengths, and file CRC32.
    """
    if len(package_data) < 9:
        raise TransportError("Truncated package: missing header")
        
    fn_len = package_data[0]
    if fn_len < 1:
        raise TransportError("Invalid filename length: 0")
        
    file_size = struct.unpack(">I", package_data[1:5])[0]
    expected_crc = struct.unpack(">I", package_data[5:9])[0]
    
    if len(package_data) < 9 + fn_len:
        raise TransportError("Truncated package: missing filename bytes")
        
    filename_bytes = package_data[9:9+fn_len]
    try:
        filename = filename_bytes.decode('utf-8')
    except UnicodeDecodeError:
        raise TransportError("Invalid UTF-8 in filename")
        
    expected_total_len = 9 + fn_len + file_size
    if len(package_data) < expected_total_len:
        raise TransportError("Truncated package: missing file bytes")
    if len(package_data) > expected_total_len:
        raise TransportError("Trailing data after declared file bytes")
        
    file_data = package_data[9+fn_len:9+fn_len+file_size]
    actual_crc = zlib.crc32(file_data) & 0xFFFFFFFF
    
    if actual_crc != expected_crc:
        raise TransportError(f"File CRC32 mismatch. Expected {expected_crc:08X}, got {actual_crc:08X}")
        
    return filename, file_data

def build_frame(session_id: int, frame_id: int, total_frames: int, payload: bytes) -> bytes:
    """
    Builds exactly one 100-byte V6 optical transport frame.
    Payload must be exactly 91 bytes.
    """
    if not (1 <= session_id <= 255):
        raise ValueError("Session ID must be between 1 and 255")
    if total_frames < 2 or total_frames > MAX_FRAMES:
        raise ValueError(f"Total frames must be between 2 and {MAX_FRAMES}")
    if frame_id < 0 or frame_id >= total_frames:
        raise ValueError("Invalid frame_id")
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError(f"Payload must be exactly {PAYLOAD_SIZE} bytes")
        
    frame = bytearray()
    frame.append(MAGIC)
    frame.append(VERSION)
    frame.append(session_id)
    frame.extend(struct.pack(">H", frame_id))
    frame.extend(struct.pack(">H", total_frames))
    frame.extend(payload)
    
    crc = crc16_ccitt_false(frame)
    frame.extend(struct.pack(">H", crc))
    
    return bytes(frame)

def parse_frame(frame_data: bytes) -> dict:
    """
    Parses and validates a 100-byte V6 frame.
    Returns a dict with parsed headers and payload.
    """
    if len(frame_data) != FRAME_SIZE:
        raise TransportError(f"Frame must be exactly {FRAME_SIZE} bytes")
        
    expected_crc = struct.unpack(">H", frame_data[98:100])[0]
    actual_crc = crc16_ccitt_false(frame_data[:98])
    if actual_crc != expected_crc:
        raise TransportError("Frame CRC16 mismatch")
        
    if frame_data[0] != MAGIC:
        raise TransportError("Invalid MAGIC")
    if frame_data[1] != VERSION:
        raise TransportError("Invalid VERSION")
        
    session_id = frame_data[2]
    if session_id == 0:
        raise TransportError("Session ID 0 is invalid")
        
    frame_id = struct.unpack(">H", frame_data[3:5])[0]
    total_frames = struct.unpack(">H", frame_data[5:7])[0]
    
    if total_frames < 2:
        raise TransportError("Total frames must be >= 2")
    if frame_id >= total_frames:
        raise TransportError("frame_id must be < total_frames")
        
    payload = frame_data[7:98]
    
    return {
        "session_id": session_id,
        "frame_id": frame_id,
        "total_frames": total_frames,
        "payload": payload
    }

def create_frames(session_id: int, package_data: bytes) -> list[bytes]:
    """
    Splits a TransferPackage into a sequence of 100-byte V6 frames.
    """
    pkg_len = len(package_data)
    
    if pkg_len > MAX_PACKAGE_SIZE:
        raise ValueError("Package too large")
        
    # Calculate required data frames
    data_frames = (pkg_len + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
    total_frames = 1 + data_frames  # frame 0 + data frames
    
    frames = []
    
    # Frame 0 (Header)
    f0_payload = bytearray(struct.pack(">I", pkg_len))
    f0_payload.extend(b'\x00' * (PAYLOAD_SIZE - 4))
    frames.append(build_frame(session_id, 0, total_frames, bytes(f0_payload)))
    
    # Data Frames
    offset = 0
    for frame_id in range(1, total_frames):
        chunk = package_data[offset:offset+PAYLOAD_SIZE]
        if len(chunk) < PAYLOAD_SIZE:
            # Right-pad final chunk
            chunk = chunk + b'\x00' * (PAYLOAD_SIZE - len(chunk))
        
        frames.append(build_frame(session_id, frame_id, total_frames, chunk))
        offset += PAYLOAD_SIZE
        
    return frames
