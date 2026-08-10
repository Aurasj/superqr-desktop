"""Display adapter wrapping the V6-proven SDL display controller."""

from __future__ import annotations

from superqr_desktop.v6.display import DisplayController as _V6DisplayController


class DisplayController:
    """Thin adapter around the frozen V6 DisplayController.

    Provides monitor detection, SDL window setup, and a neutral standby
    pattern for when no transfer or campaign is active.
    """

    def __init__(self, contract: dict):
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
        if self._controller.screen and self._controller.renderer:
            self._controller.render("deterministic_random")

    def close(self) -> None:
        self._controller.close()
