"""Build the lab-only QR capacity/cadence mapping campaign."""

from __future__ import annotations

from superqr_desktop.v7_capacity_lab.campaign import RunSpec
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_qr_capacity_map_manifest


def build_qr_capacity_map_runs(dwell: int, frames: int) -> list[RunSpec]:
    manifest = load_qr_capacity_map_manifest()
    campaign = manifest["campaign"]
    profile_order = list(campaign["profile_order"])
    fps_candidates = [float(value) for value in campaign["fps_candidates"]]
    control = campaign["stability_control"]

    runs: list[RunSpec] = []
    for block_index, profile in enumerate(profile_order):
        runs.extend(
            RunSpec(profile, dwell, frames, target_fps=fps)
            for fps in fps_candidates
        )
        if (
            campaign.get("interleave_control_between_profile_blocks", False)
            and block_index + 1 < len(profile_order)
        ):
            runs.append(RunSpec(
                str(control["profile"]),
                dwell,
                frames,
                target_fps=float(control["target_fps"]),
            ))

    expected = int(campaign["run_count"])
    if len(runs) != expected:
        raise RuntimeError(
            f"QR capacity map run count mismatch: built {len(runs)}, expected {expected}"
        )
    return runs
