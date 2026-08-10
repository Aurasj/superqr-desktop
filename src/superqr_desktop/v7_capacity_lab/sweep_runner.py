"""Deterministic degradation sweep runner.

For each canonical Phase 1 profile and each degradation type, binary-search
the parameter space to find the first value where pristine replay recovery
fails.  Reports the boundary and the differential diagnosis of *what* failed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

from superqr_desktop.v7_capacity_lab.degradation import (
    BlurDegradation,
    BrightnessContrastDegradation,
    DownsampleDegradation,
    GaussianNoiseDegradation,
    PerspectiveDegradation,
    RollingShutterDegradation,
    SaltPepperNoiseDegradation,
    apply_degradation,
    degradation_name,
    degradation_param,
    DEGRADATION_TYPES,
)
from superqr_desktop.v7_capacity_lab.differential_diagnostics import (
    FailureCategory,
    SweepDiagnosis,
    diagnose_sweep,
)
from superqr_desktop.v7_capacity_lab.replay_decoder import (
    ReplayDecoder,
    ReplayFrameResult,
    _load_png_bgr,
)


# ---------------------------------------------------------------------------
# parameter search ranges
# ---------------------------------------------------------------------------

DEGRADATION_RANGE_SPECS = {
    DownsampleDegradation:    (1.0, 0.05, 0.01),   # (start, end, tolerance)
    BlurDegradation:          (0.0, 20.0, 0.1),
    PerspectiveDegradation:   (0.0, 200.0, 1.0),
    BrightnessContrastDegradation: None,  # multi-param; special-cased
    GaussianNoiseDegradation: (0.0, 128.0, 0.5),
    SaltPepperNoiseDegradation: (0.0, 0.5, 0.001),
    RollingShutterDegradation: (0.0, 0.5, 0.005),
}

FIXED_FRAME_COUNT_DROP_FRACTIONS = [0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0]


def _make_degradation(deg_type, param: float) -> Any:
    """Create a degradation instance from its type and scalar parameter."""
    if deg_type == DownsampleDegradation:
        return DownsampleDegradation(scale=param)
    if deg_type == BlurDegradation:
        return BlurDegradation(sigma=param)
    if deg_type == PerspectiveDegradation:
        return PerspectiveDegradation(max_shift=param)
    if deg_type == GaussianNoiseDegradation:
        return GaussianNoiseDegradation(std=param)
    if deg_type == SaltPepperNoiseDegradation:
        return SaltPepperNoiseDegradation(fraction=param)
    if deg_type == RollingShutterDegradation:
        return RollingShutterDegradation(row_time_ratio=param)
    raise TypeError(f"unsupported degradation: {deg_type.__name__}")


# ---------------------------------------------------------------------------
# single-profile sweep
# ---------------------------------------------------------------------------


def _replay_profile_frames(
    replay: ReplayDecoder,
    profile: str,
    degrade_fn=None,
) -> list[ReplayFrameResult]:
    """Replay all RUNNING frames for one profile, optionally degraded."""
    frames = [
        f for f in replay.expected_frames
        if f["profile"] == profile and f["state"] == "RUNNING"
    ]
    results: list[ReplayFrameResult] = []
    for captured in frames:
        frame_path = replay._frames_dir / captured["file_name"]
        bgr = _load_png_bgr(frame_path)
        if degrade_fn is not None:
            bgr = degrade_fn(bgr)
        result = replay._decoder.analyze(bgr)
        # Build a ReplayFrameResult manually
        decoded = result.envelope is not None
        envelope_match = False
        run_token_match = False
        profile_match = False
        frame_index_match = False
        from superqr_desktop.v7_capacity_lab.run_sync import RunState

        expected_token = int(captured["run_token"])
        expected_profile = str(captured["profile"])
        expected_index = int(captured["frame_index"])
        from superqr_desktop.v7_capacity_lab.phase1_profiles import (
            grid_profiles,
            qr_controls,
        )

        if result.envelope is not None:
            envelope_match = True
            run_token_match = result.envelope.run_token == expected_token
            profile_match = result.profile == expected_profile
            frame_index_match = result.frame_index == expected_index

        non_erased = result.observed_bits - result.erased_bits
        ber = result.bit_errors / non_erased if non_erased else 0.0
        erasure_rate = (
            result.erased_bits / result.observed_bits
            if result.observed_bits else 0.0
        )

        def _expected_bytes(prof: str) -> int:
            grids = grid_profiles()
            if prof in grids:
                return int(grids[prof]["raw_bytes_per_frame"])
            qrs = qr_controls()
            if prof in qrs:
                return int(qrs[prof]["frame_bytes"])
            return 0

        innovative = 0
        if result.raw_valid and result.envelope is not None and result.envelope.state == RunState.RUNNING:
            innovative = _expected_bytes(expected_profile)

        results.append(ReplayFrameResult(
            run_token=expected_token,
            profile=expected_profile,
            frame_index=expected_index,
            expected_state="RUNNING",
            decoded=decoded,
            envelope_match=envelope_match,
            state_match=result.envelope.state == RunState.RUNNING if result.envelope else False,
            profile_match=profile_match,
            frame_index_match=frame_index_match,
            run_token_match=run_token_match,
            raw_valid=result.raw_valid,
            ber=ber,
            erasure_rate=erasure_rate,
            observed_bits=result.observed_bits,
            bit_errors=result.bit_errors,
            erased_bits=result.erased_bits,
            innovative_bytes=innovative,
            expected_innovative_bytes=_expected_bytes(expected_profile),
            failure_reason=result.failure_reason,
            geometry_source=result.geometry_source,
            sync_status=result.sync_status,
            analysis_path=result.path,
        ))
    return results


def _all_passed(results: list[ReplayFrameResult]) -> bool:
    return all(
        r.decoded and r.envelope_match and r.run_token_match
        and r.profile_match and r.frame_index_match
        and r.raw_valid and r.ber == 0.0 and r.erasure_rate == 0.0
        for r in results
    )


def binary_search_boundary(
    replay: ReplayDecoder,
    profile: str,
    deg_type,
    start: float,
    end: float,
    tolerance: float,
    max_iterations: int = 30,
) -> tuple[float | None, list[SweepDiagnosis]]:
    """Binary-search the degradation parameter for the first failure boundary.

    Returns (boundary_value, sweep_history) where boundary_value is None if
    the profile never fails within the search range.
    """
    diagnoses: list[SweepDiagnosis] = []

    # Check pristine first
    pristine_results = _replay_profile_frames(replay, profile)
    if not _all_passed(pristine_results):
        name = degradation_name(_make_degradation(deg_type, start))
        diagnoses.append(diagnose_sweep(pristine_results, name, start))
        return start, diagnoses

    # Check worst-case
    worst = _make_degradation(deg_type, end)
    worst_fn = lambda f: apply_degradation(f, worst)
    worst_results = _replay_profile_frames(replay, profile, worst_fn)
    if _all_passed(worst_results):
        name = degradation_name(worst)
        diagnoses.append(diagnose_sweep(worst_results, name, end))
        return None, diagnoses  # never fails

    # Binary search
    lo, hi = start, end
    for _ in range(max_iterations):
        if hi - lo <= tolerance:
            break
        mid = (lo + hi) / 2.0
        deg = _make_degradation(deg_type, mid)
        degrade_fn = lambda f, d=deg: apply_degradation(f, d)
        results = _replay_profile_frames(replay, profile, degrade_fn)
        name = degradation_name(deg)
        diagnoses.append(diagnose_sweep(results, name, mid))
        if _all_passed(results):
            lo = mid
        else:
            hi = mid

    return hi, diagnoses


# ---------------------------------------------------------------------------
# brightness/contrast 2-D sweep
# ---------------------------------------------------------------------------


def brightness_contrast_boundary(
    replay: ReplayDecoder,
    profile: str,
) -> dict[str, float | None]:
    """Find contrast (alpha) and brightness (beta) failure boundaries separately."""
    results: dict[str, float | None] = {}

    # Contrast reduction: alpha < 1.0, beta = 0
    def _contrast_degraded(alpha: float):
        return lambda f: cv2.convertScaleAbs(f, alpha=alpha, beta=0)

    lo, hi = 0.01, 1.0
    for _ in range(20):
        mid = (lo + hi) / 2.0
        r = _replay_profile_frames(replay, profile, _contrast_degraded(mid))
        if _all_passed(r):
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.005:
            break
    results["contrast_alpha_min"] = lo if lo > 0.02 else None

    # Brightness reduction: alpha = 1.0, beta < 0
    def _brightness_degraded(beta: int):
        return lambda f: cv2.convertScaleAbs(f, alpha=1.0, beta=beta)

    lo, hi = -255, 0
    for _ in range(20):
        mid = (lo + hi) / 2.0
        r = _replay_profile_frames(replay, profile, _brightness_degraded(int(mid)))
        if _all_passed(r):
            hi = mid
        else:
            lo = mid
        if hi - lo < 2.0:
            break
    results["brightness_beta_min"] = lo if lo < -2 else None

    # Brightness increase
    lo, hi = 0, 255
    for _ in range(20):
        mid = (lo + hi) / 2.0
        r = _replay_profile_frames(replay, profile, _brightness_degraded(int(mid)))
        if _all_passed(r):
            lo = mid
        else:
            hi = mid
        if hi - lo < 2.0:
            break
    results["brightness_beta_max"] = hi if hi < 253 else None

    return results


# ---------------------------------------------------------------------------
# frame-drop sweep
# ---------------------------------------------------------------------------


def frame_drop_boundary(
    replay: ReplayDecoder,
    profile: str,
) -> float | None:
    """Find the frame-drop fraction where acquisition breaks.

    Drops frames by removing them from the replay sequence. A dropped frame
    means the receiver sees a missing logical frame.
    """
    frames = [
        f for f in replay.expected_frames
        if f["profile"] == profile and f["state"] == "RUNNING"
    ]
    if len(frames) < 2:
        return None

    for fraction in FIXED_FRAME_COUNT_DROP_FRACTIONS:
        drop_count = int(len(frames) * fraction)
        if drop_count == 0:
            continue
        kept = frames[:-drop_count] if drop_count > 0 else frames
        results = []
        for captured in kept:
            frame_path = replay._frames_dir / captured["file_name"]
            bgr = _load_png_bgr(frame_path)
            result = replay._decoder.analyze(bgr)
            decoded = result.envelope is not None
            if not decoded or not (result.raw_valid if hasattr(result, 'raw_valid') else False):
                results.append(False)
        if not all(results) if results else True:
            return fraction
    return None


# ---------------------------------------------------------------------------
# full campaign sweep
# ---------------------------------------------------------------------------


@dataclass
class ProfileSweepResult:
    profile: str
    boundaries: dict[str, float | None]  # degradation_name → first failure param
    brightness_contrast: dict[str, float | None] = field(default_factory=dict)
    frame_drop_boundary: float | None = None


@dataclass
class CampaignSweepReport:
    capture_manifest_path: str
    profiles: list[ProfileSweepResult]
    summary: dict[str, Any] = field(default_factory=dict)


def run_campaign_sweep(manifest_path: str | Path) -> CampaignSweepReport:
    """Run every degradation sweep against every profile in the capture.

    This is the main entry point for differential analysis.
    """
    replay = ReplayDecoder(manifest_path)
    profiles_in_capture = sorted({
        f["profile"] for f in replay.expected_frames
    })

    profile_results: list[ProfileSweepResult] = []

    for profile in profiles_in_capture:
        boundaries: dict[str, float | None] = {}

        for deg_type in DEGRADATION_TYPES:
            if deg_type == BrightnessContrastDegradation:
                continue  # handled separately

            spec = DEGRADATION_RANGE_SPECS.get(deg_type)
            if spec is None:
                continue
            start, end, tolerance = spec

            boundary, _ = binary_search_boundary(
                replay, profile, deg_type, start, end, tolerance,
            )
            name = degradation_name(_make_degradation(deg_type, start))
            boundaries[name] = boundary

        bc = brightness_contrast_boundary(replay, profile)
        drop = frame_drop_boundary(replay, profile)

        profile_results.append(ProfileSweepResult(
            profile=profile,
            boundaries=boundaries,
            brightness_contrast=bc,
            frame_drop_boundary=drop,
        ))

    # Summary
    per_degradation: dict[str, list[float | None]] = defaultdict(list)
    for pr in profile_results:
        for name, value in pr.boundaries.items():
            per_degradation[name].append(value)
        for name, value in pr.brightness_contrast.items():
            per_degradation[name].append(value)
        per_degradation["frame_drop"].append(pr.frame_drop_boundary)

    summary: dict[str, Any] = {}
    for name, values in per_degradation.items():
        numeric = [v for v in values if v is not None]
        summary[name] = {
            "profiles_tested": len(values),
            "profiles_never_failed": len(values) - len(numeric),
            "min_boundary": min(numeric) if numeric else None,
            "max_boundary": max(numeric) if numeric else None,
            "median_boundary": sorted(numeric)[len(numeric) // 2] if numeric else None,
        }

    return CampaignSweepReport(
        capture_manifest_path=str(manifest_path),
        profiles=profile_results,
        summary=summary,
    )


def format_sweep_report(report: CampaignSweepReport) -> str:
    """Format a CampaignSweepReport for human consumption."""
    lines = [
        f"Campaign sweep: {report.capture_manifest_path}",
        f"{len(report.profiles)} profiles analyzed",
        "",
    ]
    for pr in report.profiles:
        lines.append(f"── {pr.profile} ──")
        for name, boundary in sorted(pr.boundaries.items()):
            if boundary is not None:
                lines.append(f"  {name}: first failure at {boundary}")
            else:
                lines.append(f"  {name}: NEVER FAILED in search range")
        if pr.brightness_contrast:
            lines.append("  brightness/contrast:")
            for k, v in sorted(pr.brightness_contrast.items()):
                status = f"{v:.3f}" if v is not None else "never failed"
                lines.append(f"    {k}: {status}")
        if pr.frame_drop_boundary is not None:
            lines.append(f"  frame_drop: first failure at {pr.frame_drop_boundary:.1%}")
        else:
            lines.append("  frame_drop: never failed")
        lines.append("")

    lines.append("── Campaign summary ──")
    for name, stats in sorted(report.summary.items()):
        lines.append(
            f"  {name}: {stats['profiles_tested']} profiles, "
            f"{stats['profiles_never_failed']} never failed, "
            f"min={stats['min_boundary']}, median={stats['median_boundary']}, "
            f"max={stats['max_boundary']}"
        )
    return "\n".join(lines)
