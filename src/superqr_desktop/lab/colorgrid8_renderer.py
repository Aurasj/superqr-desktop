"""Pygame renderer for the isolated ColorGrid8 LAB."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pygame

from superqr_desktop.lab.colorgrid8_core import (
    ColorGrid8Profile,
    PALETTE_RGB,
    build_symbol_frame,
)

FIDUCIAL_MODULES = 7
MIN_FINDER_MODULE_PX = 6
MIN_FINDER_PX = FIDUCIAL_MODULES * MIN_FINDER_MODULE_PX  # 42 px
ORIENTATION_CORNER = "TL"  # Top-Left corner carries the asymmetric orientation cue


@dataclass(frozen=True)
class ColorGrid8RenderGeometry:
    cell_px: int
    grid_left: int
    grid_top: int
    grid_width: int
    grid_height: int
    carrier_width: int
    carrier_height: int
    outer_margin_px: int
    finder_size_px: int
    finder_module_px: int
    fiducial_centers: tuple[tuple[float, float], ...]
    orientation_corner: str = ORIENTATION_CORNER
    orientation_marker_rect: tuple[int, int, int, int] | None = None

    @property
    def grid_rect(self) -> pygame.Rect:
        return pygame.Rect(self.grid_left, self.grid_top, self.grid_width, self.grid_height)

    @property
    def carrier_rect(self) -> pygame.Rect:
        return pygame.Rect(0, 0, self.carrier_width, self.carrier_height)


def _compute_geometry(
    profile: ColorGrid8Profile,
    max_width: int,
    max_height: int,
) -> ColorGrid8RenderGeometry:
    """Compute decoupled optical geometry with minimum finder size and full-canvas utilization."""
    if profile.version == 2 and (profile.cols, profile.rows) in ((240, 216), (336, 288)):
        # The product receiver maps finder centres to the corners of an
        # eight-cell border. Keep that ratio independent of window size.
        finder_module_px = MIN_FINDER_MODULE_PX
        finder_size_px = FIDUCIAL_MODULES * finder_module_px
        edge = 6
        cell_px = min(
            (max_width - finder_size_px - 2 * edge) // (profile.cols + 16),
            (max_height - finder_size_px - 2 * edge) // (profile.rows + 16),
        )
        minimum_cell = 3
        if cell_px < minimum_cell:
            minimum_width = (profile.cols + 16) * minimum_cell + finder_size_px + 2 * edge
            minimum_height = (profile.rows + 16) * minimum_cell + finder_size_px + 2 * edge
            raise ValueError(f"{profile.cols}x{profile.rows} ColorGrid8 needs a canvas of at least {minimum_width}x{minimum_height} pixels")
        outer_margin_px = 8 * cell_px + finder_size_px // 2 + edge
        grid_width, grid_height = profile.cols * cell_px, profile.rows * cell_px
        carrier_width = grid_width + 2 * outer_margin_px
        carrier_height = grid_height + 2 * outer_margin_px
        lo = edge + finder_size_px / 2.0
        centers = ((lo, lo), (carrier_width - lo, lo),
                   (carrier_width - lo, carrier_height - lo), (lo, carrier_height - lo))
        return ColorGrid8RenderGeometry(
            cell_px, outer_margin_px, outer_margin_px, grid_width, grid_height,
            carrier_width, carrier_height, outer_margin_px, finder_size_px,
            finder_module_px, centers, ORIENTATION_CORNER,
            (outer_margin_px, edge, finder_module_px, finder_module_px),
        )
    # Scale finder module with canvas resolution while enforcing a sensible physical minimum (>=6 px/module).
    finder_module_px = max(MIN_FINDER_MODULE_PX, min(max_width, max_height) // 160)
    finder_size_px = FIDUCIAL_MODULES * finder_module_px
    quiet_zone_px = max(18, finder_module_px * 2)
    outer_margin_px = finder_size_px + 2 * quiet_zone_px

    available_w = max_width - 2 * outer_margin_px
    available_h = max_height - 2 * outer_margin_px
    cell_px = min(available_w // profile.cols, available_h // profile.rows)
    if cell_px < 2:
        # If available margin is tight, allow margin to shrink down to finder clearance
        min_margin = finder_size_px + 12
        avail_w_tight = max_width - 2 * min_margin
        avail_h_tight = max_height - 2 * min_margin
        cell_px = min(avail_w_tight // profile.cols, avail_h_tight // profile.rows)
        if cell_px < 2:
            raise ValueError(
                f"canvas {max_width}x{max_height} is too small for "
                f"{profile.cols}x{profile.rows} ColorGrid8 at >=2 px/cell with decoupled finders"
            )
        outer_margin_px = min_margin
        quiet_zone_px = (outer_margin_px - finder_size_px) // 2

    cell_px = int(cell_px)
    grid_width = profile.cols * cell_px
    grid_height = profile.rows * cell_px
    carrier_width = grid_width + 2 * outer_margin_px
    carrier_height = grid_height + 2 * outer_margin_px
    grid_left = outer_margin_px
    grid_top = outer_margin_px

    # Finder centers are placed symmetrically outside the 4 grid corners in the outer margins
    finder_inset = quiet_zone_px
    cx_left = finder_inset + finder_size_px / 2.0
    cx_right = carrier_width - finder_inset - finder_size_px / 2.0
    cy_top = finder_inset + finder_size_px / 2.0
    cy_bottom = carrier_height - finder_inset - finder_size_px / 2.0
    fiducial_centers = (
        (cx_left, cy_top),
        (cx_right, cy_top),
        (cx_right, cy_bottom),
        (cx_left, cy_bottom),
    )

    # Asymmetric orientation marker: solid black rectangle in the Top-Left quadrant margin
    # placed cleanly between the TL finder right edge and the data grid left edge
    om_size = max(6, finder_module_px)
    finder_right_edge = cx_left + finder_size_px / 2.0
    om_x = int(finder_right_edge + (grid_left - finder_right_edge - om_size) / 2.0)
    om_y = int(cy_top - om_size / 2.0)
    orientation_marker_rect = (om_x, om_y, om_size, om_size)

    return ColorGrid8RenderGeometry(
        cell_px=cell_px,
        grid_left=grid_left,
        grid_top=grid_top,
        grid_width=grid_width,
        grid_height=grid_height,
        carrier_width=carrier_width,
        carrier_height=carrier_height,
        outer_margin_px=outer_margin_px,
        finder_size_px=finder_size_px,
        finder_module_px=finder_module_px,
        fiducial_centers=fiducial_centers,
        orientation_corner=ORIENTATION_CORNER,
        orientation_marker_rect=orientation_marker_rect,
    )


def choose_cell_px(profile: ColorGrid8Profile, max_width: int, max_height: int) -> int:
    """Choose the largest integer cell that fits the available canvas."""
    return _compute_geometry(profile, max_width, max_height).cell_px


def _draw_finder(surface: pygame.Surface, center: tuple[float, float], module_px: int) -> None:
    """Draw a 1:1:3:1:1 concentric square finder fiducial."""
    cx, cy = center
    size7 = 7 * module_px
    x = round(cx - size7 / 2)
    y = round(cy - size7 / 2)
    pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(x, y, size7, size7))
    size5 = 5 * module_px
    pygame.draw.rect(
        surface,
        (255, 255, 255),
        pygame.Rect(round(cx - size5 / 2), round(cy - size5 / 2), size5, size5),
    )
    size3 = 3 * module_px
    pygame.draw.rect(
        surface,
        (0, 0, 0),
        pygame.Rect(round(cx - size3 / 2), round(cy - size3 / 2), size3, size3),
    )


class ColorGrid8Renderer:
    """Render data cells with no antialiasing, decoupled large fiducials, and orientation cue."""

    def __init__(self) -> None:
        self._cached_geometry: ColorGrid8RenderGeometry | None = None
        self._cached_background: pygame.Surface | None = None
        self._indexed_surface: pygame.Surface | None = None
        self._last_profile_dims: tuple[int, int] | None = None
        self._last_max_canvas: tuple[int, int] | None = None

    def _ensure_pipeline(
        self,
        profile: ColorGrid8Profile,
        max_width: int,
        max_height: int,
    ) -> ColorGrid8RenderGeometry:
        dims = (profile.cols, profile.rows)
        canvas_dims = (max_width, max_height)
        if (
            self._cached_geometry is not None
            and self._cached_background is not None
            and self._indexed_surface is not None
            and self._last_profile_dims == dims
            and self._last_max_canvas == canvas_dims
        ):
            return self._cached_geometry

        geometry = _compute_geometry(profile, max_width, max_height)

        # 8-bit palette-indexed surface for zero-copy symbol blitting
        indexed = pygame.Surface((profile.cols, profile.rows), depth=8)
        palette_list = [tuple(c) for c in PALETTE_RGB]
        indexed.set_palette(palette_list + [(0, 0, 0)] * (256 - len(palette_list)))
        self._indexed_surface = indexed

        # Pre-render static carrier background with white canvas, finders, and orientation cue
        bg = pygame.Surface((geometry.carrier_width, geometry.carrier_height), depth=24)
        bg.fill((255, 255, 255))
        for center in geometry.fiducial_centers:
            _draw_finder(bg, center, geometry.finder_module_px)

        # Asymmetric orientation marker in Top-Left quadrant
        if geometry.orientation_marker_rect is not None:
            ox, oy, ow, oh = geometry.orientation_marker_rect
            pygame.draw.rect(bg, (0, 0, 0), pygame.Rect(ox, oy, ow, oh))

        self._cached_background = bg
        self._cached_geometry = geometry
        self._last_profile_dims = dims
        self._last_max_canvas = canvas_dims
        return geometry

    def render_symbols(
        self,
        profile: ColorGrid8Profile,
        symbols: np.ndarray,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> tuple[pygame.Surface, ColorGrid8RenderGeometry]:
        """Render a symbol matrix using fast palette lookup and nearest-neighbor scaling.

        Zero antialiasing, zero interpolation, zero repeated 3D numpy array expansion.
        """
        if symbols.shape != (profile.rows, profile.cols):
            raise ValueError(
                f"symbol matrix shape {symbols.shape} != {(profile.rows, profile.cols)}"
            )
        if symbols.dtype != np.uint8:
            symbols = symbols.astype(np.uint8, copy=False)
        if symbols.size and (int(symbols.min()) < 0 or int(symbols.max()) > 7):
            raise ValueError("ColorGrid8 symbols must be in [0, 7]")

        geometry = self._ensure_pipeline(profile, max_width, max_height)
        assert self._indexed_surface is not None
        assert self._cached_background is not None

        # Blit 2D uint8 symbols directly into 8-bit palette surface (transposed for pygame [x, y])
        pygame.surfarray.blit_array(self._indexed_surface, symbols.T)

        # Nearest-neighbor scale to integer pixel grid dimensions
        scaled_grid = pygame.transform.scale(
            self._indexed_surface,
            (geometry.grid_width, geometry.grid_height),
        )

        # Blit scaled data grid onto a copy of the pre-rendered carrier background
        surface = self._cached_background.copy()
        surface.blit(scaled_grid, (geometry.grid_left, geometry.grid_top))
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

        Uses the identical optical geometry, scale, and finders as data carrier frames.
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
        """Single-symbol LAB helper for manual palette inspection."""
        if not 0 <= symbol < 8:
            raise ValueError("symbol must be in [0, 8)")
        symbols = np.full((profile.rows, profile.cols), symbol, dtype=np.uint8)
        return self.render_symbols(
            profile,
            symbols,
            max_width=max_width,
            max_height=max_height,
        )
