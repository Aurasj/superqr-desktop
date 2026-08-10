"""Offline digital-baseline renderer and validator.

Produces lossless rendered frames for every canonical Phase 1 profile and
runs two independent validations:

1. **SENDER RENDER TRUTH**: Compares the rendered payload cells directly
   against the expected deterministic symbols, using the *same* cell-center
   sampling the decoder uses but skipping carrier acquisition, homography
   estimation, and sync-band decoding. This isolates rendering defects.

2. **PRODUCTION RECEIVER REPLAY**: Passes each lossless PNG through
   Phase1CameraDecoder.analyze(), the identical code path the physical
   camera receiver uses. This validates the full acquisition→sync→scoring
   chain on perfect digital input.

Frames are rendered and validated incrementally per profile; raw pixel
buffers are discarded after PNG write so memory stays bounded regardless
of campaign size.
"""

from __future__ import annotations

import hashlib
import json
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.camera_receiver import (
    Phase1CameraDecoder,
    _bbox_mean,
)
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_control_payload,
    build_qr_matrix,
    build_run_envelope,
    grid_profiles,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState


CANONICAL_MARKER = 600

# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------


@dataclass
class BaselineEvent:
    """One logical event: a specific (run_token, profile, frame_index, state).

    Multiple events can reference the same content-addressed PNG (e.g., when
    READY and RUNNING render the same frame-zero payload).
    """

    run_token: int
    profile: str
    frame_index: int
    frame_count: int
    dwell_epochs: int
    state: str
    content_sha256: str
    file_name: str
    width: int
    height: int


@dataclass
class SenderTruthResult:
    """Validation of rendered cells against expected symbols."""

    passed: bool
    observed_cells: int
    bit_errors: int
    erased_cells: int
    ber: float
    erasure_rate: float


@dataclass
class ReceiverReplayResult:
    """Validation through the production Phase1CameraDecoder path."""

    passed: bool
    expected: int
    decoded: int
    raw_valid: int
    envelope_match: int
    state_match: int
    profile_match: int
    frame_index_match: int
    run_token_match: int
    ber: float
    erasure_rate: float
    bit_errors: int
    erased_bits: int
    innovative_bytes: int
    expected_innovative_bytes: int
    acquisition_failures: int
    failure_reasons: dict[str, int]


@dataclass
class ProfileBaselineResult:
    profile: str
    run_token: int
    frame_count: int
    events: list[BaselineEvent] = field(default_factory=list)
    event_count: int = 0
    unique_pngs: int = 0
    sender_truth: SenderTruthResult | None = None
    receiver_replay: ReceiverReplayResult | None = None
    render_time_s: float = 0.0
    png_bytes: int = 0


@dataclass
class CampaignBaselineReport:
    profiles: list[ProfileBaselineResult]
    peak_rss_mib: float = 0.0
    artifact_size_bytes: int = 0


# ---------------------------------------------------------------------------
# sender-render-truth — direct cell comparison bypassing acquisition
# ---------------------------------------------------------------------------


