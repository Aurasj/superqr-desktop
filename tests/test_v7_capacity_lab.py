"""Focused tests for the internal V7 Capacity Lab support.

Capacity Lab remains a development/diagnostic subsystem. The product UI no
longer exposes V6/V7 application modes, so tests here intentionally do not
instantiate Tk or assert the retired engine selector.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from superqr_desktop.v7_capacity_lab import protocol_bridge


def test_packaged_reference_vectors_are_self_contained(monkeypatch):
    monkeypatch.delenv("SUPERQR_PROTOCOL_ROOT", raising=False)
    protocol_bridge._protocol_root = None
    protocol_bridge._protocol_available = False
    protocol_bridge._reference_vectors_cache = None
    vectors = protocol_bridge.load_reference_vectors()
    assert len(vectors["vectors"]) == 14


def test_packaged_v6_carrier_contract_is_available(monkeypatch):
    monkeypatch.delenv("SUPERQR_PROTOCOL_ROOT", raising=False)
    protocol_bridge._protocol_root = None
    protocol_bridge._protocol_available = False
    protocol_bridge._v6_contract_cache = None
    contract = protocol_bridge.load_v6_visual_contract()
    assert contract["contract_version"] == "v6"
    assert "anchors" in contract
    assert "data_grid" in contract


def test_all_14_reference_profiles_cross_validate():
    from superqr_desktop.v7_capacity_lab.cross_validate import validate_reference_profiles

    results = validate_reference_profiles()
    assert len(results) == 14
    assert all(r.passed for r in results)


def test_canonical_profile_resolution():
    from superqr_desktop.v7_capacity_lab.cross_validate import find_canonical_reference_profile

    assert find_canonical_reference_profile(40, "v6_reference_4", 42).name == "ref_40x40_v6_reference_4_seed42"
    assert find_canonical_reference_profile(96, "candidate_8_a", 42).name == "ref_96x96_candidate_8_a_seed42"
    assert find_canonical_reference_profile(40, "v6_reference_4", 99) is None


def test_local_prng_v6_golden():
    from superqr_desktop.v7_capacity_lab._local.palettes import get_palette
    from superqr_desktop.v7_capacity_lab._local.patterns import random_fill
    from superqr_desktop.v7_capacity_lab._local.prng import Xorshift32
    from superqr_desktop.v7_capacity_lab._local.vectors import compute_symbol_hashes

    palette = get_palette("v6_reference_4")
    matrix = random_fill(Xorshift32(42), 20, 20, palette.name, palette.bits_per_cell)
    hashes = compute_symbol_hashes(matrix)
    assert hashes["symbol_crc32"] == "BEAFE8A7"


@pytest.fixture
def pygame_session():
    pygame.init()
    yield
    pygame.quit()


def test_lab_renderer_40x40(pygame_session):
    from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
    from superqr_desktop.v7_capacity_lab.protocol_bridge import get_protocol_profiles

    profiles = get_protocol_profiles()
    profile = profiles.build_profile(
        name="lab_40x40_v6_reference_4_seed42",
        grid_size=40,
        palette_name="v6_reference_4",
        layout_name="single",
        seed=42,
        dwell_epochs=2,
    )
    seq = profiles.build_frame_sequence(profile, num_data_frames=1)
    data_frame = next(f for f in seq.frames if not f.is_calibration)
    renderer = LabRenderer(marker_size=800)
    renderer.prepare_logical_frame(data_frame.symbol_matrix)
    assert renderer.cached_frame_display is not None
    assert renderer.cached_frame_display.get_size() == (800, 800)


def test_lab_renderer_96x96(pygame_session):
    from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
    from superqr_desktop.v7_capacity_lab.protocol_bridge import get_protocol_profiles

    profiles = get_protocol_profiles()
    profile = profiles.build_profile(
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


def test_app_has_single_product_entry_point_without_mode_selector():
    import inspect
    import superqr_desktop.app as app

    assert callable(app.main)
    source = inspect.getsource(app.ControlApp)
    assert "V6 Stable" not in source
    assert "V7 Development" not in source
    assert "Engine / Protocol" not in source
    assert "Send File — V7" in source


def test_debug_patterns_still_use_frozen_v6_carrier():
    import superqr_desktop.app as app

    values = {value for _, value in app.DEBUG_PATTERNS}
    assert values == {"deterministic_random", "checkerboard", "black", "white"}
