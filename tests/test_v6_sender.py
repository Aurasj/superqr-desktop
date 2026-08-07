import pytest
from superqr_desktop.v6.sender import V6SenderSession
from superqr_desktop.v6.transport import build_transfer_package, parse_transfer_package

def test_session_id_sequence_and_wrapping():
    session = V6SenderSession()
    # Counter starts at 0, first session is 1
    sid = session.next_session_id()
    assert sid == 1
    
    # Fast forward to 255
    session.session_id_counter = 254
    assert session.next_session_id() == 255
    
    # Next wraps to 1 (never 0)
    assert session.next_session_id() == 1
    assert session.next_session_id() == 2

def test_new_file_preparation_session_id():
    session = V6SenderSession()
    sid1 = session.prepare_transfer("test1.txt", b"Hello 1")
    assert sid1 == 1
    assert session.transfer_state == "READY"
    assert session.filename == "test1.txt"
    assert session.file_size == 7
    assert session.total_frames >= 2  # Header frame + data frame
    
    sid2 = session.prepare_transfer("test2.txt", b"Hello 2")
    assert sid2 == 2
    assert session.transfer_state == "READY"
    assert session.filename == "test2.txt"

def test_start_stop_restart_preserves_frames():
    session = V6SenderSession()
    # Use ~300 bytes of data to generate 5 frames (1 header + 4 data frames)
    session.prepare_transfer("demo.bin", b"A" * 300)
    
    initial_frames = list(session.frames)
    initial_sid = session.session_id
    assert session.total_frames > 3
    
    # Start transfer
    started = session.start_transfer()
    assert started is True
    assert session.transfer_state == "SENDING"
    assert session.current_frame_idx == 0
    
    # Advance a few frames
    session.advance_frame()
    session.advance_frame()
    assert session.current_frame_idx == 2
    
    # Stop transfer
    session.stop_transfer()
    assert session.transfer_state == "STOPPED"
    
    # Restart transfer
    session.start_transfer()
    assert session.transfer_state == "SENDING"
    assert session.current_frame_idx == 0  # Restarts from 0
    assert session.session_id == initial_sid  # Session ID unchanged
    assert session.frames == initial_frames  # Frames unchanged

def test_frame_index_wrapping():
    session = V6SenderSession()
    session.prepare_transfer("small.txt", b"Data")
    total = session.total_frames
    assert total > 0
    
    session.start_transfer()
    # Cycle through all frames exactly once
    for i in range(total):
        idx = session.advance_frame()
        assert idx == i
        
    # Wraps back to 0
    assert session.current_frame_idx == 0
    idx_wrapped = session.advance_frame()
    assert idx_wrapped == 0

def test_interval_presets_and_default():
    session = V6SenderSession()
    assert session.interval_ms == 100
    assert session.INTERVAL_PRESETS == [50, 100, 200, 500]
    
    session.set_interval(50)
    assert session.interval_ms == 50
    
    session.set_interval(500)
    assert session.interval_ms == 500
    
    # Invalid interval ignored
    session.set_interval(300)
    assert session.interval_ms == 500

def test_static_pattern_switch_interaction():
    session = V6SenderSession()
    session.prepare_transfer("file.txt", b"Sample content")
    session.start_transfer()
    assert session.transfer_state == "SENDING"
    
    frames_before = list(session.frames)
    sid_before = session.session_id
    
    # User switches to static pattern
    session.set_static_pattern()
    assert session.transfer_state == "STOPPED"
    assert session.frames == frames_before
    assert session.session_id == sid_before
    assert session.filename == "file.txt"
    
    # Can restart transfer without corruption
    assert session.start_transfer() is True
    assert session.transfer_state == "SENDING"

def test_manual_frame_navigation():
    session = V6SenderSession()
    session.prepare_transfer("nav.txt", b"B" * 300)
    assert session.transfer_state == "READY"
    assert session.current_frame_idx == 0
    total = session.total_frames
    assert total > 2
    
    # Next frame steps 0 -> 1
    session.next_frame()
    assert session.current_frame_idx == 1
    
    # Prev frame steps 1 -> 0
    session.prev_frame()
    assert session.current_frame_idx == 0
    
    # Prev frame from 0 wraps 0 -> total - 1
    session.prev_frame()
    assert session.current_frame_idx == total - 1
    
    # Next frame from total - 1 wraps total - 1 -> 0
    session.next_frame()
    assert session.current_frame_idx == 0
    
    # Session ID, frames, and state remain unchanged
    assert session.transfer_state == "READY"
    assert session.get_current_frame_indexes() is not None
    assert len(session.get_current_frame_indexes()) == 400
    
    # Disallowed during SENDING state
    session.start_transfer()
    idx_before = session.current_frame_idx
    session.prev_frame()
    assert session.current_frame_idx == idx_before

