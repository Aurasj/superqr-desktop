"""Build the lab-only focused QR ECC mapping campaign."""

from __future__ import annotations

from superqr_desktop.v7_capacity_lab.campaign import RunSpec
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_qr_ecc_map_manifest


def build_qr_ecc_map_runs(dwell: int, frames: int) -> list[RunSpec]:
    manifest = load_qr_ecc_map_manifest()
    campaign = manifest["campaign"]
    expected_frames = int(campaign["frame_count"])
    if frames != expected_frames:
        # UI still owns the frame-count control, but this experiment's evidence
        # and run ordering are defined for the canonical 256-frame sample.
        frames = expected_frames

    runs = [
        RunSpec(
            str(item["profile"]),
            dwell,
            frames,
            target_fps=float(item["target_fps"]),
        )
        for item in campaign["runs"]
    ]
    expected = int(campaign["run_count"])
    if len(runs) != expected:
        raise RuntimeError(
            f"QR ECC map run count mismatch: built {len(runs)}, expected {expected}"
        )
    if max(run.target_fps or 0.0 for run in runs) > 30.0:
        raise RuntimeError("QR ECC map must not exceed the selected 30 FPS ceiling")
    return runs
