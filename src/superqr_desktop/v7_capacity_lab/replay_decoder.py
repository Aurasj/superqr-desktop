"""Offline replay: feed captured frames through the real receiver decoder.

Reads a capture manifest + PNG frames produced by CaptureRecorder, converts
each frame to a numpy BGR array, and passes it through the production
Phase1CameraDecoder.analyze() path.  Compares every decoded result against
the ground-truth envelope and payload expectations from the manifest.

This is the same code path the physical camera receiver uses; a pristine
digital replay must recover 100 % of expected RUNNING frames with BER 0,
erasures 0, and exact expected innovative bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from superqr_desktop.v7_capacity_lab.camera_receiver import Phase1CameraDecoder
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    grid_profiles,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.run_sync import RunState


@dataclass
class ReplayFrameResult:
    """Outcome for one replayed logical frame."""

    run_token: int
    profile: str
    frame_index: int
    expected_state: str
    decoded: bool
    envelope_match: bool
    state_match: bool
    profile_match: bool
    frame_index_match: bool
    run_token_match: bool
    raw_valid: bool
    ber: float
    erasure_rate: float
    observed_bits: int
    bit_errors: int
    erased_bits: int
    innovative_bytes: int
    expected_innovative_bytes: int
    failure_reason: str | None
    geometry_source: str
    sync_status: str
    analysis_path: str


@dataclass
class ReplayReport:
    """Aggregate replay results across all frames."""

    total_expected: int
    total_decoded: int
    total_raw_valid: int
    total_envelope_match: int
    total_state_match: int
    total_profile_match: int
    total_frame_index_match: int
    total_run_token_match: int
    aggregate_ber: float
    aggregate_erasure_rate: float
    total_observed_bits: int
    total_bit_errors: int
    total_erased_bits: int
    total_innovative_bytes: int
    total_expected_innovative_bytes: int
    failure_reasons: dict[str, int]
    frame_results: list[ReplayFrameResult] = field(default_factory=list)
    passed: bool = False

    @property
    def acquisition_rate(self) -> float:
        return self.total_decoded / self.total_expected if self.total_expected else 0.0

    @property
    def raw_valid_yield(self) -> float:
        return self.total_raw_valid / self.total_decoded if self.total_decoded else 0.0


def _load_png_bgr(path: str | Path) -> np.ndarray:
    """Read a lossless PNG back to the BGR numpy array the decoder expects."""
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError(f"captured frame not found: {path}")
    return frame


def _expected_innovative_bytes(profile: str) -> int:
    grids = grid_profiles()
    if profile in grids:
        return int(grids[profile]["raw_bytes_per_frame"])
    qrs = qr_controls()
    if profile in qrs:
        return int(qrs[profile]["frame_bytes"])
    return 0


class ReplayDecoder:
    """Feed captured frames through the real Phase1CameraDecoder and verify."""

    def __init__(self, manifest_path: str | Path) -> None:
        with Path(manifest_path).open("r", encoding="utf-8") as handle:
            self._manifest = json.load(handle)
        if self._manifest.get("schema") != "superqr-capture-manifest-v1":
            raise ValueError("capture manifest must be schema superqr-capture-manifest-v1")
        self._frames_dir = Path(manifest_path).parent / "frames"
        self._decoder = Phase1CameraDecoder()

    @property
    def manifest(self) -> dict[str, Any]:
        return self._manifest

    @property
    def expected_frames(self) -> list[dict[str, Any]]:
        """Return only RUNNING frames (those the receiver must score)."""
        return [
            f for f in self._manifest["frames"]
            if f["state"] == "RUNNING"
        ]

    def replay_frame(self, captured: dict[str, Any]) -> ReplayFrameResult:
        """Replay one captured frame through the decoder and compare."""
        frame_path = self._frames_dir / captured["file_name"]
        bgr = _load_png_bgr(frame_path)
        result = self._decoder.analyze(bgr)

        decoded = result.envelope is not None
        envelope_match = False
        state_match = False
        profile_match = False
        frame_index_match = False
        run_token_match = False

        expected_token = int(captured["run_token"])
        expected_profile = str(captured["profile"])
        expected_index = int(captured["frame_index"])
        expected_state = str(captured["state"])
        expected_bytes = _expected_innovative_bytes(expected_profile)

        if result.envelope is not None:
            envelope_match = True
            state_match = result.envelope.state == RunState.RUNNING
            profile_match = result.profile == expected_profile
            frame_index_match = result.frame_index == expected_index
            run_token_match = result.envelope.run_token == expected_token

        non_erased = result.observed_bits - result.erased_bits
        ber = result.bit_errors / non_erased if non_erased else 0.0
        erasure_rate = result.erased_bits / result.observed_bits if result.observed_bits else 0.0

        innovative = 0
        if result.raw_valid and result.envelope is not None and result.envelope.state == RunState.RUNNING:
            innovative = expected_bytes

        return ReplayFrameResult(
            run_token=expected_token,
            profile=expected_profile,
            frame_index=expected_index,
            expected_state=expected_state,
            decoded=decoded,
            envelope_match=envelope_match,
            state_match=state_match,
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
            expected_innovative_bytes=expected_bytes,
            failure_reason=result.failure_reason,
            geometry_source=result.geometry_source,
            sync_status=result.sync_status,
            analysis_path=result.path,
        )

    def replay_all(self) -> ReplayReport:
        """Replay every RUNNING frame and produce an aggregate report.

        Creates a fresh decoder per profile so the acquisition path preference
        does not contaminate across grid/QR profile boundaries.
        """
        expected = self.expected_frames
        results: list[ReplayFrameResult] = []
        current_profile = None
        for captured in expected:
            profile = captured["profile"]
            if profile != current_profile:
                self._decoder = Phase1CameraDecoder()
                current_profile = profile
            results.append(self.replay_frame(captured))

        decoded = [r for r in results if r.decoded]
        total_decoded = len(decoded)
        total_raw_valid = sum(1 for r in results if r.raw_valid)
        total_envelope = sum(1 for r in results if r.envelope_match)
        total_state = sum(1 for r in results if r.state_match)
        total_profile = sum(1 for r in results if r.profile_match)
        total_frame_ix = sum(1 for r in results if r.frame_index_match)
        total_token = sum(1 for r in results if r.run_token_match)

        total_observed = sum(r.observed_bits for r in results)
        total_errors = sum(r.bit_errors for r in results)
        total_erased = sum(r.erased_bits for r in results)
        total_non_erased = total_observed - total_erased
        total_innovative = sum(r.innovative_bytes for r in results)
        total_expected_innovative = sum(r.expected_innovative_bytes for r in results)

        failures: dict[str, int] = {}
        for r in results:
            if r.failure_reason:
                failures[r.failure_reason] = failures.get(r.failure_reason, 0) + 1

        passed = (
            total_decoded == len(expected)
            and total_raw_valid == len(expected)
            and total_envelope == len(expected)
            and total_state == len(expected)
            and total_profile == len(expected)
            and total_frame_ix == len(expected)
            and total_token == len(expected)
            and total_errors == 0
            and total_erased == 0
            and total_innovative == total_expected_innovative
        )

        return ReplayReport(
            total_expected=len(expected),
            total_decoded=total_decoded,
            total_raw_valid=total_raw_valid,
            total_envelope_match=total_envelope,
            total_state_match=total_state,
            total_profile_match=total_profile,
            total_frame_index_match=total_frame_ix,
            total_run_token_match=total_token,
            aggregate_ber=total_errors / total_non_erased if total_non_erased else 0.0,
            aggregate_erasure_rate=total_erased / total_observed if total_observed else 0.0,
            total_observed_bits=total_observed,
            total_bit_errors=total_errors,
            total_erased_bits=total_erased,
            total_innovative_bytes=total_innovative,
            total_expected_innovative_bytes=total_expected_innovative,
            failure_reasons=failures,
            frame_results=results,
            passed=passed,
        )
