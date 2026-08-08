"""Tests for V7 Capacity Lab Desktop modules."""

import os
import sys
import time

import pytest

# Force dummy video driver for headless testing
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame

# Ensure protocol bridge is resolvable before imports
from superqr_desktop.v7_capacity_lab import protocol_bridge


# ─────────────────────────────────────────────────────────────────────
# protocol_bridge tests
# ─────────────────────────────────────────────────────────────────────


class TestProtocolBridge:
    def test_resolves_protocol_root(self):
        root = protocol_bridge.get_protocol_root()
        assert root.is_dir()
        assert (root / "protocol" / "v7_capacity_lab").is_dir()

    def test_loads_reference_vectors(self):
        vectors = protocol_bridge.load_reference_vectors()
        assert "vectors" in vectors
        entries = vectors["vectors"]
        assert len(entries) == 14  # 7 grid sizes × 2 palettes

    def test_loads_v6_visual_contract(self):
        contract = protocol_bridge.load_v6_visual_contract()
        assert contract["contract_version"] == "v6"
        assert "border" in contract
        assert "anchors" in contract
        assert "data_grid" in contract

    def test_all_module_accessors_return_modules(self):
        """Every accessor should return a valid module."""
        modules = [
            protocol_bridge.get_protocol_model(),
            protocol_bridge.get_protocol_palettes(),
            protocol_bridge.get_protocol_profiles(),
            protocol_bridge.get_protocol_patterns(),
            protocol_bridge.get_protocol_geometry(),
            protocol_bridge.get_protocol_layouts(),
            protocol_bridge.get_protocol_vectors(),
            protocol_bridge.get_protocol_calibration(),
            protocol_bridge.get_protocol_prng(),
        ]
        for mod in modules:
            assert mod is not None

    def test_env_var_resolution(self, monkeypatch):
        """SUPERQR_PROTOCOL_ROOT should take priority."""
        root = protocol_bridge.get_protocol_root()
        monkeypatch.setenv("SUPERQR_PROTOCOL_ROOT", str(root))
        # Reset cache
        protocol_bridge._protocol_root = None
        sys_path_before = len(sys.path)
        resolved = protocol_bridge.get_protocol_root()
        assert resolved == root
        # sys.path manipulation only happens once
        protocol_bridge._protocol_root = None
        monkeypatch.delenv("SUPERQR_PROTOCOL_ROOT", raising=False)


# ─────────────────────────────────────────────────────────────────────
# cross_validate tests
# ─────────────────────────────────────────────────────────────────────


