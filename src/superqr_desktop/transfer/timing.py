"""Monotonic cadence helper for in-process optical presentation.

Tk owns the SDL window on the main thread, so active transfer presentation
cannot use a background SDL worker.  This helper keeps frame deadlines separate
from the slower UI/status polling loop and deliberately never bursts multiple
frames to catch up after a stall.
"""

from __future__ import annotations

import math


class TransferCadenceClock:
    """Track one monotonic presentation deadline at a time."""

    def __init__(self) -> None:
        self._deadline: float | None = None

    @property
    def running(self) -> bool:
        return self._deadline is not None

    @property
    def deadline(self) -> float | None:
        return self._deadline

    def start(self, now: float, interval_ms: int) -> None:
        self._deadline = now + self._interval_seconds(interval_ms)

    def stop(self) -> None:
        self._deadline = None

    def reschedule(self, now: float, interval_ms: int) -> None:
        """Apply a new interval from *now* instead of keeping an old deadline."""
        if self._deadline is not None:
            self.start(now, interval_ms)

    def due(self, now: float) -> bool:
        return self._deadline is not None and now >= self._deadline

    def mark_presented(self, now: float, interval_ms: int) -> None:
        """Advance one interval without generating catch-up bursts.

        Small callback jitter keeps the original deadline cadence.  If the UI
        was delayed by at least a whole interval, the next deadline is rebased
        from the completed presentation so frames are never flashed back-to-back.
        """
        interval = self._interval_seconds(interval_ms)
        if self._deadline is None:
            self._deadline = now + interval
            return
        next_deadline = self._deadline + interval
        self._deadline = next_deadline if next_deadline > now else now + interval

    def delay_ms(self, now: float, *, max_delay_ms: int | None = None) -> int:
        """Return a positive Tk ``after`` delay for the current deadline."""
        if self._deadline is None:
            raise RuntimeError("cadence clock is not running")
        remaining_ms = max(0.0, (self._deadline - now) * 1000.0)
        delay = max(1, math.ceil(remaining_ms))
        if max_delay_ms is not None:
            delay = min(delay, max(1, max_delay_ms))
        return delay

    @staticmethod
    def _interval_seconds(interval_ms: int) -> float:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        return interval_ms / 1000.0
