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
    """Choose the largest integer cell that fits the available canvas.

    There is intentionally no arbitrary upper cap: on a 4K/8K sender, larger
    cells directly buy more camera samples per chroma cell.  A too-small canvas
    is rejected instead of silently overflowing it with a forced 2 px cell.
    """
    cell = min(
        max_width // (profile.cols + 2 * OUTER_MARGIN_CELLS),
        max_height // (profile.rows + 2 * OUTER_MARGIN_CELLS),
    )
    if cell < 2:
        raise ValueError(
            f"canvas {max_width}x{max_height} is too small for "
            f"{profile.cols}x{profile.rows} ColorGrid8 at >=2 px/cell"
        )
    return int(cell)


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

    def _geometry(
        self,
        profile: ColorGrid8Profile,
        max_width: int,
        max_height: int,
    ) -> ColorGrid8RenderGeometry:
        cell_px = choose_cell_px(profile, max_width, max_height)
        grid_width = profile.cols * cell_px
        grid_height = profile.rows * cell_px
        grid_left = OUTER_MARGIN_CELLS * cell_px
        grid_top = OUTER_MARGIN_CELLS * cell_px
        offset = FIDUCIAL_OFFSET_CELLS * cell_px
        left = grid_left - offset
        right = grid_left + grid_width + offset
        top = grid_top - offset
        bottom = grid_top + grid_height + offset
        return ColorGrid8RenderGeometry(
            cell_px=cell_px,
            grid_left=grid_left,
            grid_top=grid_top,
            grid_width=grid_width,
            grid_height=grid_height,
            fiducial_centers=((left, top), (right, top), (right, bottom), (left, bottom)),
        )

    def render_symbols(
        self,
        profile: ColorGrid8Profile,
        symbols: np.ndarray,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        """Render a prebuilt symbol matrix.

        Keeping deterministic PRNG generation outside this method lets the LAB
        runner prepare future frames while the current optical frame is on-screen.
        The live presentation path then only expands colors and creates a surface.
        """
        if symbols.shape != (profile.rows, profile.cols):
            raise ValueError(
                f"symbol matrix shape {symbols.shape} != {(profile.rows, profile.cols)}"
            )
        if symbols.dtype != np.uint8:
            symbols = symbols.astype(np.uint8, copy=False)
        if symbols.size and (int(symbols.min()) < 0 or int(symbols.max()) > 7):
            raise ValueError("ColorGrid8 symbols must be in [0, 7]")

        geometry = self._geometry(profile, max_width, max_height)
        cell_rgb = PALETTE_RGB[symbols]
        pixels = np.repeat(
            np.repeat(cell_rgb, geometry.cell_px, axis=0),
            geometry.cell_px,
            axis=1,
        )
        # pygame.surfarray uses [x, y, channel], numpy image above is [y, x, channel].
        grid_surface = pygame.surfarray.make_surface(np.transpose(pixels, (1, 0, 2)))

        canvas_width = geometry.grid_width + 2 * geometry.grid_left
        canvas_height = geometry.grid_height + 2 * geometry.grid_top
        surface = pygame.Surface((canvas_width, canvas_height), depth=24)
        surface.fill((255, 255, 255))
        surface.blit(grid_surface, (geometry.grid_left, geometry.grid_top))
        for center in geometry.fiducial_centers:
            _finder(surface, center, geometry.cell_px)
        return surface, geometry

    def render(
        self,
        profile: ColorGrid8Profile,
        frame_index: int,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        return self.render_symbols(
            profile,
            build_symbol_frame(profile, frame_index),
            max_width=max_width,
            max_height=max_height,
        )

    def render_calibration_board(
        self,
        profile: ColorGrid8Profile,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        """Show all eight symbols simultaneously in large balanced regions.

        Sequential full-screen solid colors make camera auto-exposure/white-balance
        chase a changing scene.  This board keeps both luminance bands and all four
        chroma states visible at once, so the camera can settle on a histogram that
        resembles the following data stream.
        """
        symbols = np.empty((profile.rows, profile.cols), dtype=np.uint8)
        top_order = (0, 5, 2, 7)
        bottom_order = (4, 1, 6, 3)
        split_row = profile.rows // 2
        for col in range(profile.cols):
            band = min(3, col * 4 // profile.cols)
            symbols[:split_row, col] = top_order[band]
            symbols[split_row:, col] = bottom_order[band]
        return self.render_symbols(
            profile,
            symbols,
            max_width=max_width,
            max_height=max_height,
        )

    def render_calibration(
        self,
        symbol: int,
        profile: ColorGrid8Profile,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        """Legacy single-symbol LAB helper retained for manual palette inspection."""
        if not 0 <= symbol < 8:
            raise ValueError("symbol must be in [0, 8)")
        symbols = np.full((profile.rows, profile.cols), symbol, dtype=np.uint8)
        return self.render_symbols(
            profile,
            symbols,
            max_width=max_width,
            max_height=max_height,
        )
