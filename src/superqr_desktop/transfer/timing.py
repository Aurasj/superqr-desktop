"""Monotonic cadence helper for production optical presentation."""

from __future__ import annotations

import math


class TransferCadenceClock:
    """Track one optical presentation deadline at a time using fractional ms."""

    def __init__(self) -> None:
        self._deadline: float | None = None

    @property
    def running(self) -> bool:
        return self._deadline is not None

    @property
    def deadline(self) -> float | None:
        return self._deadline

    def start(self, now: float, interval_ms: float) -> None:
        self._deadline = now + self._interval_seconds(interval_ms)

    def stop(self) -> None:
        self._deadline = None

    def reschedule(self, now: float, interval_ms: float) -> None:
        if self._deadline is not None:
            self.start(now, interval_ms)

    def due(self, now: float) -> bool:
        return self._deadline is not None and now >= self._deadline

    def mark_presented(self, now: float, interval_ms: float) -> None:
        """Schedule the next change while guaranteeing a full optical dwell.

        QR encoding is prefetched off the UI thread. If a producer underrun ever
        makes us late by a whole interval, rebase from the actual flip time rather
        than flashing the next QR immediately.
        """
        interval = self._interval_seconds(interval_ms)
        if self._deadline is None:
            self._deadline = now + interval
            return
        next_deadline = self._deadline + interval
        self._deadline = next_deadline if next_deadline > now else now + interval

    def delay_ms(self, now: float, *, max_delay_ms: int | None = None) -> int:
        if self._deadline is None:
            raise RuntimeError("cadence clock is not running")
        remaining_ms = max(0.0, (self._deadline - now) * 1000.0)
        delay = max(1, math.ceil(remaining_ms))
        if max_delay_ms is not None:
            delay = min(delay, max(1, max_delay_ms))
        return delay

    @staticmethod
    def _interval_seconds(interval_ms: float) -> float:
        interval_ms = float(interval_ms)
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        return interval_ms / 1000.0