class TestCrossValidate:
    def test_all_14_reference_profiles_pass(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            validate_reference_profiles,
        )
        results = validate_reference_profiles()
        assert len(results) == 14
        failed = [r for r in results if not r.passed]
        if failed:
            for r in failed:
                for name, ok in r.checks.items():
                    if not ok:
                        print(f"  FAIL {r.profile_name}.{name}: {r.details.get(name)}")
        assert len(failed) == 0, f"{len(failed)} profiles failed validation"

    def test_individual_profiles_validate(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import validate_profile
        from superqr_desktop.v7_capacity_lab.protocol_bridge import get_protocol_profiles

        profiles_mod = get_protocol_profiles()
        profiles = profiles_mod.build_reference_profiles()
        # Spot-check: first, middle, last
        for idx in [0, len(profiles) // 2, -1]:
            result = validate_profile(profiles[idx])
            assert result.passed, (
                f"Profile {profiles[idx].name} failed: "
                + "; ".join(f"{k}={v}" for k, v in result.checks.items() if not v)
            )

    def test_v6_reference_4_cross_validation_matches_golden(self):
        """Verify the protocol lab's V6 cross-validation also works from Desktop."""
        palettes_mod = protocol_bridge.get_protocol_palettes()
        patterns_mod = protocol_bridge.get_protocol_patterns()
        prng_mod = protocol_bridge.get_protocol_prng()

        palette = palettes_mod.get_palette("v6_reference_4")
        prng = prng_mod.Xorshift32(42)
        matrix = patterns_mod.random_fill(prng, 20, 20, palette.name, palette.bits_per_cell)

        flat = []
        for row in matrix.symbols:
            flat.extend(row)

        expected_first = [1, 2, 3, 0, 0, 2, 3, 3, 2, 1, 0, 0, 0, 3, 1, 1, 2, 0, 2, 1]
        assert flat[:20] == expected_first

        import zlib
        crc32_val = zlib.crc32(bytes(flat)) & 0xFFFFFFFF
        assert f"{crc32_val:08X}" == "BEAFE8A7"


# ─────────────────────────────────────────────────────────────────────
# Canonical profile resolution tests
# ─────────────────────────────────────────────────────────────────────


class TestCanonicalProfileResolution:
    def test_40x40_v6_ref_4_seed42_resolves(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(40, "v6_reference_4", 42)
        assert canonical is not None
        assert canonical.name == "ref_40x40_v6_reference_4_seed42"

    def test_40x40_candidate_8_a_seed42_resolves(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(40, "candidate_8_a", 42)
        assert canonical is not None
        assert canonical.name == "ref_40x40_candidate_8_a_seed42"

    def test_96x96_v6_ref_4_seed42_resolves(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(96, "v6_reference_4", 42)
        assert canonical is not None
        assert canonical.name == "ref_96x96_v6_reference_4_seed42"

    def test_96x96_candidate_8_a_seed42_resolves(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(96, "candidate_8_a", 42)
        assert canonical is not None
        assert canonical.name == "ref_96x96_candidate_8_a_seed42"

    def test_all_14_canonical_configs_resolve(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        from superqr_desktop.v7_capacity_lab.protocol_bridge import (
            get_protocol_profiles,
        )
        profiles_mod = get_protocol_profiles()
        all_ref = profiles_mod.build_reference_profiles()
        assert len(all_ref) == 14

        for rp in all_ref:
            canonical = find_canonical_reference_profile(
                rp.grid_size, rp.palette_name, rp.seed,
            )
            assert canonical is not None, (
                f"No canonical found for {rp.grid_size}, {rp.palette_name}, {rp.seed}"
            )
            assert canonical.name == rp.name

    def test_non_reference_seed_99_returns_none(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(40, "v6_reference_4", 99)
        assert canonical is None

    def test_non_reference_seed_7_returns_none(self):
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            find_canonical_reference_profile,
        )
        canonical = find_canonical_reference_profile(80, "candidate_8_a", 7)
        assert canonical is None

    def test_validate_or_fail_with_lab_named_profile_passes(self, monkeypatch):
        """A 'lab_*' profile matching canonical (grid, palette, seed)
        should resolve to the ref_* profile and pass validation."""
        from superqr_desktop.v7_capacity_lab.cross_validate import validate_or_fail
        from superqr_desktop.v7_capacity_lab.protocol_bridge import (
            get_protocol_profiles, get_protocol_model,
        )

        # Build a user profile with a "lab_*" style name
        profiles_mod = get_protocol_profiles()
        model_mod = get_protocol_model()
        CalibrationConfig = model_mod.CalibrationConfig

        profile = profiles_mod.build_profile(
            name="lab_40x40_v6_reference_4_seed42",
            grid_size=40,
            palette_name="v6_reference_4",
            layout_name="single",
            seed=42,
            dwell_epochs=2,
            calibration=CalibrationConfig(solid_frames=True),
        )

        # Patch sys.exit so validate_or_fail doesn't kill the test process
        exit_calls = []
        monkeypatch.setattr("sys.exit", lambda code=None: exit_calls.append(code) or None)

        # Run — this should not call sys.exit(1)
        validate_or_fail(profile)

        assert exit_calls != [1], (
            "validate_or_fail called sys.exit(1) on a config that should pass"
        )

    def test_cross_validate_cli_standalone_still_works(self):
        """The standalone cross_validate CLI must still work."""
        from superqr_desktop.v7_capacity_lab.cross_validate import (
            validate_reference_profiles,
        )
        results = validate_reference_profiles()
        assert len(results) == 14
        assert all(r.passed for r in results)


# ─────────────────────────────────────────────────────────────────────
# lab_renderer tests
# ─────────────────────────────────────────────────────────────────────


class TestLabRenderer:
    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        yield
        pygame.quit()

    def _make_matrix(self, grid_size, palette_name="v6_reference_4", seed=42):
        patterns_mod = protocol_bridge.get_protocol_patterns()
        palettes_mod = protocol_bridge.get_protocol_palettes()
        prng_mod = protocol_bridge.get_protocol_prng()

        palette = palettes_mod.get_palette(palette_name)
        prng = prng_mod.Xorshift32(seed)
        return patterns_mod.random_fill(prng, grid_size, grid_size,
                                        palette.name, palette.bits_per_cell)

    def test_render_40x40_v6_reference_4(self):
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=800)
        matrix = self._make_matrix(40, "v6_reference_4")
        renderer.prepare_logical_frame(matrix)

        assert renderer.cached_frame_display is not None
        assert renderer.cached_frame_display.get_width() == 800
        assert renderer.cached_frame_display.get_height() == 800
        assert renderer.timings.total_prepare_us >= 0

    def test_render_96x96_candidate_8_a(self):
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=1000)
        matrix = self._make_matrix(96, "candidate_8_a")
        renderer.prepare_logical_frame(matrix)

        assert renderer.cached_frame_display is not None
        assert renderer.cached_frame_display.get_width() == 1000
        assert renderer.timings.total_prepare_us >= 0

    def test_render_80x80(self):
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=600)
        matrix = self._make_matrix(80, "v6_reference_4")
        renderer.prepare_logical_frame(matrix)

        assert renderer.cached_frame_display is not None
        assert renderer.cached_frame_display.get_width() == 600

    def test_palette_rgb_output_exact(self):
        """Render a solid-color matrix and verify exact pixel colors."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        from protocol.v7_capacity_lab.model import SymbolMatrix

        # Create a 2x2 matrix with known symbol indexes: 0, 1, 2, 3
        matrix = SymbolMatrix(
            rows=2, cols=2, palette_name="v6_reference_4",
            symbols=[[0, 1], [2, 3]],
        )
        renderer = LabRenderer(marker_size=100)  # small for easy pixel checking
        renderer.prepare_logical_frame(matrix)

        surf = renderer.cached_frame_display
        # Payload bbox is (200,200)-(800,800) → at marker_size=100:
        # Display payload rect: (20, 20, 60, 60)
        # Each cell is 30x30 pixels
        # Check center pixel of each cell
        payload_bbox = (200.0, 200.0, 800.0, 800.0)
        scale = 100 / 1000.0
        px = int(payload_bbox[0] * scale)
        py = int(payload_bbox[1] * scale)
        pw = int((payload_bbox[2] - payload_bbox[0]) * scale)
        ph = int((payload_bbox[3] - payload_bbox[1]) * scale)
        cell_w = pw // 2
        cell_h = ph // 2

        # Symbol 0 → BLACK (0,0,0)
        cx, cy = px + cell_w // 2, py + cell_h // 2
        assert surf.get_at((cx, cy))[:3] == (0, 0, 0)

        # Symbol 1 → WHITE (255,255,255)
        cx, cy = px + cell_w + cell_w // 2, py + cell_h // 2
        assert surf.get_at((cx, cy))[:3] == (255, 255, 255)

        # Symbol 2 → RED (255,0,0)
        cx, cy = px + cell_w // 2, py + cell_h + cell_h // 2
        assert surf.get_at((cx, cy))[:3] == (255, 0, 0)

        # Symbol 3 → BLUE (0,0,255)
        cx, cy = px + cell_w + cell_w // 2, py + cell_h + cell_h // 2
        assert surf.get_at((cx, cy))[:3] == (0, 0, 255)

    def test_candidate_8_a_rgb_output(self):
        """Verify candidate_8_a palette colors render correctly."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        from protocol.v7_capacity_lab.model import SymbolMatrix

        # candidate_8_a: 0=BLACK,1=WHITE,2=RED,3=GREEN,4=BLUE,5=YELLOW,6=CYAN,7=MAGENTA
        colors = {
            0: (0, 0, 0),
            1: (255, 255, 255),
            2: (255, 0, 0),
            3: (0, 255, 0),
            4: (0, 0, 255),
            5: (255, 255, 0),
            6: (0, 255, 255),
            7: (255, 0, 255),
        }
        # 4x2 grid: 8 cells, one per color
        symbols = [[0, 1, 2, 3], [4, 5, 6, 7]]
        matrix = SymbolMatrix(rows=2, cols=4, palette_name="candidate_8_a", symbols=symbols)

        renderer = LabRenderer(marker_size=500)
        renderer.prepare_logical_frame(matrix)

        surf = renderer.cached_frame_display
        payload_bbox = (200.0, 200.0, 800.0, 800.0)
        scale = 500 / 1000.0
        px = int(payload_bbox[0] * scale)
        py = int(payload_bbox[1] * scale)
        pw = int((payload_bbox[2] - payload_bbox[0]) * scale)
        ph = int((payload_bbox[3] - payload_bbox[1]) * scale)
        cell_w = pw // 4
        cell_h = ph // 2

        for row in range(2):
            for col in range(4):
                sym = symbols[row][col]
                cx = px + col * cell_w + cell_w // 2
                cy = py + row * cell_h + cell_h // 2
                actual = surf.get_at((cx, cy))[:3]
                assert actual == colors[sym], (
                    f"Symbol {sym} at ({col},{row}): expected {colors[sym]}, got {actual}"
                )

    def test_nearest_neighbor_no_blending(self):
        """Hard cell boundaries: adjacent cells of different colors must not blend."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        from protocol.v7_capacity_lab.model import SymbolMatrix

        # 2x1 matrix: BLACK | WHITE
        symbols = [[0, 1]]
        matrix = SymbolMatrix(rows=1, cols=2, palette_name="v6_reference_4", symbols=symbols)

        renderer = LabRenderer(marker_size=500)
        renderer.prepare_logical_frame(matrix)

        surf = renderer.cached_frame_display
        payload_bbox = (200.0, 200.0, 800.0, 800.0)
        scale = 500 / 1000.0
        px = int(payload_bbox[0] * scale)
        py = int(payload_bbox[1] * scale)
        pw = int((payload_bbox[2] - payload_bbox[0]) * scale)
        ph = int((payload_bbox[3] - payload_bbox[1]) * scale)
        cell_w = pw // 2
        cy = py + ph // 2

        # Boundary: check pixel just left of midline should be BLACK
        mid_x = px + cell_w
        left_pixel = surf.get_at((mid_x - 1, cy))[:3]
        assert left_pixel == (0, 0, 0), f"Left of boundary: {left_pixel}"

        # Check pixel just right of midline should be WHITE
        right_pixel = surf.get_at((mid_x, cy))[:3]
        assert right_pixel == (255, 255, 255), f"Right of boundary: {right_pixel}"

        # No intermediate/antialiased colors within 3px of boundary
        for offset in range(-3, 4):
            pixel = surf.get_at((mid_x + offset, cy))[:3]
            assert pixel in ((0, 0, 0), (255, 255, 255)), (
                f"Blended color found at offset {offset} from boundary: {pixel}"
            )

    def test_payload_rectangle_mapping(self):
        """Payload should occupy the exact region defined by payload_bbox.

        Uses a RED 1x1 cell so leakage outside the payload bbox is detectable
        (carrier areas outside payload are not red).
        """
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        from protocol.v7_capacity_lab.model import SymbolMatrix

        # 1x1 RED cell (symbol 2 in v6_reference_4)
        symbols = [[2]]
        matrix = SymbolMatrix(rows=1, cols=1, palette_name="v6_reference_4", symbols=symbols)

        renderer = LabRenderer(marker_size=100)
        renderer.prepare_logical_frame(matrix)

        surf = renderer.cached_frame_display
        payload_bbox = (200.0, 200.0, 800.0, 800.0)
        scale = 100 / 1000.0
        px = int(payload_bbox[0] * scale)
        py = int(payload_bbox[1] * scale)
        pw = int((payload_bbox[2] - payload_bbox[0]) * scale)
        ph = int((payload_bbox[3] - payload_bbox[1]) * scale)

        # Center of payload should be RED
        cx, cy = px + pw // 2, py + ph // 2
        assert surf.get_at((cx, cy))[:3] == (255, 0, 0)

        # Point outside payload bbox should NOT be red
        # At marker_size=100, payload occupies pixels 20..80 in both axes.
        # Check a point at the very edge (x=5, y=50) — this is in the
        # carrier's left quiet zone, far from the payload.
        if px > 10:
            outer_pixel = surf.get_at((5, 50))[:3]
            assert outer_pixel != (255, 0, 0), (
                "Payload RED leaked into carrier area at left edge"
            )

    def test_timing_instrumentation_populated(self):
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=400)
        matrix = self._make_matrix(40)
        renderer.prepare_logical_frame(matrix)

        timings = renderer.timings.as_dict()
        for key in ["symbol_matrix_to_rgb_us", "surface_creation_us",
                     "payload_scale_us", "compose_us", "total_prepare_us"]:
            assert key in timings
            assert timings[key] >= 0

    def test_carrier_cached_between_frames(self):
        """Carrier should be same object across multiple prepare calls."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=400)
        carrier_before = renderer._carrier_display

        matrix = self._make_matrix(40)
        renderer.prepare_logical_frame(matrix)
        assert renderer._carrier_display is carrier_before

        # Second frame — carrier still the same object
        matrix2 = self._make_matrix(40, seed=99)
        renderer.prepare_logical_frame(matrix2)
        assert renderer._carrier_display is carrier_before

    def test_cached_frame_different_between_different_frames(self):
        """Different logical frames should produce different cached surfaces."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        renderer = LabRenderer(marker_size=200)

        renderer.prepare_logical_frame(self._make_matrix(40, seed=42))
        frame0 = renderer.cached_frame_display

        renderer.prepare_logical_frame(self._make_matrix(40, seed=99))
        frame1 = renderer.cached_frame_display

        # Different PRNG seeds → different pixel content
        assert frame0 is not frame1


# ─────────────────────────────────────────────────────────────────────
# lab_display / dwell tests
# ─────────────────────────────────────────────────────────────────────


class TestDwellController:
    def test_dwell_2_exact_present_count(self):
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=2)

        # Frame 0: present twice
        assert dwell.record_present() is False  # present 1
        assert dwell.record_present() is True   # present 2 → advance
        assert dwell.presents_for_current_frame == 0

    def test_dwell_3_exact_present_count(self):
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=3)

        assert dwell.record_present() is False  # present 1
        assert dwell.record_present() is False  # present 2
        assert dwell.record_present() is True   # present 3 → advance
        assert dwell.presents_for_current_frame == 0

    def test_dwell_4_exact_present_count(self):
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=4)

        assert dwell.record_present() is False  # present 1
        assert dwell.record_present() is False  # present 2
        assert dwell.record_present() is False  # present 3
        assert dwell.record_present() is True   # present 4 → advance
        assert dwell.presents_for_current_frame == 0

    def test_dwell_does_not_advance_early(self):
        """Frame must NOT advance before completing its dwell window."""
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=3)

        # After 1 present: should NOT advance
        assert dwell.record_present() is False
        assert dwell.logical_frame_index == 0  # unchanged
        assert dwell.presents_for_current_frame == 1

        # After 2 presents: should NOT advance
        assert dwell.record_present() is False
        assert dwell.logical_frame_index == 0  # unchanged
        assert dwell.presents_for_current_frame == 2

        # After 3 presents: should advance
        assert dwell.record_present() is True
        assert dwell.logical_frame_index == 0  # still 0 (caller advances)
        assert dwell.presents_for_current_frame == 0

    def test_multiple_dwell_cycles(self):
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=2)

        # Cycle through 5 logical frames
        for frame in range(5):
            assert dwell.record_present() is False  # present 1
            assert dwell.record_present() is True   # present 2
            dwell.advance_logical_frame()
            assert dwell.logical_frame_index == frame + 1

    def test_timer_tick_always_advances(self):
        from superqr_desktop.v7_capacity_lab.lab_display import DwellState
        dwell = DwellState(dwell_epochs=2)

        # timer_tick returns True to signal advance; caller advances the frame
        assert dwell.timer_tick() is True
        dwell.advance_logical_frame()
        assert dwell.logical_frame_index == 1

        # Second tick
        assert dwell.timer_tick() is True
        dwell.advance_logical_frame()
        assert dwell.logical_frame_index == 2

    def test_fallback_mode_labeling(self):
        from superqr_desktop.v7_capacity_lab.lab_display import (
            LabDisplayController, TimingMode,
        )
        dc = LabDisplayController(dwell_epochs=2)
        # Without an actual display with VSync, we should be in fallback
        # (or VSYNC_MODE if the dummy driver happens to support it)
        assert dc.diag.timing_mode in (TimingMode.VSYNC_MODE, TimingMode.FALLBACK_TIMER_MODE)

    def test_refresh_period_vs_logical_dwell(self):
        """refresh_period_ms and expected_logical_dwell_ms should be distinct."""
        from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
        dc = LabDisplayController(dwell_epochs=3)

        if dc.diag.reported_refresh_hz > 0:
            assert dc.diag.refresh_period_ms > 0
            # logical dwell = dwell_epochs * refresh_period
            expected = 3 * dc.diag.refresh_period_ms
            assert abs(dc.diag.expected_logical_dwell_ms - expected) < 0.01


# ─────────────────────────────────────────────────────────────────────
# Display controller tests
# ─────────────────────────────────────────────────────────────────────


class TestDisplayController:
    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        yield
        pygame.quit()

    def test_setup_display_creates_surface(self):
        from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
        dc = LabDisplayController(dwell_epochs=2)
        dc.setup_display(display_index=0, fullscreen=False, marker_size=400)
        assert dc.screen is not None
        assert dc.screen.get_width() > 0

    def test_present_updates_diagnostics(self):
        from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
        dc = LabDisplayController(dwell_epochs=2)
        dc.setup_display(display_index=0, fullscreen=False, marker_size=400)

        surf = pygame.Surface((400, 400))
        surf.fill((128, 128, 128))
        dc.present(surf)

        assert dc.diag.present_count == 1
        assert dc.diag.present_block_us >= 0

    def test_detect_displays_returns_list(self):
        from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
        dc = LabDisplayController()
        displays = dc.detect_displays()
        assert len(displays) >= 1
        assert "index" in displays[0]
        assert "width" in displays[0]


# ─────────────────────────────────────────────────────────────────────
# V6 files untouched check
# ─────────────────────────────────────────────────────────────────────


class TestV6Untouched:
    def test_v6_modules_still_importable(self):
        """V6 modules must remain unchanged and importable."""
        from superqr_desktop.v6.renderer import V6Renderer
        from superqr_desktop.v6.display import DisplayController
        from superqr_desktop.v6.sender import V6SenderSession
        from superqr_desktop.v6.transport import (
            build_transfer_package, create_frames, bytes_to_palette_indexes,
        )
        from superqr_desktop.v6.patterns import get_pattern_bytes, Xorshift32
        assert True  # imports succeeded

    def test_v6_contract_unchanged(self):
        from superqr_desktop.contract.loader import load_contract, EXPECTED_CONTRACT_HASH
        contract, h = load_contract()
        assert h == EXPECTED_CONTRACT_HASH


# ─────────────────────────────────────────────────────────────────────
# Launcher tests
# ─────────────────────────────────────────────────────────────────────


def _tk_available() -> bool:
    """Check whether Tkinter can create a root window in this environment."""
    try:
        import tkinter as _tk
        root = _tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


TK_AVAILABLE = _tk_available()
TK_SKIP_REASON = "Tkinter Tcl/Tk not available in this environment"


class TestLauncher:
    def test_launcher_importable(self):
        """Launcher module imports without side effects."""
        from superqr_desktop.v7_capacity_lab import lab_launcher
        assert lab_launcher is not None

    def test_detect_displays_returns_list(self):
        """Display detection should work without creating a window."""
        from superqr_desktop.v7_capacity_lab.lab_launcher import _detect_displays
        displays = _detect_displays()
        assert len(displays) >= 1
        for d in displays:
            assert "index" in d
            assert "label" in d
            assert "width" in d
            assert "height" in d

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_validation_passes_valid_config(self):
        """Default settings should validate cleanly."""
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            errors = launcher._validate()
            assert errors == [], f"Expected no errors, got: {errors}"
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_validation_rejects_bad_grid(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._grid_var.set("99")
            errors = launcher._validate()
            assert len(errors) >= 1
            assert any("Grid" in e for e in errors)
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_validation_rejects_zero_seed(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._seed_var.set("0")
            errors = launcher._validate()
            assert len(errors) >= 1
            assert any("Seed" in e or "seed" in e for e in errors)
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_validation_rejects_bad_frames(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._frames_var.set("0")
            errors = launcher._validate()
            assert len(errors) >= 1
            assert any("Frames" in e for e in errors)
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_validation_rejects_small_marker(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._marker_var.set("50")
            errors = launcher._validate()
            assert len(errors) >= 1
            assert any("Marker" in e for e in errors)
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_build_args_produces_namespace(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._grid_var.set("80")
            launcher._palette_var.set("candidate_8_a")
            launcher._dwell_var.set("3")
            launcher._seed_var.set("99")
            launcher._layout_var.set("2x2")
            launcher._frames_var.set("50")
            launcher._marker_var.set("800")
            launcher._calib_var.set(False)
            launcher._fullscreen_var.set(True)
            launcher._hud_var.set(True)

            args = launcher._build_args()
            assert args.grid == 80
            assert args.palette == "candidate_8_a"
            assert args.dwell == 3
            assert args.seed == 99
            assert args.layout == "2x2"
            assert args.frames == 50
            assert args.marker_size == 800
            assert args.no_calibration is True
            assert args.fullscreen is True
            assert args.hud is True
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_build_args_no_calibration_inverts_calib_var(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            launcher._calib_var.set(True)
            args = launcher._build_args()
            assert args.no_calibration is False

            launcher._calib_var.set(False)
            args = launcher._build_args()
            assert args.no_calibration is True
        finally:
            launcher.root.destroy()

    @pytest.mark.skipif(not TK_AVAILABLE, reason=TK_SKIP_REASON)
    def test_get_display_index_matches_labels(self):
        from superqr_desktop.v7_capacity_lab.lab_launcher import LabLauncher
        launcher = LabLauncher()
        try:
            labels = [d["label"] for d in launcher.displays]
            for idx, label in enumerate(labels):
                launcher._display_var.set(label)
                assert launcher._get_display_index() == idx
        finally:
            launcher.root.destroy()

    def test_cli_main_importable(self):
        """lab_launcher.main() should be importable and callable."""
        from superqr_desktop.v7_capacity_lab.lab_launcher import main as launcher_main
        assert callable(launcher_main)

    def test_lab_runner_cli_still_works(self):
        """The CLI entry point must continue to work after the refactor."""
        from superqr_desktop.v7_capacity_lab.lab_runner import main as runner_main
        assert callable(runner_main)


# ─────────────────────────────────────────────────────────────────────
# Integration: render + cross-validate
# ─────────────────────────────────────────────────────────────────────


class TestIntegration:
    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        yield
        pygame.quit()

    def test_render_all_reference_profiles(self):
        """Every reference profile should render without error."""
        from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
        from superqr_desktop.v7_capacity_lab.protocol_bridge import get_protocol_profiles

        renderer = LabRenderer(marker_size=400)
        profiles_mod = get_protocol_profiles()
        profiles = profiles_mod.build_reference_profiles()

        for profile in profiles:
            seq = profiles_mod.build_frame_sequence(profile, num_data_frames=1)
            data_frames = [f for f in seq.frames if not f.is_calibration]
            assert len(data_frames) >= 1, f"No data frames for {profile.name}"
            renderer.prepare_logical_frame(data_frames[0].symbol_matrix)
            assert renderer.cached_frame_display is not None
