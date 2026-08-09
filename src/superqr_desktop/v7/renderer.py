from __future__ import annotations

import pygame

from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v7.profiles import EXTRA_PILOTS, PALETTES, PAYLOAD_BBOX, PROFILE_CODE_CELLS, OpticalProfile

CANONICAL_SIZE = 1000


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


class V7TransferRenderer:
    """Fast dense renderer for production V7 transfer frames.

    Reuses the proven packaged V6 acquisition geometry, but production transfer
    code intentionally does not depend on the Capacity Lab package.
    """

    def __init__(self, marker_size: int, profile: OpticalProfile):
        self.marker_size = marker_size
        self.profile = profile
        self.contract, _ = load_contract()
        self._scale = marker_size / CANONICAL_SIZE
        self._carrier = self._build_carrier()
        self.cached_frame_display: pygame.Surface | None = None

    def _rect(self, bbox) -> pygame.Rect:
        x1, y1, x2, y2 = bbox
        return pygame.Rect(
            round(x1 * self._scale),
            round(y1 * self._scale),
            max(1, round((x2 - x1) * self._scale)),
            max(1, round((y2 - y1) * self._scale)),
        )

    def _build_carrier(self) -> pygame.Surface:
        canonical = pygame.Surface((CANONICAL_SIZE, CANONICAL_SIZE))
        canonical.fill((255, 255, 255))
        palette = {}
        for _, entry in self.contract["palette"]["indexes"].items():
            palette[entry["name"]] = _hex_to_rgb(entry["sRGB"])

        border = self.contract["border"]
        outer = border["bbox"]
        stroke = border["stroke_width"]
        inner = [outer[0] + stroke, outer[1] + stroke, outer[2] - stroke, outer[3] - stroke]
        pygame.draw.rect(canonical, palette["BLACK"], pygame.Rect(*self._canonical_rect(outer)))
        pygame.draw.rect(canonical, palette["WHITE"], pygame.Rect(*self._canonical_rect(inner)))

        for anchor in self.contract["anchors"]["elements"].values():
            bbox = anchor["bbox"]
            core = anchor["identity_pattern"]["core_bbox"]
            pygame.draw.rect(canonical, palette["BLACK"], pygame.Rect(*self._canonical_rect(bbox)))
            pygame.draw.rect(canonical, palette["WHITE"], pygame.Rect(*self._canonical_rect(core)))
            cx = (core[0] + core[2]) // 2
            cy = (core[1] + core[3]) // 2
            for q in anchor["identity_pattern"]["black_quadrants"]:
                qb = {
                    "top_left": [core[0], core[1], cx, cy],
                    "top_right": [cx, core[1], core[2], cy],
                    "bottom_left": [core[0], cy, cx, core[3]],
                    "bottom_right": [cx, cy, core[2], core[3]],
                }[q]
                pygame.draw.rect(canonical, palette["BLACK"], pygame.Rect(*self._canonical_rect(qb)))

        for pilot in self.contract["calibration_pilots"]["elements"].values():
            pygame.draw.rect(canonical, palette[pilot["carrier_color"]], pygame.Rect(*self._canonical_rect(pilot["carrier_bbox"])))
            pygame.draw.rect(canonical, palette[pilot["core_color"]], pygame.Rect(*self._canonical_rect(pilot["core_bbox"])))

        for tracker in self.contract["border_tracking"]["elements"].values():
            pygame.draw.rect(canonical, palette[tracker["color"]], pygame.Rect(*self._canonical_rect(tracker["bbox"])))

        sync = self.contract["phase_sync_cells"]["elements"]
        pygame.draw.rect(canonical, palette["BLACK"], pygame.Rect(*self._canonical_rect(sync["SYNC_0"]["bbox"])))
        pygame.draw.rect(canonical, palette["WHITE"], pygame.Rect(*self._canonical_rect(sync["SYNC_1"]["bbox"])))

        extra_colors = {
            "GREEN": "#00FF00",
            "YELLOW": "#FFFF00",
            "CYAN": "#00FFFF",
            "MAGENTA": "#FF00FF",
        }
        for name, bbox in EXTRA_PILOTS.items():
            pygame.draw.rect(canonical, _hex_to_rgb(extra_colors[name]), pygame.Rect(*self._canonical_rect(bbox)))

        for bit_index, bbox in enumerate(PROFILE_CODE_CELLS):
            bit = (self.profile.id >> (3 - bit_index)) & 1
            color = (255, 255, 255) if bit else (0, 0, 0)
            pygame.draw.rect(canonical, color, pygame.Rect(*self._canonical_rect(bbox)))

        if self.marker_size == CANONICAL_SIZE:
            return canonical
        return pygame.transform.scale(canonical, (self.marker_size, self.marker_size))

    @staticmethod
    def _canonical_rect(bbox) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = bbox
        return int(x1), int(y1), int(x2 - x1), int(y2 - y1)

    def prepare_symbols(self, symbols: list[int]) -> None:
        p = self.profile
        if len(symbols) != p.cell_count:
            raise ValueError(f"expected {p.cell_count} symbols for {p.key}")
        colors = [_hex_to_rgb(v) for v in PALETTES[p.palette_name]]
        g = p.grid
        buf = bytearray(g * g * 3)
        pos = 0
        for symbol in symbols:
            r, gg, b = colors[symbol]
            buf[pos] = r
            buf[pos + 1] = gg
            buf[pos + 2] = b
            pos += 3
        native = pygame.image.frombytes(bytes(buf), (g, g), "RGB")
        target = self._rect(PAYLOAD_BBOX)
        payload = pygame.transform.scale(native, (target.width, target.height))
        frame = self._carrier.copy()
        frame.blit(payload, target.topleft)
        self.cached_frame_display = frame
