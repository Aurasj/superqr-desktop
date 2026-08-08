"""Lean tests for the preserved V7 Capacity Lab and product-shell invariants."""

import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from superqr_desktop.v7_capacity_lab import protocol_bridge
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer


def test_protocol_bridge_accessors_are_available():
    assert protocol_bridge.get_protocol_model() is not None
    assert protocol_bridge.get_protocol_palettes() is not None
    assert protocol_bridge.get_protocol_profiles() is not None


def test_reference_vectors_are_packaged():
    vectors = protocol_bridge.load_reference_vectors()
    assert len(vectors["vectors"]) == 14


def test_v6_visual_contract_is_preserved():
    contract = protocol_bridge.load_v6_visual_contract()
    assert contract["contract_version"] == "v6"
    assert contract["anchors"]["size"] == 80


def test_capacity_lab_can_render_reference_frame():
    pygame.init()
    try:
        profiles = protocol_bridge.get_protocol_profiles()
        model = protocol_bridge.get_protocol_model()
        profile = model.LabProfile(
            name="lab_96x96_candidate_8_a_seed42",
            grid_size=96,
            palette_name="candidate_8_a",
            layout_name="single",
            seed=42,
            dwell_epochs=2,
        )
        seq = profiles.build_frame_sequence(profile, num_data_frames=1)
        data_frame = next(f for f in seq.frames if not f.is_calibration)
        renderer = LabRenderer(marker_size=600)
        renderer.prepare_logical_frame(data_frame.symbol_matrix)
        assert renderer.cached_frame_display is not None
    finally:
        pygame.quit()


def test_app_has_single_product_entry_point_without_mode_selector():
    import inspect
    import superqr_desktop.app as app

    assert callable(app.main)
    source = inspect.getsource(app.ControlApp)
    assert "V6 Stable" not in source
    assert "V7 Development" not in source
    assert "Engine / Protocol" not in source
    assert "OPTICAL PROFILE" in source
    assert "TRANSFER" in source


def test_debug_patterns_still_use_frozen_v6_carrier():
    import superqr_desktop.app as app

    values = {value for _, value in app.DEBUG_PATTERNS}
    assert values == {"deterministic_random", "checkerboard", "black", "white"}