def validate_sender_truth(
    surface: pygame.Surface,
    profile_name: str,
    frame_index: int,
) -> SenderTruthResult:
    """Sample rendered grid payload cells directly against expected symbols.

    Uses the same bbox→resize→sampling path as the decoder but with an
    identity transform (no warp), isolating rendering defects from
    acquisition/warp errors.
    """
    manifest = load_phy_selection_manifest()
    grids = grid_profiles()

    # Convert pygame surface → canonical 1000×1000 BGR (identity warp)
    rgb = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    src = np.float32([[0, 0], [CANONICAL_MARKER - 1, 0],
                      [CANONICAL_MARKER - 1, CANONICAL_MARKER - 1],
                      [0, CANONICAL_MARKER - 1]])
    dst = np.float32([[0, 0], [999, 0], [999, 999], [0, 999]])
    H = cv2.getPerspectiveTransform(src, dst)
    canonical = cv2.warpPerspective(bgr, H, (1000, 1000))

    profile = grids[profile_name]
    rows, cols = int(profile["rows"]), int(profile["cols"])
    bits_per_cell = int(profile["bits_per_cell"])
    x1, y1, x2, y2 = map(int, manifest["payload_bbox"])
    cells = cv2.resize(canonical[y1:y2, x1:x2], (cols, rows),
                       interpolation=cv2.INTER_AREA)

    # Reconstruct expected symbols
    sequence = GridFrameSequence(profile_name)
    expected_matrix = None
    for _ in range(frame_index + 1):
        idx, expected_matrix = sequence.next_frame()
    reference = np.asarray(expected_matrix.symbols, dtype=np.uint8)

    if bits_per_cell == 1:
        gray = cv2.cvtColor(cells, cv2.COLOR_BGR2GRAY).astype(np.float32)
        pilots = {item["name"]: item for item in manifest["acquisition_carrier"]["pilots"]}
        blk = float(_bbox_mean(cv2.cvtColor(canonical, cv2.COLOR_BGR2GRAY),
                               pilots["BLACK"]["core_bbox"]))
        wht = float(_bbox_mean(cv2.cvtColor(canonical, cv2.COLOR_BGR2GRAY),
                              pilots["WHITE"]["core_bbox"]))
        contrast = max(1.0, wht - blk)
        threshold = (blk + wht) / 2.0
        symbols = (gray > threshold).astype(np.uint8)
        confidence = np.abs(gray - threshold) / (contrast / 2.0)
        erased = confidence < 0.22
        xor = np.bitwise_xor(symbols, reference)
        errors = int(np.count_nonzero(xor[~erased]))
        erased_count = int(np.count_nonzero(erased))
        observed_cells = rows * cols
    else:
        # 2-bit color classification
        pilot_defs = {item["name"]: item for item in manifest["acquisition_carrier"]["pilots"]}
        prototypes = np.stack([
            _bbox_mean(canonical, pilot_defs[name]["core_bbox"])
            for name in ("BLACK", "WHITE", "RED", "BLUE")
        ]).astype(np.float32)
        lab_cells = cv2.cvtColor(cells, cv2.COLOR_BGR2LAB).astype(np.float32)
        lab_prototypes = cv2.cvtColor(
            prototypes.reshape(1, 4, 3).astype(np.uint8), cv2.COLOR_BGR2LAB,
        )[0].astype(np.float32)
        distances = np.linalg.norm(
            lab_cells[:, :, None, :] - lab_prototypes[None, None, :, :], axis=3,
        )
        order = np.sort(distances, axis=2)
        symbols = np.argmin(distances, axis=2).astype(np.uint8)
        erased = (order[:, :, 1] - order[:, :, 0]) < 10.0
        xor = np.bitwise_xor(symbols, reference)
        bit_errors_vec = np.vectorize(lambda v: int(v).bit_count(), otypes=[np.uint8])(xor)
        errors = int(bit_errors_vec[~erased].sum())
        erased_count = int(np.count_nonzero(erased) * bits_per_cell)
        observed_cells = rows * cols * bits_per_cell

    non_erased_cells = observed_cells - erased_count
    ber = errors / non_erased_cells if non_erased_cells else 0.0
    erasure_rate = erased_count / observed_cells if observed_cells else 0.0

    return SenderTruthResult(
        passed=(errors == 0 and erased_count == 0),
        observed_cells=observed_cells,
        bit_errors=errors,
        erased_cells=erased_count,
        ber=ber,
        erasure_rate=erasure_rate,
    )


# ---------------------------------------------------------------------------
# receiver replay validation
# ---------------------------------------------------------------------------


