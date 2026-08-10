import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import build_qr_matrix, qr_controls


def test_qr_controls_share_selected_marker_canvas_and_keep_integer_modules():
    pygame.init()
    try:
        renderer = LabRenderer(marker_size=600)
        for control in qr_controls().values():
            matrix = build_qr_matrix(control, 0)
            native = renderer.build_qr_native_surface(matrix, int(control["quiet_zone_modules"]))
            renderer.prepare_qr_native_surface(native)
            surface = renderer.cached_frame_display
            assert surface is not None
            assert surface.get_size() == (600, 600)

            total = control["total_modules"]
            scale = 600 // total
            rendered = total * scale
            offset = (600 - rendered) // 2
            quiet = control["quiet_zone_modules"] * scale
            # Top-left finder begins immediately after the quiet zone and must
            # remain an exact black integer-scaled QR module.
            sample = offset + quiet + scale // 2
            assert tuple(surface.get_at((sample, sample)))[:3] == (0, 0, 0)
            assert tuple(surface.get_at((offset, offset)))[:3] == (255, 255, 255)
    finally:
        pygame.quit()


def test_display_centers_common_600px_grid_and_qr_surface():
    pygame.display.init()
    controller = LabDisplayController()
    try:
        controller.screen = pygame.display.set_mode((1000, 1000))
        controller.marker_size = 600
        controller.diag.timing_mode = controller.diag.timing_mode.VSYNC_MODE
        frame = pygame.Surface((600, 600))
        frame.fill((0, 0, 0))
        controller.present(frame)
        assert tuple(controller.screen.get_at((199, 500)))[:3] == (255, 255, 255)
        assert tuple(controller.screen.get_at((200, 500)))[:3] == (0, 0, 0)
        assert tuple(controller.screen.get_at((800, 500)))[:3] == (255, 255, 255)
    finally:
        controller.close()
