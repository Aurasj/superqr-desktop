"""Pygame renderer for the isolated ColorGrid8 LAB."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.colorgrid8_core import (
    ColorGrid8Profile,
    PALETTE_RGB,
    build_symbol_frame,
)

FIDUCIAL_OFFSET_CELLS = 4
OUTER_MARGIN_CELLS = 8
FIDUCIAL_MODULES = 7


@dataclass(frozen=True)
class ColorGrid8RenderGeometry:
    cell_px: int
    grid_left: int
    grid_top: int
    grid_width: int
    grid_height: int
    fiducial_centers: tuple[tuple[float, float], ...]

    @property
    def grid_rect(self) -> pygame.Rect:
        return pygame.Rect(self.grid_left, self.grid_top, self.grid_width, self.grid_height)


def choose_cell_px(profile: ColorGrid8Profile, max_width: int, max_height: int) -> int:
    cell = min(
        max_width // (profile.cols + 2 * OUTER_MARGIN_CELLS),
        max_height // (profile.rows + 2 * OUTER_MARGIN_CELLS),
    )
    return max(2, min(10, int(cell)))


def _finder(surface: pygame.Surface, center: tuple[float, float], cell_px: int) -> None:
    cx, cy = center
    size = FIDUCIAL_MODULES * cell_px
    x = round(cx - size / 2)
    y = round(cy - size / 2)
    pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(x, y, size, size))
    inner5 = 5 * cell_px
    pygame.draw.rect(
        surface,
        (255, 255, 255),
        pygame.Rect(round(cx - inner5 / 2), round(cy - inner5 / 2), inner5, inner5),
    )
    inner3 = 3 * cell_px
    pygame.draw.rect(
        surface,
        (0, 0, 0),
        pygame.Rect(round(cx - inner3 / 2), round(cy - inner3 / 2), inner3, inner3),
    )


class ColorGrid8Renderer:
    """Render data cells with no antialiasing and four large luma fiducials."""

    def render(
        self,
        profile: ColorGrid8Profile,
        frame_index: int,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        cell_px = choose_cell_px(profile, max_width, max_height)
        grid_width = profile.cols * cell_px
        grid_height = profile.rows * cell_px
        grid_left = OUTER_MARGIN_CELLS * cell_px
        grid_top = OUTER_MARGIN_CELLS * cell_px
        canvas_width = grid_width + 2 * grid_left
        canvas_height = grid_height + 2 * grid_top

        symbols = build_symbol_frame(profile, frame_index)
        cell_rgb = PALETTE_RGB[symbols]
        pixels = np.repeat(np.repeat(cell_rgb, cell_px, axis=0), cell_px, axis=1)
        # pygame.surfarray uses [x, y, channel], numpy image above is [y, x, channel].
        grid_surface = pygame.surfarray.make_surface(np.transpose(pixels, (1, 0, 2)))

        surface = pygame.Surface((canvas_width, canvas_height), depth=24)
        surface.fill((255, 255, 255))
        surface.blit(grid_surface, (grid_left, grid_top))

        offset = FIDUCIAL_OFFSET_CELLS * cell_px
        left = grid_left - offset
        right = grid_left + grid_width + offset
        top = grid_top - offset
        bottom = grid_top + grid_height + offset
        centers = ((left, top), (right, top), (right, bottom), (left, bottom))
        for center in centers:
            _finder(surface, center, cell_px)

        return surface, ColorGrid8RenderGeometry(
            cell_px=cell_px,
            grid_left=grid_left,
            grid_top=grid_top,
            grid_width=grid_width,
            grid_height=grid_height,
            fiducial_centers=centers,
        )

    def render_calibration(
        self,
        symbol: int,
        profile: ColorGrid8Profile,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        if not 0 <= symbol < 8:
            raise ValueError("symbol must be in [0, 8)")
        surface, geometry = self.render(profile, 0, max_width=max_width, max_height=max_height)
        color = tuple(int(x) for x in PALETTE_RGB[symbol])
        pygame.draw.rect(surface, color, geometry.grid_rect)
        return surface, geometry
