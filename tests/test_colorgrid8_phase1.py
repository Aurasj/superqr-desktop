"""Phase 1 tests: sender optical geometry, decoupled finders, orientation cue, and presentation timing."""

from __future__ import annotations

import os
import time
import numpy as np
import pygame
import pytest

from superqr_desktop.lab.colorgrid8_core import (
    ColorGrid8Profile,
    PALETTE_RGB,
    TRANSFER_HEADER_VERSION,
    build_symbol_frame,
    golden_crc32,
)
from superqr_desktop.lab.colorgrid8_renderer import (
    ColorGrid8Renderer,
    ColorGrid8RenderGeometry,
    _compute_geometry,
    choose_cell_px,
    MIN_FINDER_PX,
    ORIENTATION_CORNER,
)
from superqr_desktop.lab.lab_display import (
    DisplayDiagnostics,
    DwellState,
    calculate_percentiles,
    detect_os_refresh_hz,
)


def _rects_overlap(r1: tuple[int, int, int, int], r2: tuple[int, int, int, int]) -> bool:
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return not (x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)


class TestOpticalGeometry:
    @pytest.mark.parametrize("dims", [(240, 216), (336, 288)])
    def test_product_finder_mapping_is_independent_of_window_size(self, dims) -> None:
        profile = ColorGrid8Profile(*dims, 30, version=TRANSFER_HEADER_VERSION)
        for canvas in ((1856, 984), (1920, 1080), (2560, 1440)):
            geometry = _compute_geometry(profile, *canvas)
            left, top = geometry.fiducial_centers[0]
            assert (geometry.grid_left - left) / geometry.cell_px == 8
            assert (geometry.grid_top - top) / geometry.cell_px == 8
            assert geometry.carrier_width <= canvas[0]
            assert geometry.carrier_height <= canvas[1]
            assert geometry.cell_px >= 3

    def test_minimum_finder_size_is_decoupled(self) -> None:
        p336 = ColorGrid8Profile(336, 288, 30, version=TRANSFER_HEADER_VERSION)
        p384 = ColorGrid8Profile(384, 336, 30, version=TRANSFER_HEADER_VERSION)
        g336 = _compute_geometry(p336, 1920, 1080)
        g384 = _compute_geometry(p384, 1920, 1080)

        assert g336.finder_size_px >= MIN_FINDER_PX
        assert g384.finder_size_px >= MIN_FINDER_PX
        assert g384.finder_size_px >= 42
        # Verify 384x336 finder does not shrink to 14px
        assert g384.finder_size_px == g336.finder_size_px

    def test_finders_and_orientation_cue_do_not_overlap_grid(self) -> None:
        profile = ColorGrid8Profile(336, 288, 30, version=TRANSFER_HEADER_VERSION)
        geometry = _compute_geometry(profile, 1920, 1080)
        grid_rect = (geometry.grid_left, geometry.grid_top, geometry.grid_width, geometry.grid_height)

        for cx, cy in geometry.fiducial_centers:
            f_size = geometry.finder_size_px
            f_rect = (int(cx - f_size / 2), int(cy - f_size / 2), f_size, f_size)
            assert not _rects_overlap(f_rect, grid_rect), f"Finder at {cx},{cy} overlaps grid"
            assert f_rect[0] >= 0 and f_rect[1] >= 0
            assert f_rect[0] + f_rect[2] <= geometry.carrier_width
            assert f_rect[1] + f_rect[3] <= geometry.carrier_height

        assert geometry.orientation_corner == "TL"
        assert geometry.orientation_marker_rect is not None
        assert not _rects_overlap(geometry.orientation_marker_rect, grid_rect)
        om_x, om_y, om_w, om_h = geometry.orientation_marker_rect
        assert om_x >= 0 and om_y >= 0
        assert om_x + om_w <= geometry.carrier_width
        assert om_y + om_h <= geometry.carrier_height

    def test_orientation_cue_is_in_top_left_quadrant(self) -> None:
        profile = ColorGrid8Profile(384, 336, 30, version=TRANSFER_HEADER_VERSION)
        geometry = _compute_geometry(profile, 1920, 1080)
        assert geometry.orientation_corner == ORIENTATION_CORNER
        assert geometry.orientation_marker_rect is not None
        om_x, om_y, om_w, om_h = geometry.orientation_marker_rect
        # Must be within the top and left margins
        assert om_x < geometry.grid_left
        assert om_y < geometry.grid_top

    def test_calibration_board_uses_identical_optical_geometry(self) -> None:
        pygame.init()
        profile = ColorGrid8Profile(336, 288, 30, version=TRANSFER_HEADER_VERSION)
        renderer = ColorGrid8Renderer()
        surf_cal, geom_cal = renderer.render_calibration_board(profile, 1920, 1080)
        surf_data, geom_data = renderer.render(profile, 0, 1920, 1080)

        assert geom_cal.cell_px == geom_data.cell_px
        assert geom_cal.grid_width == geom_data.grid_width
        assert geom_cal.grid_height == geom_data.grid_height
        assert geom_cal.carrier_width == geom_data.carrier_width
        assert geom_cal.carrier_height == geom_data.carrier_height
        assert geom_cal.finder_size_px == geom_data.finder_size_px
        assert geom_cal.fiducial_centers == geom_data.fiducial_centers
        assert surf_cal.get_size() == surf_data.get_size()
        pygame.quit()


