"""Lightweight sender presentation telemetry for the desktop UI."""

from __future__ import annotations

from superqr_desktop.v7.telemetry import PresentationTelemetry


class DiagnosticsCollector:
    """Keep measured presentation cadence separate from configured cadence."""

    def __init__(self) -> None:
        self._presentation = PresentationTelemetry()
        self.last_error: str | None = None

    def record_present(
        self,
        frame_id: int,
        configured_interval_ms: int,
        render_ms: float,
        flip_ms: float,
    ) -> None:
        self._presentation.record_present(
            frame_id=frame_id,
            configured_interval_ms=configured_interval_ms,
            render_prepare_ms=render_ms,
            display_flip_ms=flip_ms,
        )

    def set_error(self, error: str) -> None:
        self.last_error = error

    def snapshot(self) -> dict:
        snapshot = self._presentation.snapshot()
        snapshot["last_error"] = self.last_error
        return snapshot

    def reset(self) -> None:
        self._presentation.reset()
        self.last_error = None
