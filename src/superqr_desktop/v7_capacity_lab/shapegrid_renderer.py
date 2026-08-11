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
from superqr_desktop.v7_capacity_lab.shapegrid_geometry import canonical_grid_bbox


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

    def canonical_rect(self, profile: dict) -> tuple[float, float, float, float]:
        return canonical_grid_bbox(
            profile, self.manifest["acquisition"]["reference_payload_bbox"]
        )

    def display_rect(self, profile: dict) -> pygame.Rect:
        return self.renderer._compute_display_payload_rect(self.canonical_rect(profile))

    def projected_subcell_px(self, profile: dict) -> float:
        rect = self.display_rect(profile)
        cols = int(profile["grid_cols"])
        rows = int(profile["grid_rows"])
        return min(rect.width / (cols * 6.0), rect.height / (rows * 6.0))

    def subcell_scale(self, profile: dict) -> int:
        """Compatibility gate: whole projected subcell pixels available."""
        return int(self.projected_subcell_px(profile))

    def prepare(self, profile: dict, cells: bytes, *, sync_bits: list[int]) -> None:
        started = time.perf_counter_ns()
        rows = int(profile["grid_rows"])
        cols = int(profile["grid_cols"])
        if len(cells) != rows * cols:
            raise ValueError(
                f"ShapeGrid cell count {len(cells)} != profile grid {cols}x{rows}"
            )

        frame = self.renderer._carrier_display.copy()
        rect = self.display_rect(profile)
        native_width = cols * 6
        native_height = rows * 6
        subcell_px = self.projected_subcell_px(profile)
        if subcell_px < 1.0:
            minimum = int(profile.get("minimum_reference_marker_px_for_subcell_scale_1", 0))
            suffix = f"; profile minimum reference marker is ~{minimum}px" if minimum else ""
            raise ValueError(
                f"ShapeGrid {profile['name']} projects below 1 px/subcell at marker "
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
        if rect.size != native.get_size():
            rendered = pygame.transform.scale(native, rect.size)
        else:
            rendered = native
        frame.blit(rendered, rect.topleft)

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