class TestPresentationTiming:
    def test_60hz_display_dwell_for_30fps_is_exact_2_refreshes(self) -> None:
        dwell = DwellState(requested_fps=30, present_refresh_hz=60.0)
        assert dwell.dwell_refreshes == 2.0
        assert dwell.is_integer_dwell is True

        presents_per_frame: list[int] = []
        for _ in range(5):
            count = 0
            while not dwell.record_present():
                count += 1
            count += 1
            presents_per_frame.append(count)
            dwell.advance_logical_frame()

        assert presents_per_frame == [2, 2, 2, 2, 2]

    def test_120hz_display_dwell_for_30fps_is_exact_4_refreshes(self) -> None:
        dwell = DwellState(requested_fps=30, present_refresh_hz=120.0)
        assert dwell.dwell_refreshes == 4.0
        assert dwell.is_integer_dwell is True

        presents_per_frame: list[int] = []
        for _ in range(5):
            count = 0
            while not dwell.record_present():
                count += 1
            count += 1
            presents_per_frame.append(count)
            dwell.advance_logical_frame()

        assert presents_per_frame == [4, 4, 4, 4, 4]

    def test_72hz_display_dwell_for_30fps_detects_non_divisible_and_alternates(self) -> None:
        dwell = DwellState(requested_fps=30, present_refresh_hz=72.0)
        assert abs(dwell.dwell_refreshes - 2.4) < 1e-6
        assert dwell.is_integer_dwell is False

        presents_per_frame: list[int] = []
        for _ in range(10):
            count = 0
            while not dwell.record_present():
                count += 1
            count += 1
            presents_per_frame.append(count)
            dwell.advance_logical_frame()

        assert sum(presents_per_frame) == 24  # 10 frames * 2.4 = 24 refreshes total
        assert set(presents_per_frame) == {2, 3}

    def test_timing_warning_generated_when_non_divisible(self) -> None:
        from superqr_desktop.lab.lab_display import LabDisplayController
        controller = LabDisplayController(requested_fps=30)
        controller._update_dwell_diagnostics(72.0)
        assert controller.diag.is_refresh_divisible is False
        assert "72.0 Hz" in controller.diag.timing_warning
        assert "WARNING" in controller.diag.timing_warning

        controller._update_dwell_diagnostics(60.0)
        assert controller.diag.is_refresh_divisible is True
        assert controller.diag.timing_warning == ""

    def test_percentile_calculation(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        p50, p95 = calculate_percentiles(values)
        assert p50 == 50.0
        assert p95 == 90.0 or p95 == 100.0


def test_vsync_jitter_does_not_change_two_refresh_dwell() -> None:
    from superqr_desktop.lab.lab_display import LabDisplayController
    controller = LabDisplayController(requested_fps=30)
    controller._update_dwell_diagnostics(60.0)
    controller.diag.vsync_verified = True
    controller.diag.actual_vsync_enabled = True
    for interval in (16.0, 17.0, 16.7, 33.3, 15.9, 16.8):
        controller._observe_present_interval(interval)
        assert controller.dwell.present_refresh_hz == 60.0
        assert controller.diag.timing_warning == ""
        assert controller.dwell.record_present() is False
        assert controller.dwell.record_present() is True
        controller.dwell.advance_logical_frame()


class TestFastPaletteRendering:
    def test_palette_indexed_rendering_is_pixel_exact_nearest_neighbor(self) -> None:
        pygame.init()
        profile = ColorGrid8Profile(168, 144, 30)
        symbols = build_symbol_frame(profile, 42)
        renderer = ColorGrid8Renderer()

        surf, geom = renderer.render_symbols(profile, symbols, 1920, 1080)
        pixels_3d = pygame.surfarray.array3d(surf)

        # Extract data grid portion
        grid_pixels = pixels_3d[
            geom.grid_left : geom.grid_left + geom.grid_width,
            geom.grid_top : geom.grid_top + geom.grid_height,
        ]

        # Check sample cells to confirm exact RGB match without antialiasing
        cell_px = geom.cell_px
        for row in range(0, profile.rows, 10):
            for col in range(0, profile.cols, 10):
                sym = symbols[row, col]
                expected_rgb = PALETTE_RGB[sym]
                sample_x = col * cell_px + cell_px // 2
                sample_y = row * cell_px + cell_px // 2
                actual_rgb = grid_pixels[sample_x, sample_y]
                assert np.array_equal(actual_rgb, expected_rgb), f"Cell ({row},{col}) RGB mismatch"

        pygame.quit()

    @pytest.mark.skipif(
        os.environ.get("SUPERQR_PERFORMANCE_TESTS") != "1",
        reason="machine-dependent render budget; enable explicitly on benchmark hardware",
    )
    def test_rendering_performance_is_gpu_friendly_and_fast(self) -> None:
        pygame.init()
        profile = ColorGrid8Profile(384, 336, 30, version=TRANSFER_HEADER_VERSION)
        symbols = np.random.randint(0, 8, size=(profile.rows, profile.cols), dtype=np.uint8)
        renderer = ColorGrid8Renderer()

        # Warm up
        renderer.render_symbols(profile, symbols, 1920, 1080)

        # Measure 50 frames
        t0 = time.perf_counter()
        for _ in range(50):
            renderer.render_symbols(profile, symbols, 1920, 1080)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0 / 50.0

        print(f"Avg render time for 384x336: {elapsed_ms:.2f} ms/frame")
        assert elapsed_ms < 6.0, f"Render time {elapsed_ms:.2f} ms exceeds 6.0 ms budget"
        pygame.quit()
