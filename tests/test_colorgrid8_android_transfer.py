"""Opt-in complete-file interoperability with the actual Android accumulator.

Run with SUPERQR_ANDROID_INTEROP=1, SUPERQR_COLORGRID_DECODER pointing to
the host C++ probe, and JAVA_HOME set for ../superqr-android/gradlew.
Ideal sampled cells are synthetic, not a physical camera/throughput benchmark.
Fixtures live only in pytest's temporary directory, never in either source tree.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest
from PIL import Image

from superqr_desktop.lab.colorgrid8_core import ColorGrid8Profile
from superqr_desktop.lab.colorgrid8_transfer import (
    BLOCK_DATA_BYTES, BLOCK_CRC_BYTES, TRANSPORT_HEADER_SIZE,
    ColorGrid8TransferSession, KIND_DATA, bytes_to_symbols,
    symbols_to_bytes, parse_transport_frame,
)
from test_colorgrid8_native_interop import decode, means

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPERQR_ANDROID_INTEROP") != "1",
    reason="optional Android full-file interoperability gate not enabled",
)


def test_desktop_native_decoder_android_complete_files(tmp_path):
    assert os.environ.get("SUPERQR_COLORGRID_DECODER"), "host native decoder required"
    android = Path(__file__).resolve().parents[2] / "superqr-android"
    image = io.BytesIO()
    Image.new("RGB", (16, 16), (40, 140, 230)).save(image, format="PNG")
    samples = {
        "empty.bin": b"",
        "small.txt": "ColorGrid complete file — offline verification\n".encode(),
        "image.png": image.getvalue(),
        "large.bin": np.random.default_rng(42).integers(0, 256, 1_048_593, dtype=np.uint8).tobytes(),
    }
    cases = []
    for filename, data in samples.items():
        (tmp_path / filename).write_bytes(data)
    for cols, rows in [(240, 216), (336, 288), (384, 336)]:
        profile = ColorGrid8Profile(cols, rows, 30, version=2)
        for filename, data in samples.items():
            with ColorGrid8TransferSession(tmp_path / filename, profile) as sender:
                # Small files: parity-only, with a damaged unused padding block,
                # proves a lost first/final frame is recoverable.
                # Large: every data frame has a bad but different block in its XOR group;
                # parity itself has one irrelevant corrupt block. Reverse delivery so
                # the final group arrives before the package header. Include duplicates.
                paths = []
                for index in range(sender.carousel_frames - 1, -1, -1):
                    kind, frame_id = sender._schedule_item(index)
                    if filename != "large.bin" and kind == KIND_DATA:
                        continue
                    stats, symbols = decode(means(sender.symbol_frame(index)), profile)
                    assert stats[:3] == (1, 6, index)  # success, payload stage, optical frame index
                    raw = symbols_to_bytes(symbols)
                    assert parse_transport_frame(profile, raw) is not None
                    block = frame_id % 8 if kind == KIND_DATA else 10
                    corrupt = bytearray(raw)
                    offset = TRANSPORT_HEADER_SIZE + block * (BLOCK_DATA_BYTES + BLOCK_CRC_BYTES)
                    # All transmitted frames in this fixture include these blocks.
                    corrupt[offset] ^= 1
                    symbols = bytes_to_symbols(bytes(corrupt))
                    path = f"{cols}-{filename}-{index}.symbols"
                    (tmp_path / path).write_bytes(symbols.tobytes())
                    paths.extend([path, path])
                cases.append({
                    "name": f"{cols}x{rows}/{filename}", "cols": cols, "rows": rows,
                    "filename": filename, "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "source": filename, "frames": paths,
                })
    (tmp_path / "manifest.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
    env = os.environ.copy()
    env["SUPERQR_COLORGRID_FIXTURE_DIR"] = str(tmp_path)
    wrapper = android / ("gradlew.bat" if os.name == "nt" else "gradlew")
    result = subprocess.run(
        [str(wrapper), ":app:testDebugUnitTest", "--tests",
         "*ColorGrid8TransferAccumulatorTest.desktopSenderFixturesVerifyThroughAndroidReceiver",
         "--rerun", "--console=plain", "--no-configuration-cache"],
        cwd=android, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # An accidentally skipped test is NOT an interoperability pass.
    from xml.etree import ElementTree
    report = android / "app/build/test-results/testDebugUnitTest/TEST-com.superqr.android.colorgrid8.ColorGrid8TransferAccumulatorTest.xml"
    root = ElementTree.parse(report).getroot()
    assert root.attrib["tests"] == "1" and root.attrib["skipped"] == "0"
    assert root.attrib["failures"] == "0" and root.attrib["errors"] == "0"
    print(f"Verified {len(cases)} complete Desktop -> native -> Android fixtures, exact bytes + CRC32 + SHA-256")
