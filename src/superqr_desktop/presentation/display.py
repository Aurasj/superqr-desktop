"""Version-neutral SDL display ownership for SuperQR Desktop."""

from __future__ import annotations

import pygame


class DisplayController:
    """Own the main-process SDL output window without legacy renderer state."""

    def __init__(self):
        self.screen: pygame.Surface | None = None
        self.marker_size = 1000
        self.current_display_index = 0
        self.is_fullscreen = False

    @staticmethod
    def detect_displays() -> list[dict]:
        if not pygame.display.get_init():
            pygame.display.init()
            DisplayController._apply_event_filter()

        displays: list[dict] = []
        try:
            for idx, (width, height) in enumerate(pygame.display.get_desktop_sizes()):
                displays.append({
                    "index": idx,
                    "label": f"Display {idx + 1} ({width}x{height})",
                    "width": width,
                    "height": height,
                })
        except Exception:
            pass

        if displays:
            return displays

        try:
            info = pygame.display.Info()
            return [{
                "index": 0,
                "label": f"Display 1 ({info.current_w}x{info.current_h})",
                "width": info.current_w,
                "height": info.current_h,
            }]
        except Exception:
            return [{
                "index": 0,
                "label": "Display 1 (Default)",
                "width": 1920,
                "height": 1080,
            }]

    # Block every SDL event type except QUIT, KEYDOWN, and USEREVENT.
    # This prevents the event queue from filling with thousands of
    # MOUSEMOTION / WINDOWMOVED events during a window drag — converting
    # those C structs to Python objects on the next pygame.event.get()
    # after mouse release would otherwise cause a visible hitch.
    _KEPT_EVENTS = {pygame.QUIT, pygame.KEYDOWN, pygame.USEREVENT}
    _blocklist: list[int] | None = None

    @classmethod
    def _build_blocklist(cls) -> list[int]:
        if cls._blocklist is not None:
            return cls._blocklist
        blocked = []
        for name in dir(pygame):
            if not name.isupper() or name.startswith("_"):
                continue
            val = getattr(pygame, name)
            if not isinstance(val, int) or val <= 0 or val >= 65536:
                continue
            if val in cls._KEPT_EVENTS:
                continue
            try:
                pygame.event.set_blocked([val])
                blocked.append(val)
            except (ValueError, TypeError):
                pass
        cls._blocklist = blocked
        return blocked

    @classmethod
    def _apply_event_filter(cls) -> None:
        bl = cls._build_blocklist()
        if bl:
            pygame.event.set_blocked(bl)

    def setup_display(
        self,
        display_index: int,
        fullscreen: bool,
        marker_size: int,
    ) -> None:
        if marker_size <= 0:
            raise ValueError("marker_size must be positive")

        self.current_display_index = display_index
        self.is_fullscreen = fullscreen
        self.marker_size = marker_size

        # Recreate the SDL display cleanly when changing monitor/window mode.
        if self.screen is not None and pygame.display.get_init():
            pygame.display.quit()
        if not pygame.display.get_init():
            pygame.display.init()
        self._apply_event_filter()

        displays = self.detect_displays()
        selected = next(
            (item for item in displays if item["index"] == display_index),
            displays[0],
        )
        screen_w = int(selected["width"])
        screen_h = int(selected["height"])

        if fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.RESIZABLE
            canvas_w = marker_size
            canvas_h = marker_size

        try:
            self.screen = pygame.display.set_mode(
                (canvas_w, canvas_h), flags, display=display_index,
            )
        except pygame.error:
            self.screen = pygame.display.set_mode(
                (canvas_w, canvas_h), flags, display=0,
            )
            self.current_display_index = 0

        pygame.display.set_caption("SuperQR Optical Marker Output")

        if not fullscreen:
            try:
                pygame.display.set_window_position((
                    (screen_w - canvas_w) // 2,
                    (screen_h - canvas_h) // 2,
                ))
            except Exception:
                pass


    def render_standby(self) -> None:
        """Fill the output with a neutral surface; no protocol pattern is shown."""
        if self.screen is None:
            return
        marker = self.marker_size
        self.screen.fill((8, 10, 14))
        canvas_w, canvas_h = self.screen.get_size()
        origin_x = (canvas_w - marker) // 2
        origin_y = (canvas_h - marker) // 2
        pygame.draw.rect(
            self.screen,
            (30, 34, 46),
            (origin_x - 1, origin_y - 1, marker + 2, marker + 2),
            1,
        )
        pygame.display.flip()

    def close(self) -> None:
        self.screen = None
        if pygame.display.get_init():
            pygame.display.quit()
