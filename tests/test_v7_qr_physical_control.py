import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import build_qr_matrix, qr_controls


def test_qr_controls_use_declared_900px_canvas_and_integer_module_scale():
    pygame.init()
    try:
        renderer = LabRenderer(marker_size=600)
        for control in qr_controls().values():
            matrix = build_qr_matrix(control, 0)
            native = renderer.build_qr_native_surface(matrix, int(control["quiet_zone_modules"]))
            renderer.prepare_qr_native_surface(native)
            surface = renderer.cached_frame_display
            assert surface is not None
            assert surface.get_size() == (control["display_size_px"], control["display_size_px"])

            total = control["total_modules"]
            scale = control["integer_module_scale_px"]
            rendered = total * scale
            assert rendered == control["rendered_size_px"]
            offset = (control["display_size_px"] - rendered) // 2
            quiet = control["quiet_zone_modules"] * scale
            # Top-left finder begins immediately after the quiet zone and must
            # remain an exact black integer-scaled QR module.
            sample = offset + quiet + scale // 2
            assert tuple(surface.get_at((sample, sample)))[:3] == (0, 0, 0)
            assert tuple(surface.get_at((offset, offset)))[:3] == (255, 255, 255)
    finally:
        pygame.quit()


def test_display_centers_actual_surface_not_custom_grid_marker_size():
    pygame.display.init()
    controller = LabDisplayController()
    try:
        controller.screen = pygame.display.set_mode((1000, 1000))
        controller.marker_size = 600
        controller.diag.timing_mode = controller.diag.timing_mode.VSYNC_MODE
        frame = pygame.Surface((900, 900))
        frame.fill((0, 0, 0))
        controller.present(frame)
        # A 900px QR control centered on a 1000px canvas starts at 50, not at
        # the 200px offset that a stale 600px marker-size calculation would use.
        assert tuple(controller.screen.get_at((49, 500)))[:3] == (255, 255, 255)
        assert tuple(controller.screen.get_at((50, 500)))[:3] == (0, 0, 0)
        assert tuple(controller.screen.get_at((950, 500)))[:3] == (255, 255, 255)
    finally:
        controller.close()
