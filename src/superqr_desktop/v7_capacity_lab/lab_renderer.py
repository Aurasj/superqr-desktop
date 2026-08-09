"""V7 Capacity Lab renderer.

Converts protocol SymbolMatrix objects to display frames via a compact
byte-buffer path with nearest-neighbor scaling. The laboratory acquisition
carrier is deliberately independent of frozen V6 geometry and does not define
the eventual production V7 data PHY or wire format.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pygame

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    load_phy_selection_manifest,
    get_protocol_geometry,
    get_protocol_palettes,
)


@dataclass
class RenderTimings:
    """Per-frame timing measurements in microseconds."""
    symbol_matrix_to_rgb_us: int = 0
    surface_creation_us: int = 0
    payload_scale_us: int = 0
    compose_us: int = 0
    total_prepare_us: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "symbol_matrix_to_rgb_us": self.symbol_matrix_to_rgb_us,
            "surface_creation_us": self.surface_creation_us,
            "payload_scale_us": self.payload_scale_us,
            "compose_us": self.compose_us,
            "total_prepare_us": self.total_prepare_us,
        }


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class V7AcquisitionCarrierRenderer:
    """Renders the lab-only V7 acquisition carrier once and caches it."""

    def __init__(self, canonical_size: int = 1000):
        self.canonical_size = canonical_size
        manifest = load_phy_selection_manifest()
        self.contract = manifest["acquisition_carrier"]
        self._scale = canonical_size / manifest["canvas_size"]
        self._surface: pygame.Surface | None = None

    @property
    def surface(self) -> pygame.Surface:
        """Return the cached carrier surface, building it on first access."""
        if self._surface is None:
            self._surface = self._build()
        return self._surface

    def _rect(self, bbox: list) -> pygame.Rect:
        x1 = int(bbox[0] * self._scale)
        y1 = int(bbox[1] * self._scale)
        x2 = int(bbox[2] * self._scale)
        y2 = int(bbox[3] * self._scale)
        return pygame.Rect(x1, y1, x2 - x1, y2 - y1)

    def _build(self) -> pygame.Surface:
        """Build a thick frame, four nested finders, and calibration pilots."""
        surf = pygame.Surface((self.canonical_size, self.canonical_size))
        surf.fill((255, 255, 255))

        border = self.contract["outer_border"]
        outer = border["bbox"]
        thickness = border["thickness"]
        inner = [outer[0] + thickness, outer[1] + thickness,
                 outer[2] - thickness, outer[3] - thickness]
        pygame.draw.rect(surf, (0, 0, 0), self._rect(outer))
        pygame.draw.rect(surf, (255, 255, 255), self._rect(inner))

        for finder in self.contract["finder_patterns"]:
            pygame.draw.rect(surf, (0, 0, 0), self._rect(finder["outer_bbox"]))
            pygame.draw.rect(surf, (255, 255, 255), self._rect(finder["inner_bbox"]))
            pygame.draw.rect(surf, (0, 0, 0), self._rect(finder["core_bbox"]))

        for pilot in self.contract["pilots"]:
            pygame.draw.rect(surf, _hex_to_rgb(pilot["carrier_color"]),
                             self._rect(pilot["carrier_bbox"]))
            pygame.draw.rect(surf, _hex_to_rgb(pilot["core_color"]),
                             self._rect(pilot["core_bbox"]))

        return surf


class LabRenderer:
    """Renders protocol SymbolMatrix objects to display frames.

    Path:
        SymbolMatrix → RGB byte buffer → native grid Surface →
        nearest-neighbor scale to display payload rect →
        compose with cached carrier → cache for dwell repeats.
    """

    def __init__(self, marker_size: int):
        self.marker_size = marker_size
        self._canonical_size = 1000
        self._marker_scale = marker_size / self._canonical_size

        # Carrier: build canonical, scale once to marker size
        self._carrier_canonical = V7AcquisitionCarrierRenderer(self._canonical_size)
        carrier_src = self._carrier_canonical.surface
        if marker_size != self._canonical_size:
            self._carrier_display = pygame.transform.scale(
                carrier_src, (marker_size, marker_size))
        else:
            self._carrier_display = carrier_src

        # Cached composed frame (reused for dwell repeats)
        self._cached_frame: pygame.Surface | None = None

        self.timings = RenderTimings()

    @property
    def cached_frame_display(self) -> pygame.Surface | None:
        return self._cached_frame

    def _compute_display_payload_rect(self, payload_bbox) -> pygame.Rect:
        """Map canonical payload_bbox to display coordinates."""
        x = int(payload_bbox[0] * self._marker_scale)
        y = int(payload_bbox[1] * self._marker_scale)
        w = int((payload_bbox[2] - payload_bbox[0]) * self._marker_scale)
        h = int((payload_bbox[3] - payload_bbox[1]) * self._marker_scale)
        return pygame.Rect(x, y, w, h)

    def prepare_logical_frame(
        self,
        symbol_matrix,
        payload_bbox=None,
        sync_bits: list[int] | None = None,
        sync_bboxes=None,
        sync_rows: int = 2,
        sync_cols: int = 40,
    ) -> None:
        """Build and cache the display frame for a new logical frame.

        Called once per logical frame change, not per refresh.
        The cached result is reused for remaining dwell refreshes.

        Args:
            symbol_matrix: protocol SymbolMatrix (has .symbols[row][col], .rows, .cols, .palette_name)
        """
        t_start = time.perf_counter_ns()

        if symbol_matrix.palette_name in load_phy_selection_manifest()["palettes"]:
            colors = load_phy_selection_manifest()["palettes"][symbol_matrix.palette_name]["colors"]
            rgb_lookup = {idx: _hex_to_rgb(hex_str) for idx, hex_str in enumerate(colors)}
        else:
            palette_mod = get_protocol_palettes()
            palette = palette_mod.get_palette(symbol_matrix.palette_name)
            rgb_lookup = {idx: _hex_to_rgb(hex_str) for idx, hex_str in palette.color_map.items()}

        # 1. Symbol matrix → RGB byte buffer
        t1 = time.perf_counter_ns()
        grid_w = symbol_matrix.cols
        grid_h = symbol_matrix.rows
        buf = bytearray(grid_w * grid_h * 3)
        pos = 0
        for row in symbol_matrix.symbols:
            for sym_idx in row:
                r, g, b = rgb_lookup[sym_idx]
                buf[pos] = r
                buf[pos + 1] = g
                buf[pos + 2] = b
                pos += 3
        t2 = time.perf_counter_ns()

        # 2. Create native grid-size Surface
        native_surf = pygame.image.frombytes(bytes(buf), (grid_w, grid_h), "RGB")
        t3 = time.perf_counter_ns()

        # 3. Scale directly to display payload rect (single scale, nearest-neighbor)
        if payload_bbox is None:
            geo_mod = get_protocol_geometry()
            payload_bbox = geo_mod.build_geometry(max(grid_w, grid_h)).payload_bbox
        display_payload_rect = self._compute_display_payload_rect(payload_bbox)
        payload_scaled = pygame.transform.scale(native_surf,
                                                 (display_payload_rect.width,
                                                  display_payload_rect.height))
        t4 = time.perf_counter_ns()

        # 4. Compose: copy cached carrier, blit payload
        frame = self._carrier_display.copy()
        frame.blit(payload_scaled, (display_payload_rect.x, display_payload_rect.y))
        if sync_bits is not None:
            if sync_bboxes is None:
                raise ValueError("sync_bboxes is required with sync_bits")
            for bbox in sync_bboxes:
                self._draw_bit_grid(frame, sync_bits, bbox, sync_rows, sync_cols)
        t5 = time.perf_counter_ns()

        self._cached_frame = frame

        # Record timings (ns → us)
        self.timings.symbol_matrix_to_rgb_us = (t2 - t1) // 1000
        self.timings.surface_creation_us = (t3 - t2) // 1000
        self.timings.payload_scale_us = (t4 - t3) // 1000
        self.timings.compose_us = (t5 - t4) // 1000
        self.timings.total_prepare_us = (t5 - t_start) // 1000

    def _draw_bit_grid(
        self, frame: pygame.Surface, bits: list[int], bbox, rows: int, cols: int,
    ) -> None:
        if len(bits) != rows * cols:
            raise ValueError("bit-grid dimensions do not match bits")
        rect = self._compute_display_payload_rect(bbox)
        for index, bit in enumerate(bits):
            row, col = divmod(index, cols)
            x1 = rect.x + round(col * rect.width / cols)
            x2 = rect.x + round((col + 1) * rect.width / cols)
            y1 = rect.y + round(row * rect.height / rows)
            y2 = rect.y + round((row + 1) * rect.height / rows)
            pygame.draw.rect(frame, (255, 255, 255) if bit else (0, 0, 0),
                             pygame.Rect(x1, y1, max(1, x2 - x1), max(1, y2 - y1)))

    def prepare_qr_matrix(self, matrix: tuple[bytes, ...], quiet_zone: int = 4) -> None:
        """Prepare a standard QR control with exact integer module scaling."""
        native = self.build_qr_native_surface(matrix, quiet_zone)
        self.prepare_qr_native_surface(native)

    def build_qr_native_surface(
        self,
        matrix: tuple[bytes, ...],
        quiet_zone: int = 4,
    ) -> pygame.Surface:
        """Build a compact QR surface once, outside the presentation loop."""
        modules = len(matrix)
        if modules < 1 or any(len(row) != modules for row in matrix):
            raise ValueError("QR matrix must be square")
        total = modules + 2 * quiet_zone
        buf = bytearray([255]) * (total * total * 3)
        for row, values in enumerate(matrix):
            for col, value in enumerate(values):
                if value:
                    offset = ((row + quiet_zone) * total + col + quiet_zone) * 3
                    buf[offset:offset + 3] = b"\x00\x00\x00"
        return pygame.image.frombytes(bytes(buf), (total, total), "RGB")

    def prepare_qr_native_surface(self, native: pygame.Surface) -> None:
        """Scale and center an already-encoded compact QR surface."""
        t_start = time.perf_counter_ns()
        total = native.get_width()
        if total != native.get_height():
            raise ValueError("native QR surface must be square")
        scale = self.marker_size // total
        if scale < 1:
            raise ValueError("marker is too small for the QR matrix")
        rendered = total * scale
        scaled = pygame.transform.scale(native, (rendered, rendered))
        frame = pygame.Surface((self.marker_size, self.marker_size))
        frame.fill((255, 255, 255))
        offset = (self.marker_size - rendered) // 2
        frame.blit(scaled, (offset, offset))
        self._cached_frame = frame
        self.timings.total_prepare_us = (time.perf_counter_ns() - t_start) // 1000
