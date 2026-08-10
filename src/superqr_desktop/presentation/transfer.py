"""Synchronous in-process V7 transfer frame rendering."""

from __future__ import annotations

import time

import pygame

from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.renderer import V7TransferRenderer


class TransferPresenter:
    """Render V7 transfer frames on the main-process SDL display.

    The same renderer/display path is used for manual Prev/Next inspection and
    active transfer presentation, so what the user previews is the optical path
    that START actually sends.
    """

    def __init__(self, display: DisplayController):
        self._display = display
        self._renderer: V7TransferRenderer | None = None

    def ensure_renderer(self, marker_size: int, profile: OpticalProfile) -> None:
        if (self._renderer is None or self._renderer.marker_size != marker_size
                or self._renderer.profile != profile):
            self._renderer = V7TransferRenderer(marker_size, profile)

    def render_frame(self, symbols: list[int], marker_size: int, profile: OpticalProfile) -> dict:
        """Render one frame. Returns timing dict with render_ms and flip_ms."""
        started_ns = time.perf_counter_ns()
        self.ensure_renderer(marker_size, profile)
        assert self._renderer is not None
        self._renderer.prepare_symbols(symbols)
        surface = self._renderer.cached_frame_display
        screen = self._display.screen
        if surface is None or screen is None:
            return {"render_ms": 0.0, "flip_ms": 0.0}

        cw, ch = screen.get_size()
        marker = marker_size
        screen.fill((8, 10, 14))
        screen.blit(surface, ((cw - marker) // 2, (ch - marker) // 2))
        flip_started_ns = time.perf_counter_ns()
        pygame.display.flip()
        completed_ns = time.perf_counter_ns()
        return {
            "render_ms": (flip_started_ns - started_ns) / 1_000_000.0,
            "flip_ms": (completed_ns - flip_started_ns) / 1_000_000.0,
        }

    def invalidate_renderer(self) -> None:
        self._renderer = None
