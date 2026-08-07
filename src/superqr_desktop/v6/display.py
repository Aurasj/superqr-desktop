import pygame
from superqr_desktop.v6.renderer import V6Renderer
from superqr_desktop.v6.diagnostics import V6DisplayMetrics

CANONICAL_SIZE = 1000

class DisplayController:
    def __init__(self, contract: dict):
        self.contract = contract
        self.screen = None
        self.renderer = None
        self.marker_size = CANONICAL_SIZE
        self.current_display_index = 0
        self.is_fullscreen = False

    @staticmethod
    def detect_displays() -> list[dict]:
        if not pygame.display.get_init():
            pygame.display.init()
            
        displays = []
        try:
            sizes = pygame.display.get_desktop_sizes()
            for idx, (w, h) in enumerate(sizes):
                displays.append({
                    "index": idx,
                    "label": f"Display {idx + 1} ({w}x{h})",
                    "width": w,
                    "height": h
                })
        except Exception:
            pass

        if not displays:
            try:
                info = pygame.display.Info()
                displays.append({
                    "index": 0,
                    "label": f"Display 1 ({info.current_w}x{info.current_h})",
                    "width": info.current_w,
                    "height": info.current_h
                })
            except Exception:
                displays.append({
                    "index": 0,
                    "label": "Display 1 (Default)",
                    "width": 1920,
                    "height": 1080
                })
        return displays

    def setup_display(self, display_index: int, is_fullscreen: bool, target_size: int = CANONICAL_SIZE) -> V6DisplayMetrics:
        self.current_display_index = display_index
        self.is_fullscreen = is_fullscreen
        self.marker_size = target_size

        if self.screen is not None:
            pygame.display.quit()
            pygame.display.init()

        displays = self.detect_displays()
        disp_info = next((d for d in displays if d["index"] == display_index), displays[0])
        screen_w = disp_info["width"]
        screen_h = disp_info["height"]

        # Canonical V6 metrics at 1000x1000 scale
        metrics = V6DisplayMetrics(self.contract, scale=1.0)

        if is_fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.RESIZABLE
            canvas_w, canvas_h = self.marker_size, self.marker_size

        try:
            self.screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=display_index)
        except pygame.error:
            self.screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=0)
            self.current_display_index = 0

        pygame.display.set_caption("SuperQR V6 Optical Marker Output")

        if not is_fullscreen:
            try:
                pos_x = (screen_w - canvas_w) // 2
                pos_y = (screen_h - canvas_h) // 2
                pygame.display.set_window_position((pos_x, pos_y))
            except Exception:
                pass

        # V6Renderer always renders canonically at 1000x1000
        self.renderer = V6Renderer(self.contract, CANONICAL_SIZE)
        return metrics

    def render(self, mode: str):
        if not self.screen or not self.renderer:
            return

        # Canonical rendering at 1000x1000
        self.renderer.draw_static_features()
        self.renderer.draw_grid(mode)

        self.screen.fill((255, 255, 255))

        canvas_w, canvas_h = self.screen.get_size()

        # Crisp pixel-preserving scaling (nearest-neighbor via pygame.transform.scale)
        if self.marker_size != CANONICAL_SIZE:
            scaled_surface = pygame.transform.scale(
                self.renderer.surface, 
                (self.marker_size, self.marker_size)
            )
        else:
            scaled_surface = self.renderer.surface

        cx = (canvas_w - self.marker_size) // 2
        cy = (canvas_h - self.marker_size) // 2

        self.screen.blit(scaled_surface, (cx, cy))
        pygame.display.flip()
