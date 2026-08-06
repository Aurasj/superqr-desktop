import pygame
from superqr_desktop.v6.renderer import V6Renderer
from superqr_desktop.v6.diagnostics import V6DisplayMetrics

class DisplayController:
    def __init__(self, contract: dict):
        self.contract = contract
        self.screen = None
        self.renderer = None
        self.marker_size = 800

    def setup_display(self, display_index: int, is_fullscreen: bool) -> V6DisplayMetrics:
        if self.screen is not None:
            pygame.display.quit()
            pygame.display.init()
            
        disp = display_index
        try:
            pygame.display.set_mode((1, 1), flags=pygame.HIDDEN, display=disp)
            info = pygame.display.Info()
        except pygame.error:
            pygame.display.init()
            info = pygame.display.Info()
            disp = 0
            
        screen_w = info.current_w
        screen_h = info.current_h
        
        self.marker_size = min(screen_w, screen_h) // 100 * 100
        if self.marker_size < 100:
            self.marker_size = 800
            
        scale = self.marker_size / 1000.0
        metrics = V6DisplayMetrics(self.contract, scale)
        
        if is_fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            canvas_w, canvas_h = screen_w, screen_h
        else:
            flags = pygame.NOFRAME
            canvas_w, canvas_h = self.marker_size, self.marker_size
            
        self.screen = pygame.display.set_mode((canvas_w, canvas_h), flags, display=disp)
        pygame.display.set_caption("V6 Optical Marker")
        
        self.renderer = V6Renderer(self.contract, self.marker_size)
        return metrics

    def render(self, mode: str):
        if not self.screen or not self.renderer:
            return
            
        self.renderer.draw_static_features()
        self.renderer.draw_grid(mode)
        
        self.screen.fill((255, 255, 255))
        
        canvas_w, canvas_h = self.screen.get_size()
        cx = (canvas_w - self.renderer.size) // 2
        cy = (canvas_h - self.renderer.size) // 2
        
        self.screen.blit(self.renderer.surface, (cx, cy))
        pygame.display.flip()