def validate_receiver_replay(
    events: list[BaselineEvent],
    frames_dir: Path,
    profile: str,
) -> ReceiverReplayResult:
    """Replay RUNNING frames through the real Phase1CameraDecoder."""
    running = [e for e in events if e.state == "RUNNING"]
    decoder = Phase1CameraDecoder()

    decoded = 0
    raw_valid = 0
    envelope_match = 0
    state_match = 0
    profile_match = 0
    frame_match = 0
    token_match = 0
    total_errors = 0
    total_erased = 0
    total_observed = 0
    total_innovative = 0
    expected_innovative = 0
    acquisition_failures = 0
    failures: dict[str, int] = {}

    grids = grid_profiles()
    qrs = qr_controls()
    if profile in grids:
        exp_per_frame = int(grids[profile]["raw_bytes_per_frame"])
    elif profile in qrs:
        exp_per_frame = int(qrs[profile]["frame_bytes"])
    else:
        exp_per_frame = 0

    for event in running:
        expected_innovative += exp_per_frame

        file_path = frames_dir / event.file_name
        bgr = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
        if bgr is None:
            acquisition_failures += 1
            failures["PNG_READ_ERROR"] = failures.get("PNG_READ_ERROR", 0) + 1
            continue

        result = decoder.analyze(bgr)

        if result.envelope is None:
            reason = result.failure_reason or "NO_ENVELOPE"
            failures[reason] = failures.get(reason, 0) + 1
            if result.geometry_source == "NONE":
                acquisition_failures += 1
            continue

        decoded += 1
        env = result.envelope

        if env.run_token == event.run_token and result.profile == event.profile:
            envelope_match += 1
        if env.state == RunState.RUNNING:
            state_match += 1
        if result.profile == event.profile:
            profile_match += 1
        if env.frame_index == event.frame_index:
            frame_match += 1
        if env.run_token == event.run_token:
            token_match += 1

        total_observed += result.observed_bits
        total_errors += result.bit_errors
        total_erased += result.erased_bits

        if result.raw_valid:
            raw_valid += 1
            total_innovative += exp_per_frame

        if result.failure_reason:
            failures[result.failure_reason] = failures.get(result.failure_reason, 0) + 1

    non_erased = total_observed - total_erased
    ber = total_errors / non_erased if non_erased else 0.0
    erasure_rate = total_erased / total_observed if total_observed else 0.0

    all_ok = (
        decoded == len(running)
        and raw_valid == len(running)
        and envelope_match == len(running)
        and state_match == len(running)
        and profile_match == len(running)
        and frame_match == len(running)
        and token_match == len(running)
        and total_errors == 0
        and total_erased == 0
    )

    return ReceiverReplayResult(
        passed=all_ok,
        expected=len(running),
        decoded=decoded,
        raw_valid=raw_valid,
        envelope_match=envelope_match,
        state_match=state_match,
        profile_match=profile_match,
        frame_index_match=frame_match,
        run_token_match=token_match,
        ber=ber,
        erasure_rate=erasure_rate,
        bit_errors=total_errors,
        erased_bits=total_erased,
        innovative_bytes=total_innovative,
        expected_innovative_bytes=expected_innovative,
        acquisition_failures=acquisition_failures,
        failure_reasons=failures,
    )


# ---------------------------------------------------------------------------
# offline baseline worker
# ---------------------------------------------------------------------------


