"""Composition path for lab-only advanced multi-lane Phase 0 frames."""
from __future__ import annotations

import time

import pygame

from superqr_desktop.v7_capacity_lab.advanced_phy import build_advanced_grid_symbols
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_advanced_phy_manifest, load_phy_selection_manifest


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


class AdvancedFrameComposer:
    """Compose independent QR/grid lanes into one display epoch.

    The canonical LabRenderer remains untouched. This composer intentionally uses
    its cached carrier and coordinate helpers only for the lab-only extension.
    """

    def __init__(self, renderer):
        self.renderer = renderer
        self.manifest = load_advanced_phy_manifest()
        self.phase1 = load_phy_selection_manifest()

    def prepare(
        self,
        profile: dict,
        frame_index: int,
        qr_surfaces: dict[int, pygame.Surface],
        *,
        sync_bits: list[int] | None = None,
    ) -> None:
        started = time.perf_counter_ns()
        if bool(profile["requires_carrier"]):
            frame = self.renderer._carrier_display.copy()
        else:
            frame = pygame.Surface((self.renderer.marker_size, self.renderer.marker_size))
            frame.fill((255, 255, 255))

        for lane in profile["lanes"]:
            lane_id = int(lane["lane_id"])
            if lane["kind"] == "qr":
                native = qr_surfaces[lane_id]
                self._blit_qr_integer(frame, native, lane["bbox"])
            else:
                self._blit_grid(frame, profile, lane, frame_index)
                self._draw_palette_pilots(frame, lane)

        if bool(profile["requires_carrier"]) and sync_bits is not None:
            sync = self.phase1["run_sync"]
            for bbox in (sync["top_bbox"], sync["bottom_bbox"]):
                self.renderer._draw_bit_grid(
                    frame,
                    sync_bits,
                    bbox,
                    int(sync["rows"]),
                    int(sync["cols"]),
                )

        self.renderer._cached_frame = frame
        self.renderer.timings.total_prepare_us = (time.perf_counter_ns() - started) // 1000

    def _blit_qr_integer(self, frame: pygame.Surface, native: pygame.Surface, bbox) -> None:
        rect = self.renderer._compute_display_payload_rect(bbox)
        total = native.get_width()
        if total != native.get_height():
            raise ValueError("advanced QR lane must be square")
        scale = min(rect.width // total, rect.height // total)
        if scale < 2:
            raise ValueError(
                f"advanced QR lane has only {scale}px/module; refuse sub-2px rendering"
            )
        rendered = total * scale
        scaled = pygame.transform.scale(native, (rendered, rendered))
        x = rect.x + (rect.width - rendered) // 2
        y = rect.y + (rect.height - rendered) // 2
        frame.blit(scaled, (x, y))

    def _blit_grid(self, frame: pygame.Surface, profile: dict, lane: dict, frame_index: int) -> None:
        symbols = build_advanced_grid_symbols(profile, lane, frame_index)
        palette = self.manifest["palettes"][lane["palette"]]
        colors = [_rgb(value) for value in palette["colors"]]
        rows = int(lane["rows"])
        cols = int(lane["cols"])
        buf = bytearray(rows * cols * 3)
        pos = 0
        for row in symbols:
            for symbol in row:
                r, g, b = colors[symbol]
                buf[pos] = r
                buf[pos + 1] = g
                buf[pos + 2] = b
                pos += 3
        native = pygame.image.frombytes(bytes(buf), (cols, rows), "RGB")
        rect = self.renderer._compute_display_payload_rect(lane["data_bbox"])
        scaled = pygame.transform.scale(native, (rect.width, rect.height))
        frame.blit(scaled, (rect.x, rect.y))

    def _draw_palette_pilots(self, frame: pygame.Surface, lane: dict) -> None:
        palette = self.manifest["palettes"][lane["palette"]]
        colors = [_rgb(value) for value in palette["colors"]]
        rect = self.renderer._compute_display_payload_rect(lane["pilot_bbox"])
        count = len(colors)
        for index, color in enumerate(colors):
            x1 = rect.x + round(index * rect.width / count)
            x2 = rect.x + round((index + 1) * rect.width / count)
            pygame.draw.rect(
                frame,
                color,
                pygame.Rect(x1, rect.y, max(1, x2 - x1), rect.height),
            )
