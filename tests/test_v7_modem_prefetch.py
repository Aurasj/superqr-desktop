from __future__ import annotations

import os
import time

import pytest

from superqr_desktop.v7.modem_pump import V7ModemFramePump
from superqr_desktop.v7.modem_sender import V7ModemSender
from superqr_desktop.v7.package_stream import PreparedPackageSource


def test_dense_xor_v1_rejects_private_generation_target(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(os.urandom(4096))
    with PreparedPackageSource.prepare(str(path), allow_compression=False) as source:
        with pytest.raises(ValueError, match="128 KiB"):
            V7ModemSender(source, channel_bytes=400, target_generation_bytes=64 * 1024)


def test_prefetch_queue_is_bounded_ordered_and_fixed_channel_size(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(os.urandom(300000))
    source = PreparedPackageSource.prepare(str(path), allow_compression=False)
    sender = V7ModemSender(source, channel_bytes=400, session_id=0x44556677)
    pump = V7ModemFramePump(sender, lookahead_frames=3)
    try:
        pump.start()
        deadline = time.monotonic() + 3.0
        while pump.snapshot().queued_frames < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = pump.snapshot()
        assert snapshot.error is None
        assert snapshot.queued_frames <= 3
        frames = [pump.take(timeout=1.0) for _ in range(8)]
        assert all(len(frame.channel_bytes) == 400 for frame in frames)
        assert len({(frame.generation_id, frame.symbol_id) for frame in frames}) == len(frames)
        assert [(frame.generation_id, frame.symbol_id) for frame in frames[:4]] == [(0, 0), (0, 1), (0, 2), (0, 3)]
        assert pump.snapshot().queued_frames <= 3
    finally:
        pump.stop(close_sender=True)
