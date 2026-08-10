"""Differential diagnostics: classify *why* a replayed frame failed.

Given a ReplayFrameResult and its expected truth, this module identifies
which component failed: acquisition, optical synchronization, payload
sampling, QR decoding, frame loss, or forward error correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureCategory(str, Enum):
    """Granular failure classification for differential analysis."""

    OK = "OK"
    ACQUISITION = "ACQUISITION"
    SYNC = "SYNC"
    PAYLOAD_SAMPLING = "PAYLOAD_SAMPLING"
    QR_DECODING = "QR_DECODING"
    FRAME_LOSS = "FRAME_LOSS"
    FEC = "FEC"


@dataclass
class FrameDiagnosis:
    """Why a single frame did or did not pass."""

    run_token: int
    profile: str
    frame_index: int
    passed: bool
    category: FailureCategory
    detail: str
    decoded: bool = False
    envelope_match: bool = False
    raw_valid: bool = False
    ber: float = 0.0
    erasure_rate: float = 0.0


@dataclass
class SweepDiagnosis:
    """Diagnostic breakdown for one degradation sweep across frames."""

    degradation_type: str
    degradation_param: float
    total_frames: int
    passed: int
    failed: int
    categories: dict[str, int] = field(default_factory=dict)
    frame_diagnoses: list[FrameDiagnosis] = field(default_factory=list)
    first_failure_boundary: float | None = None

    @property
    def acquisition_failures(self) -> int:
        return self.categories.get(FailureCategory.ACQUISITION.value, 0)

    @property
    def sync_failures(self) -> int:
        return self.categories.get(FailureCategory.SYNC.value, 0)

    @property
    def payload_sampling_failures(self) -> int:
        return self.categories.get(FailureCategory.PAYLOAD_SAMPLING.value, 0)

    @property
    def qr_decoding_failures(self) -> int:
        return self.categories.get(FailureCategory.QR_DECODING.value, 0)

    @property
    def frame_loss_failures(self) -> int:
        return self.categories.get(FailureCategory.FRAME_LOSS.value, 0)

    @property
    def fec_failures(self) -> int:
        return self.categories.get(FailureCategory.FEC.value, 0)


def diagnose_frame(result: "ReplayFrameResult") -> FrameDiagnosis:
    """Classify a single replayed frame result."""
    from superqr_desktop.v7_capacity_lab.replay_decoder import ReplayFrameResult

    # Perfect
    if (
        result.decoded
        and result.envelope_match
        and result.run_token_match
        and result.profile_match
        and result.frame_index_match
        and result.raw_valid
        and result.ber == 0.0
        and result.erasure_rate == 0.0
    ):
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=True,
            category=FailureCategory.OK,
            detail="perfect recovery",
            decoded=True,
            envelope_match=True,
            raw_valid=True,
            ber=0.0,
            erasure_rate=0.0,
        )

    # Frame loss: nothing decoded at all
    if not result.decoded:
        detail = result.failure_reason or "no envelope decoded"
        if result.geometry_source in ("NONE",):
            return FrameDiagnosis(
                run_token=result.run_token,
                profile=result.profile,
                frame_index=result.frame_index,
                passed=False,
                category=FailureCategory.ACQUISITION,
                detail=f"acquisition failure: {detail}",
                decoded=False,
                ber=result.ber,
                erasure_rate=result.erasure_rate,
            )
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.FRAME_LOSS,
            detail=f"frame lost after geometry: {detail}",
            decoded=False,
            envelope_match=False,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # Envelope decoded but wrong identity → sync failure (false lock)
    if not result.run_token_match or not result.profile_match:
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.SYNC,
            detail=(
                f"sync mismatch: token={result.run_token_match}, "
                f"profile={result.profile_match}"
            ),
            decoded=True,
            envelope_match=False,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # Envelope correct but frame index wrong → sync
    if not result.frame_index_match:
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.SYNC,
            detail=f"frame index mismatch",
            decoded=True,
            envelope_match=True,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # QR specific failures
    if result.analysis_path == "QR" and result.failure_reason and "QR_" in (result.failure_reason or ""):
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.QR_DECODING,
            detail=f"QR decode failure: {result.failure_reason}",
            decoded=True,
            envelope_match=True,
            raw_valid=False,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # Envelope correct but BER > 0 or erasures > 0 → payload sampling
    if result.ber > 0.0 or result.erasure_rate > 0.0:
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.PAYLOAD_SAMPLING,
            detail=(
                f"payload sampling errors: BER={result.ber:.4%}, "
                f"erasures={result.erasure_rate:.4%}, "
                f"errors={result.bit_errors}, erased={result.erased_bits}"
            ),
            decoded=True,
            envelope_match=True,
            raw_valid=result.raw_valid,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # Raw valid but innovatives don't match → FEC-level issue
    if not result.raw_valid:
        return FrameDiagnosis(
            run_token=result.run_token,
            profile=result.profile,
            frame_index=result.frame_index,
            passed=False,
            category=FailureCategory.FEC,
            detail=f"raw validation failed",
            decoded=True,
            envelope_match=True,
            raw_valid=False,
            ber=result.ber,
            erasure_rate=result.erasure_rate,
        )

    # Catch-all
    return FrameDiagnosis(
        run_token=result.run_token,
        profile=result.profile,
        frame_index=result.frame_index,
        passed=False,
        category=FailureCategory.FRAME_LOSS,
        detail=f"unclassified: {result.failure_reason or 'unknown'}",
        decoded=result.decoded,
        envelope_match=result.envelope_match,
        raw_valid=result.raw_valid,
        ber=result.ber,
        erasure_rate=result.erasure_rate,
    )


def diagnose_sweep(frame_results: list, degradation_type: str, degradation_param: float) -> SweepDiagnosis:
    """Diagnose every frame in a degradation sweep."""
    diagnoses = [diagnose_frame(r) for r in frame_results]
    categories: dict[str, int] = {}
    for d in diagnoses:
        key = d.category.value
        categories[key] = categories.get(key, 0) + 1

    passed = sum(1 for d in diagnoses if d.passed)
    failed = len(diagnoses) - passed

    return SweepDiagnosis(
        degradation_type=degradation_type,
        degradation_param=degradation_param,
        total_frames=len(frame_results),
        passed=passed,
        failed=failed,
        categories=categories,
        frame_diagnoses=diagnoses,
        first_failure_boundary=degradation_param if failed > 0 else None,
    )
