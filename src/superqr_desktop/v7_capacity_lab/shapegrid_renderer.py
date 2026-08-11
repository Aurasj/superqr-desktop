"""Renderer for the lab-only Chroma4 ShapeGrid Phase 0 candidate."""
from __future__ import annotations

import time

import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    load_phy_selection_manifest,
    load_shapegrid_manifest,
)
from superqr_desktop.v7_capacity_lab.shapegrid import INACTIVE, symbol_to_shape_color


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


class ShapeGridFrameComposer:
    """Draw one shared-carrier ShapeGrid epoch from row-major logical cells."""

    def __init__(self, renderer):
        self.renderer = renderer
        self.manifest = load_shapegrid_manifest()
        self.phase1 = load_phy_selection_manifest()
        self._atlas = self._build_symbol_atlas()

    def _build_symbol_atlas(self) -> np.ndarray:
        modulation = self.manifest["modulation"]
        background = np.asarray(_rgb(modulation["background_color"]), dtype=np.uint8)
        atlas = np.empty((256, 6, 6, 3), dtype=np.uint8)
        atlas[:] = background
        colors = [_rgb(value) for value in modulation["data_palette"]["colors"]]
        mapping = [int(value) for value in modulation["data_palette"]["bit_to_palette_index"]]
        glyphs = modulation["glyphs"]
        for symbol in range(64):
            shape_id, color_bits = symbol_to_shape_color(symbol)
            color = np.asarray(colors[mapping[color_bits]], dtype=np.uint8)
            mask = glyphs[shape_id]["mask"]
            for row in range(5):
                for col in range(5):
                    if mask[row][col] == "#":
                        atlas[symbol, row, col] = color
        return atlas

    def reference_rect(self) -> pygame.Rect:
        return self.renderer._compute_display_payload_rect(
            self.manifest["acquisition"]["reference_payload_bbox"]
        )

    def subcell_scale(self, profile: dict) -> int:
        rect = self.reference_rect()
        width = int(profile["grid_cols"]) * 6
        height = int(profile["grid_rows"]) * 6
        return min(rect.width // width, rect.height // height)

    def prepare(self, profile: dict, cells: bytes, *, sync_bits: list[int]) -> None:
        started = time.perf_counter_ns()
        rows = int(profile["grid_rows"])
        cols = int(profile["grid_cols"])
        if len(cells) != rows * cols:
            raise ValueError(
                f"ShapeGrid cell count {len(cells)} != profile grid {cols}x{rows}"
            )

        frame = self.renderer._carrier_display.copy()
        rect = self.reference_rect()
        native_width = cols * 6
        native_height = rows * 6
        scale = min(rect.width // native_width, rect.height // native_height)
        if scale < 1:
            minimum = int(profile.get("minimum_reference_marker_px_for_subcell_scale_1", 0))
            suffix = f"; profile minimum reference marker is ~{minimum}px" if minimum else ""
            raise ValueError(
                f"ShapeGrid {profile['name']} cannot fit integer 6x6 subcells at marker "
                f"{self.renderer.marker_size}px{suffix}"
            )

        cell_matrix = np.frombuffer(cells, dtype=np.uint8).reshape(rows, cols)
        if np.any((cell_matrix != INACTIVE) & (cell_matrix > 63)):
            raise ValueError("ShapeGrid cells contain a value outside 0..63/255")
        tiled = self._atlas[cell_matrix]
        rgb = tiled.transpose(0, 2, 1, 3, 4).reshape(native_height, native_width, 3)
        native = pygame.image.frombuffer(
            rgb.tobytes(), (native_width, native_height), "RGB"
        ).copy()
        if scale > 1:
            rendered = pygame.transform.scale(
                native, (native_width * scale, native_height * scale)
            )
        else:
            rendered = native
        x = rect.x + (rect.width - rendered.get_width()) // 2
        y = rect.y + (rect.height - rendered.get_height()) // 2
        frame.blit(rendered, (x, y))

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
        self.renderer.timings.total_prepare_us = (
            time.perf_counter_ns() - started
        ) // 1000
