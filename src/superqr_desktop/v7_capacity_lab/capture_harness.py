"""Deterministic V7 campaign capture: lossless frame export with timeline.

Every unique logical frame is recorded once as a lossless PNG. Duplicate
dwell presents are stored as timeline timestamps only, not as duplicate
image data. Frame hashes provide content-addressed deduplication and
integrity verification for replay.

PNG encoding occurs at ``write_manifest()`` time, outside the presentation
hot path.  The hot path only extracts raw pixel bytes and computes a hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pygame


@dataclass
class CapturedFrame:
    """Metadata for one unique logical frame stored on disk."""

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
    present_timestamps_ns: list[int] = field(default_factory=list)

    @property
    def key(self) -> tuple[int, str, int, str]:
        return (self.run_token, self.profile, self.frame_index, self.state)


@dataclass
class RunCapture:
    """Per-run capture summary."""

    run_token: int
    profile: str
    frame_count: int
    dwell_epochs: int
    unique_frames: int
    total_presents: int
    started_ns: int
    finished_ns: int


class CaptureRecorder:
    """Record lossless rendered frames during a campaign presentation.

    Integration point: the presentation thread calls ``record_logical_frame``
    once per logical-frame change.  Raw pixel bytes are buffered in memory;
    PNG encoding and disk I/O are deferred to ``write_manifest()``.
    """

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)
        self._frames: list[CapturedFrame] = []
        self._runs: list[RunCapture] = []
        self._seen_hashes: dict[str, CapturedFrame] = {}
        self._pending: dict[str, bytes] = {}  # content_hash → raw RGB bytes
        self._run_started_ns: int | None = None
        self._current_run: tuple | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._frames_dir = self._output_dir / "frames"
        self._frames_dir.mkdir(exist_ok=True)

    def stop(self, join: bool = True) -> None:
        pass

    # ------------------------------------------------------------------
    # hot-path recording (called from presentation thread)
    # ------------------------------------------------------------------

    def record_logical_frame(
        self,
        surface: pygame.Surface,
        *,
        run_token: int,
        profile: str,
        frame_index: int,
        frame_count: int,
        dwell_epochs: int,
        state: str,
        present_timestamp_ns: int,
    ) -> bool:
        """Record a presented logical frame. Returns True if the content was new.

        Must be called from the presentation thread.  Extracts raw bytes and
        computes a content hash synchronously; PNG encoding is deferred.
        """
        size = surface.get_size()
        raw = pygame.image.tobytes(surface, "RGB")
        content_hash = hashlib.sha256(raw).hexdigest()

        if content_hash in self._seen_hashes:
            existing = self._seen_hashes[content_hash]
            existing.present_timestamps_ns.append(present_timestamp_ns)
            return False

        file_name = f"{content_hash[:16]}.png"
        record = CapturedFrame(
            run_token=run_token,
            profile=profile,
            frame_index=frame_index,
            frame_count=frame_count,
            dwell_epochs=dwell_epochs,
            state=state,
            content_sha256=content_hash,
            file_name=file_name,
            width=size[0],
            height=size[1],
            present_timestamps_ns=[present_timestamp_ns],
        )
        self._seen_hashes[content_hash] = record
        self._frames.append(record)
        self._pending[content_hash] = raw
        return True

    def start_run(
        self, run_token: int, profile: str, frame_count: int,
        dwell_epochs: int, timestamp_ns: int,
    ) -> None:
        self._run_started_ns = timestamp_ns
        self._current_run = (run_token, profile, frame_count, dwell_epochs)

    def finish_run(self, timestamp_ns: int) -> None:
        if self._run_started_ns is not None and self._current_run is not None:
            rt, prof, fc, de = self._current_run
            run_frames = [
                f for f in self._frames if f.run_token == rt and f.profile == prof
            ]
            self._runs.append(RunCapture(
                run_token=rt,
                profile=prof,
                frame_count=fc,
                dwell_epochs=de,
                unique_frames=len(run_frames),
                total_presents=sum(
                    len(f.present_timestamps_ns) for f in run_frames
                ),
                started_ns=self._run_started_ns,
                finished_ns=timestamp_ns,
            ))
        self._run_started_ns = None

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def export_manifest(self) -> dict[str, Any]:
        """Produce the capture manifest (does not write PNGs)."""
        return {
            "schema": "superqr-capture-manifest-v1",
            "frames": [asdict(f) for f in self._frames],
            "runs": [asdict(r) for r in self._runs],
        }

    def write_manifest(self) -> Path:
        """Encode all pending frames as PNGs, write them to disk, and write the manifest."""
        for content_hash, raw in self._pending.items():
            record = self._seen_hashes.get(content_hash)
            if record is None:
                continue
            file_path = self._frames_dir / record.file_name
            if not file_path.exists():
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(
                    record.height, record.width, 3,
                )
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(file_path), bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        self._pending.clear()

        manifest = self.export_manifest()
        path = self._output_dir / "capture_manifest.json"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, separators=(",", ": "))
        return path

    @property
    def frame_count(self) -> int:
        return len(self._frames)
