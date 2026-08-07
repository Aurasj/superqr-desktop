import pygame
from superqr_desktop.v6.patterns import get_pattern_bytes

def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

class V6Renderer:
    def __init__(self, contract: dict, size: int):
        self.contract = contract
        self.size = size
        self.scale = size / 1000.0
        self.surface = pygame.Surface((size, size))
        
        self.palette = {}
        for idx, p in self.contract["palette"]["indexes"].items():
            self.palette[p["name"]] = hex_to_rgb(p["sRGB"])
            
    def _rect(self, bbox: list) -> pygame.Rect:
        x1 = int(bbox[0] * self.scale)
        y1 = int(bbox[1] * self.scale)
        x2 = int(bbox[2] * self.scale)
        y2 = int(bbox[3] * self.scale)
        return pygame.Rect(x1, y1, x2 - x1, y2 - y1)
        
    def draw_static_features(self):
        self.surface.fill((255, 255, 255))
        
        b = self.contract["border"]
        stroke = b["stroke_width"]
        outer_bbox = b["bbox"]
        inner_bbox = [
            outer_bbox[0] + stroke, 
            outer_bbox[1] + stroke, 
            outer_bbox[2] - stroke, 
            outer_bbox[3] - stroke
        ]
        pygame.draw.rect(self.surface, self.palette["BLACK"], self._rect(outer_bbox))
        pygame.draw.rect(self.surface, self.palette["WHITE"], self._rect(inner_bbox))
        
        for key, anchor in self.contract["anchors"]["elements"].items():
            pygame.draw.rect(self.surface, self.palette["BLACK"], self._rect(anchor["bbox"]))
            core_bbox = anchor["identity_pattern"]["core_bbox"]
            pygame.draw.rect(self.surface, self.palette["WHITE"], self._rect(core_bbox))
            quadrants = anchor["identity_pattern"]["black_quadrants"]
            cx = (core_bbox[0] + core_bbox[2]) // 2
            cy = (core_bbox[1] + core_bbox[3]) // 2
            for q in quadrants:
                if q == "top_left": q_bbox = [core_bbox[0], core_bbox[1], cx, cy]
                elif q == "top_right": q_bbox = [cx, core_bbox[1], core_bbox[2], cy]
                elif q == "bottom_left": q_bbox = [core_bbox[0], cy, cx, core_bbox[3]]
                elif q == "bottom_right": q_bbox = [cx, cy, core_bbox[2], core_bbox[3]]
                pygame.draw.rect(self.surface, self.palette["BLACK"], self._rect(q_bbox))
                
        for key, pilot in self.contract["calibration_pilots"]["elements"].items():
            pygame.draw.rect(self.surface, self.palette[pilot["carrier_color"]], self._rect(pilot["carrier_bbox"]))
            pygame.draw.rect(self.surface, self.palette[pilot["core_color"]], self._rect(pilot["core_bbox"]))
            
        for key, tracker in self.contract["border_tracking"]["elements"].items():
            pygame.draw.rect(self.surface, self.palette[tracker["color"]], self._rect(tracker["bbox"]))
            
        for key, sync in self.contract["phase_sync_cells"]["elements"].items():
            color = self.palette["BLACK"] if key == "SYNC_0" else self.palette["WHITE"]
            pygame.draw.rect(self.surface, color, self._rect(sync["bbox"]))
            
    def draw_grid(self, mode: str):
        grid = self.contract["data_grid"]
        cols, rows = grid["cols"], grid["rows"]
        csize = grid["cell_size"]
        x0, y0 = grid["bbox"][0], grid["bbox"][1]
        
        pattern_bytes = get_pattern_bytes(mode, rows, cols)
        color_lookup = [
            self.palette["BLACK"],
            self.palette["WHITE"],
            self.palette["RED"],
            self.palette["BLUE"]
        ]
        
        idx = 0
        for r in range(rows):
            for c in range(cols):
                color = color_lookup[pattern_bytes[idx]]
                idx += 1
                bbox = [x0 + c * csize, y0 + r * csize, x0 + (c + 1) * csize, y0 + (r + 1) * csize]
                pygame.draw.rect(self.surface, color, self._rect(bbox))

    def draw_grid_indexes(self, indexes: list[int]):
        grid = self.contract["data_grid"]
        cols, rows = grid["cols"], grid["rows"]
        csize = grid["cell_size"]
        x0, y0 = grid["bbox"][0], grid["bbox"][1]
        
        color_lookup = [
            self.palette["BLACK"],
            self.palette["WHITE"],
            self.palette["RED"],
            self.palette["BLUE"]
        ]
        
        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx < len(indexes):
                    color = color_lookup[indexes[idx]]
                else:
                    color = color_lookup[0]
                idx += 1
                bbox = [x0 + c * csize, y0 + r * csize, x0 + (c + 1) * csize, y0 + (r + 1) * csize]
                pygame.draw.rect(self.surface, color, self._rect(bbox))
