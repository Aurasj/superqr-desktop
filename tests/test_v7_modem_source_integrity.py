from __future__ import annotations

import os

import pytest

from superqr_desktop.v7.modem_sender import V7ModemSender
from superqr_desktop.v7.package_stream import COMPRESSION_DEFLATE_RAW, PackageSourceError, PreparedPackageSource


def test_pass_through_source_mutation_is_rejected_before_generation_read(tmp_path):
    path = tmp_path / "entropy.bin"
    path.write_bytes(os.urandom(300000))
    source = PreparedPackageSource.prepare(str(path), allow_compression=False)
    try:
        with path.open("ab") as handle:
            handle.write(b"changed")
        with pytest.raises(PackageSourceError, match="changed"):
            V7ModemSender(source, channel_bytes=400)
    finally:
        source.close()


def test_compressed_spool_is_stable_even_if_original_changes_after_prepare(tmp_path):
    path = tmp_path / "compressible.txt"
    path.write_bytes(b"SuperQR stable compressed spool\n" * 20000)
    source = PreparedPackageSource.prepare(str(path))
    try:
        assert source.info.compression_id == COMPRESSION_DEFLATE_RAW
        package_size = source.size
        path.write_bytes(b"replacement contents")
        sender = V7ModemSender(source, channel_bytes=400, session_id=0x12345678)
        frame = sender.next_physical_frame()
        assert len(frame) == 400
        assert sender.source.size == package_size
    finally:
        source.close()
