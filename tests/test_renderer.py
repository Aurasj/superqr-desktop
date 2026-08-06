import pytest
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame
from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.renderer import V6Renderer

def test_v6_renderer_draw():
    pygame.init()
    contract, _ = load_contract()
    renderer = V6Renderer(contract, size=800)
    renderer.draw_static_features()
    renderer.draw_grid("deterministic_random")
    
    assert renderer.surface.get_width() == 800
    assert renderer.surface.get_height() == 800
    pygame.quit()
