import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.contract.loader import load_contract
from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.v7.profiles import get_profile
from superqr_desktop.v7.renderer import V7TransferRenderer


def test_v7_renderer_draws_selected_marker_size():
    pygame.init()
    profile = get_profile(0)
    renderer = V7TransferRenderer(800, profile)
    renderer.prepare_symbols([0] * profile.cell_count)
    surface = renderer.cached_frame_display
    assert surface is not None
    assert surface.get_size() == (800, 800)
    pygame.quit()


def test_display_metrics_scale_with_marker_size():
    contract, _ = load_contract()
    display = DisplayController(contract)
    metrics = display._metrics_for_marker(800)
    assert metrics.active_width == 704
    assert metrics.active_height == 704
    assert metrics.grid_width == 480
    assert metrics.grid_height == 480
