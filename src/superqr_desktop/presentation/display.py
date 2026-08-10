"""Display adapter wrapping the V6-proven SDL display controller.

Provides monitor detection and SDL window setup. The standby surface is a
neutral protocol-independent fill — not a V6 carrier pattern.
"""

from __future__ import annotations

import pygame

from superqr_desktop.v6.display import DisplayController as _V6DisplayController


class DisplayController:
    """Thin adapter around the frozen V6 DisplayController.

    Generic SDL ownership (detect, setup, close) comes from the V6 controller.
    Standby rendering uses a neutral surface, not a V6 carrier.
    """

    def __init__(self, contract: dict):
        # Pass the contract dict because V6 DisplayController's __init__ stores it
        # for later use.  We only use detect_displays / setup_display / close,
        # never the V6 render paths.
        self._controller = _V6DisplayController(contract)

    def detect_displays(self) -> list[dict]:
        return self._controller.detect_displays()

    def setup_display(self, display_index: int, fullscreen: bool, marker_size: int):
        return self._controller.setup_display(display_index, fullscreen, marker_size)

    @property
    def screen(self):
        return self._controller.screen

    @property
    def marker_size(self) -> int:
        return self._controller.marker_size

    def render_standby(self) -> None:
        """Fill the display with a neutral dark surface. No V6 carrier."""
        screen = self._controller.screen
        if screen is None:
            return
        marker = self._controller.marker_size
        screen.fill((8, 10, 14))
        # Draw a subtle frame outline so the user knows the output window is alive.
        cw, ch = screen.get_size()
        ox, oy = (cw - marker) // 2, (ch - marker) // 2
        pygame.draw.rect(screen, (30, 34, 46), (ox - 1, oy - 1, marker + 2, marker + 2), 1)
        pygame.display.flip()

    def close(self) -> None:
        self._controller.close()
