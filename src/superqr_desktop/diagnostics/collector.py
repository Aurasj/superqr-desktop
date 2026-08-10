"""Lightweight telemetry collector for UI status display."""

from __future__ import annotations


class DiagnosticsCollector:
    def __init__(self):
        self.present_count = 0
        self.last_render_ms = 0.0
        self.last_flip_ms = 0.0
        self.last_error: str | None = None

    def record_present(self, render_ms: float, flip_ms: float) -> None:
        self.present_count += 1
        self.last_render_ms = render_ms
        self.last_flip_ms = flip_ms

    def set_error(self, error: str) -> None:
        self.last_error = error

    def snapshot(self) -> dict:
        return {
            "present_count": self.present_count,
            "last_render_ms": round(self.last_render_ms, 3),
            "last_flip_ms": round(self.last_flip_ms, 3),
            "last_error": self.last_error,
        }

    def reset(self) -> None:
        self.present_count = 0
        self.last_render_ms = 0.0
        self.last_flip_ms = 0.0
        self.last_error = None