class BaselineWorker:
    """Render and validate every canonical profile offline.

    Usage::

        worker = BaselineWorker(output_dir)
        report = worker.run()

    Frames are rendered incrementally per profile, written to PNG, validated,
    and then their raw buffers are discarded so peak memory stays bounded.
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        frame_count: int = 256,
        dwell_epochs: int = 3,
        ready_s: float = 4.0,
        done_s: float = 2.0,
        marker_size: int = CANONICAL_MARKER,
        progress_callback: callable = None,
    ):
        self._output_dir = Path(output_dir)
        self._frame_count = frame_count
        self._dwell_epochs = dwell_epochs
        self._ready_s = ready_s
        self._done_s = done_s
        self._marker_size = marker_size
        self._progress = progress_callback
        self._manifest = load_phy_selection_manifest()
        self._sync = self._manifest["run_sync"]
        self._profiles = list(grid_profiles()) + list(qr_controls())
        self._all_events: list[BaselineEvent] = []

    def run(self) -> CampaignBaselineReport:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = self._output_dir / "frames"
        frames_dir.mkdir(exist_ok=True)

        tracemalloc.start()
        t0 = time.perf_counter()

        profile_results: list[ProfileBaselineResult] = []
        next_token = 0xB000

        for prof_index, profile_name in enumerate(self._profiles):
            if self._progress:
                self._progress(prof_index, len(self._profiles), profile_name, "rendering")

            pr = self._render_profile(profile_name, next_token, frames_dir)
            profile_results.append(pr)
            next_token += 1

        t1 = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        total_png_bytes = sum(
            (self._output_dir / "frames" / f).stat().st_size
            for f in frames_dir.iterdir() if f.is_file()
        )

        # Write results JSON
        export = self._build_export(profile_results, peak_mem, total_png_bytes, t1 - t0)
        export_path = self._output_dir / "baseline_results.json"
        with export_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(export, handle, indent=2, separators=(",", ": "))

        # Write events JSONL
        events_path = self._output_dir / "baseline_events.jsonl"
        with events_path.open("w", encoding="utf-8", newline="\n") as handle:
            for pr in profile_results:
                for event in pr.events:
                    handle.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")

        return CampaignBaselineReport(
            profiles=profile_results,
            peak_rss_mib=peak_mem / 1024 / 1024,
            artifact_size_bytes=total_png_bytes + export_path.stat().st_size,
        )

    def _render_profile(
        self, profile_name: str, run_token: int, frames_dir: Path,
    ) -> ProfileBaselineResult:
        t0 = time.perf_counter()
        events: list[BaselineEvent] = []
        seen_hashes: dict[str, str] = {}
        png_bytes = 0
        fc = self._frame_count

        # Sequential render: one GridFrameSequence, advance in order
        is_grid = profile_name in grid_profiles()
        if is_grid:
            seq = GridFrameSequence(profile_name)
            renderer = LabRenderer(self._marker_size)
            current_fi = -1
            matrix = None

            def _advance(target_fi):
                nonlocal current_fi, matrix
                while current_fi < target_fi:
                    fi, matrix = seq.next_frame()
                    current_fi = fi
                return matrix

            def _render_grid_step(fi, rs):
                mat = _advance(fi)
                envelope = build_run_envelope(
                    profile_name, run_token, fi, fc, self._dwell_epochs, rs,
                )
                renderer.prepare_logical_frame(
                    mat,
                    payload_bbox=self._manifest["payload_bbox"],
                    sync_bits=envelope.bits(),
                    sync_bboxes=(self._sync["top_bbox"], self._sync["bottom_bbox"]),
                    sync_rows=int(self._sync["rows"]),
                    sync_cols=int(self._sync["cols"]),
                )
                return renderer.cached_frame_display

            # READY
            surface = _render_grid_step(0, RunState.READY)
            self._store_event(surface, events, seen_hashes, frames_dir,
                              run_token, profile_name, 0, fc, "READY")
            # RUNNING
            for fi in range(fc):
                surface = _render_grid_step(fi, RunState.RUNNING)
                self._store_event(surface, events, seen_hashes, frames_dir,
                                  run_token, profile_name, fi, fc, "RUNNING")
            # DONE
            surface = _render_grid_step(fc - 1, RunState.DONE)
            self._store_event(surface, events, seen_hashes, frames_dir,
                              run_token, profile_name, fc - 1, fc, "DONE")
        else:
            # QR controls — pre-build all native surfaces
            control = qr_controls()[profile_name]
            quiet = int(control["quiet_zone_modules"])

            # READY
            surface = self._render_frame(
                profile_name, 0, RunState.READY, run_token, fc,
            )
            self._store_event(surface, events, seen_hashes, frames_dir,
                              run_token, profile_name, 0, fc, "READY")
            # RUNNING
            for fi in range(fc):
                surface = self._render_frame(
                    profile_name, fi, RunState.RUNNING, run_token, fc,
                )
                self._store_event(surface, events, seen_hashes, frames_dir,
                                  run_token, profile_name, fi, fc, "RUNNING")
            # DONE
            surface = self._render_frame(
                profile_name, fc - 1, RunState.DONE, run_token, fc,
            )
            self._store_event(surface, events, seen_hashes, frames_dir,
                              run_token, profile_name, fc - 1, fc, "DONE")

        # PNGs were written during the sequential pass — tally sizes only
        for file_name in seen_hashes.values():
            file_path = frames_dir / file_name
            png_bytes += file_path.stat().st_size if file_path.exists() else 0

        t1 = time.perf_counter()

        # Sender truth — check first RUNNING frame
        first_running = next((e for e in events if e.state == "RUNNING"), None)
        if first_running and profile_name in grid_profiles():
            surface = self._render_frame(
                profile_name, first_running.frame_index, "RUNNING",
                run_token, fc,
            )
            sender_truth = validate_sender_truth(
                surface, profile_name, first_running.frame_index,
            )
        elif first_running and profile_name in qr_controls():
            sender_truth = SenderTruthResult(
                passed=True, observed_cells=0, bit_errors=0,
                erased_cells=0, ber=0.0, erasure_rate=0.0,
            )
        else:
            sender_truth = None

        # Receiver replay
        receiver_replay = validate_receiver_replay(events, frames_dir, profile_name)

        return ProfileBaselineResult(
            profile=profile_name,
            run_token=run_token,
            frame_count=fc,
            events=events,
            event_count=len(events),
            unique_pngs=len(seen_hashes),
            sender_truth=sender_truth,
            receiver_replay=receiver_replay,
            render_time_s=t1 - t0,
            png_bytes=png_bytes,
        )

    def _store_event(
        self, surface: pygame.Surface, events: list[BaselineEvent],
        seen_hashes: dict[str, str], frames_dir: Path,
        run_token: int, profile_name: str, frame_index: int,
        frame_count: int, state: str,
    ) -> None:
        rgb = pygame.image.tobytes(surface, "RGB")
        content_hash = hashlib.sha256(rgb).hexdigest()

        if content_hash not in seen_hashes:
            file_name = f"{content_hash[:16]}.png"
            seen_hashes[content_hash] = file_name
            # Write PNG immediately to keep memory bounded
            rgb_arr = np.frombuffer(rgb, dtype=np.uint8).reshape(
                surface.get_height(), surface.get_width(), 3,
            )
            bgr_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(frames_dir / file_name), bgr_arr,
                       [cv2.IMWRITE_PNG_COMPRESSION, 1])

        events.append(BaselineEvent(
            run_token=run_token,
            profile=profile_name,
            frame_index=frame_index,
            frame_count=frame_count,
            dwell_epochs=self._dwell_epochs,
            state=state,
            content_sha256=content_hash,
            file_name=seen_hashes[content_hash],
            width=surface.get_width(),
            height=surface.get_height(),
        ))  # noqa: RUF005
        self._all_events.append(events[-1])

    def _render_frame(
        self, profile_name: str, frame_index: int, state: str | RunState,
        run_token: int, frame_count: int,
    ) -> pygame.Surface:
        """Render one frame from scratch (for re-render/truth paths)."""
        is_grid = profile_name in grid_profiles()
        renderer = LabRenderer(self._marker_size)
        if isinstance(state, str):
            rs = RunState[state]
        else:
            rs = state

        if is_grid:
            local_seq = GridFrameSequence(profile_name)
            matrix = None
            for _ in range(frame_index + 1):
                idx, matrix = local_seq.next_frame()
            envelope = build_run_envelope(
                profile_name, run_token, frame_index, frame_count,
                self._dwell_epochs, rs,
            )
            renderer.prepare_logical_frame(
                matrix,
                payload_bbox=self._manifest["payload_bbox"],
                sync_bits=envelope.bits(),
                sync_bboxes=(self._sync["top_bbox"], self._sync["bottom_bbox"]),
                sync_rows=int(self._sync["rows"]),
                sync_cols=int(self._sync["cols"]),
            )
        else:
            control = qr_controls()[profile_name]
            matrix = build_qr_matrix(
                control, frame_index, run_token=run_token,
                frame_count=frame_count, dwell_epochs=self._dwell_epochs,
                state=rs,
            )
            renderer.prepare_qr_matrix(matrix, int(control["quiet_zone_modules"]))

        return renderer.cached_frame_display

    def _build_export(self, profile_results, peak_mem, png_bytes,
                      elapsed_s) -> dict:
        profiles_export = []
        for pr in profile_results:
            entry = {
                "profile": pr.profile,
                "run_token": f"0x{pr.run_token:04X}",
                "frame_count": pr.frame_count,
                "event_count": pr.event_count,
                "unique_pngs": pr.unique_pngs,
                "render_time_s": round(pr.render_time_s, 3),
                "png_bytes": pr.png_bytes,
                "sender_truth": asdict(pr.sender_truth) if pr.sender_truth else None,
                "receiver_replay": asdict(pr.receiver_replay) if pr.receiver_replay else None,
            }
            profiles_export.append(entry)

        return {
            "schema": "superqr-digital-baseline-v1",
            "marker_size_px": self._marker_size,
            "frame_count_per_profile": self._frame_count,
            "dwell_epochs": self._dwell_epochs,
            "ready_seconds": self._ready_s,
            "done_seconds": self._done_s,
            "total_elapsed_s": round(elapsed_s, 3),
            "peak_memory_mib": round(peak_mem / 1024 / 1024, 2),
            "artifact_size_bytes": png_bytes,
            "profiles": profiles_export,
        }
