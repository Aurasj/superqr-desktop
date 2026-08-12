"""V7 Capacity Lab CLI runner.

Minimal Pygame event loop with keyboard controls.
No Tkinter. Single-threaded predictable display/present loop.

Dwell semantics (VSYNC_MODE):
    Each logical frame receives exactly dwell_epochs completed presents
    before the next frame is selected. The frame does NOT advance before
    the present that completes the current dwell window.

Usage:
    python -m superqr_desktop.v7_capacity_lab.lab_runner [options]
"""

from __future__ import annotations

import argparse
import time
from enum import Enum, auto

import pygame

from superqr_desktop.v7_capacity_lab.protocol_bridge import (
    get_protocol_model,
    get_protocol_profiles,
)
from superqr_desktop.v7_capacity_lab.cross_validate import validate_or_fail
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.lab_display import (
    LabDisplayController,
    TimingMode,
    FALLBACK_REFRESH_HZ,
)


class RunnerState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()


DIAG_INTERVAL = 2.0  # seconds between console diagnostic prints


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SuperQR V7 Capacity Lab — experimental renderer",
    )
    p.add_argument("--grid", type=int, default=40,
                   choices=[40, 48, 56, 64, 72, 80, 96],
                   help="Grid size (NxN)")
    p.add_argument("--palette", type=str, default="v6_reference_4",
                   choices=["v6_reference_4", "candidate_8_a"],
                   help="Candidate palette")
    p.add_argument("--dwell", type=int, default=2,
                   choices=[2, 3, 4],
                   help="Dwell epochs (refresh cycles per logical frame)")
    p.add_argument("--seed", type=int, default=42,
                   help="PRNG seed")
    p.add_argument("--layout", type=str, default="single",
                   choices=["single", "2x2"],
                   help="Payload layout")
    p.add_argument("--frames", type=int, default=100,
                   help="Number of data frames")
    p.add_argument("--fullscreen", action="store_true",
                   help="Fullscreen output")
    p.add_argument("--display", type=int, default=0,
                   help="Display index")
    p.add_argument("--marker-size", type=int, default=1000,
                   help="Marker output size in pixels")
    p.add_argument("--no-calibration", action="store_true",
                   help="Disable calibration frames")
    p.add_argument("--hud", action="store_true",
                   help="Enable minimal on-screen status")
    return p


class LabRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args

        # Build profile via protocol
        profiles_mod = get_protocol_profiles()
        model_mod = get_protocol_model()
        CalibrationConfig = model_mod.CalibrationConfig

        calib = CalibrationConfig(
            solid_frames=not args.no_calibration,
            preamble_frames=0,
            reference_cell_density=0,
        )

        self.profile = profiles_mod.build_profile(
            name=f"lab_{args.grid}x{args.grid}_{args.palette}_seed{args.seed}",
            grid_size=args.grid,
            palette_name=args.palette,
            layout_name=args.layout,
            seed=args.seed,
            dwell_epochs=args.dwell,
            calibration=calib,
        )

        # Build frame sequence
        self.sequence = profiles_mod.build_frame_sequence(self.profile, args.frames)
        self.total_frames = len(self.sequence.frames)
        self.logical_frame_idx = 0

        # State
        self.state = RunnerState.IDLE
        self._running = True

        # Display
        pygame.init()
        LabDisplayController._apply_event_filter()
        self.display = LabDisplayController(dwell_epochs=args.dwell)
        self.display.setup_display(
            display_index=args.display,
            fullscreen=args.fullscreen,
            marker_size=args.marker_size,
        )

        # Renderer
        self.renderer = LabRenderer(marker_size=args.marker_size)

        # Font for optional HUD
        self._hud_font: pygame.font.Font | None = None
        if args.hud:
            try:
                self._hud_font = pygame.font.SysFont("Consolas", 12)
            except Exception:
                self._hud_font = None

        # Fallback timer
        self._fallback_last_tick: float = 0.0

        # Diagnostic rate limit
        self._last_diag_time: float = 0.0
        self._total_presents: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main entry point."""
        # Cross-validate before anything appears on screen
        self._validate()

        # Print startup diagnostics
        self._print_startup()

        # Prepare initial frame
        self._prepare_current()

        # Main loop
        try:
            self._main_loop()
        finally:
            pygame.quit()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        print("Running cross-validation...")
        validate_or_fail(self.profile)
        print()

    def _print_startup(self) -> None:
        diag = self.display.diag
        print("V7 Capacity Lab — Startup")
        print(f"  Profile:        {self.profile.name}")
        print(f"  Grid:           {self.profile.grid_size}x{self.profile.grid_size}")
        print(f"  Palette:        {self.profile.palette_name}")
        print(f"  Layout:         {self.profile.layout_name}")
        print(f"  Dwell epochs:   {self.profile.dwell_epochs}")
        print(f"  Total frames:   {self.total_frames}")
        print(f"  Requested VSync: {diag.requested_vsync}")
        print(f"  VSync enabled:  {diag.actual_vsync_enabled}")
        print(f"  Refresh rate:   {diag.reported_refresh_hz:.1f} Hz" if diag.reported_refresh_hz > 0
              else "  Refresh rate:   unknown")
        print(f"  Timing mode:    {diag.timing_mode.name}")
        print(f"  Refresh period: {diag.refresh_period_ms:.2f} ms")
        print(f"  Logical dwell:  {diag.expected_logical_dwell_ms:.2f} ms")
        print(f"  Marker size:    {self.args.marker_size} px")
        print(f"  Fullscreen:     {self.args.fullscreen}")
        mode_str = "TIMER-BASED" if diag.timing_mode == TimingMode.FALLBACK_TIMER_MODE else "HARDWARE-SYNCED"
        print(f"  Timing label:   {mode_str}")
        print()
        print("Controls: [Space] Start/Pause  [S] Stop  [N] Next frame  [Q/Esc] Quit")
        print()

    def _prepare_current(self) -> None:
        """Prepare the current logical frame for display."""
        frame = self.sequence.frames[self.logical_frame_idx]
        self.renderer.prepare_logical_frame(frame.symbol_matrix)
        self.display.dwell.presents_for_current_frame = 0

    def _main_loop(self) -> None:
        diag = self.display.diag
        vsync_mode = diag.timing_mode == TimingMode.VSYNC_MODE
        fallback_tick_sec = 0.0
        if not vsync_mode:
            fallback_tick_sec = self.display.expected_dwell_ms() / 1000.0

        while self._running:
            self._handle_events()

            if self.state == RunnerState.RUNNING:
                if vsync_mode:
                    self._step_vsync()
                else:
                    self._step_fallback(fallback_tick_sec)
                self._total_presents += 1

            elif self.state == RunnerState.IDLE:
                # Show the initial frame once
                if self.renderer.cached_frame_display:
                    self.display.present(self.renderer.cached_frame_display)

            elif self.state == RunnerState.PAUSED:
                # Hold current frame — re-present to keep window alive
                if self.renderer.cached_frame_display:
                    self.display.present(self.renderer.cached_frame_display)

            self._maybe_print_diagnostics()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key: int) -> None:
        if key in (pygame.K_q, pygame.K_ESCAPE):
            self._running = False
        elif key == pygame.K_SPACE:
            if self.state == RunnerState.RUNNING:
                self.state = RunnerState.PAUSED
                print("[PAUSED]")
            else:
                self.state = RunnerState.RUNNING
                if self.state == RunnerState.IDLE:
                    self.state = RunnerState.RUNNING
                self.display.dwell.presents_for_current_frame = 0
                self.display._dwell_start_time = time.perf_counter()
                print("[RUNNING]")
        elif key == pygame.K_s:
            self.state = RunnerState.PAUSED
            print("[STOPPED]")
        elif key == pygame.K_n:
            if self.state != RunnerState.RUNNING:
                self._advance_frame()
                self._prepare_current()
                # Show the frame
                if self.renderer.cached_frame_display:
                    self.display.present(self.renderer.cached_frame_display)
                print(f"[NEXT] Frame {self.logical_frame_idx}/{self.total_frames - 1}")

    def _step_vsync(self) -> None:
        """One iteration of VSync-synchronized rendering."""
        # 1. Present the cached frame
        if self.renderer.cached_frame_display is None:
            return
        self.display.present(self.renderer.cached_frame_display)

        # 2. Record completed present
        should_advance = self.display.dwell.record_present()

        # 3. Advance if dwell window complete
        if should_advance:
            self.display.record_dwell_complete()
            self.display.dwell.advance_logical_frame()
            self._advance_frame()
            self._prepare_current()

    def _step_fallback(self, tick_sec: float) -> None:
        """One iteration of timer-based rendering."""
        now = time.monotonic()
        if now - self._fallback_last_tick >= tick_sec:
            self._fallback_last_tick = now

            # Advance frame and present
            self.display.record_dwell_complete()
            self._advance_frame()
            self._prepare_current()

            if self.renderer.cached_frame_display:
                self.display.present(self.renderer.cached_frame_display)

    def _advance_frame(self) -> None:
        """Move to the next logical frame, wrapping around."""
        self.logical_frame_idx = (self.logical_frame_idx + 1) % self.total_frames

    def _maybe_print_diagnostics(self) -> None:
        now = time.perf_counter()
        if now - self._last_diag_time < DIAG_INTERVAL:
            return
        self._last_diag_time = now

        diag = self.display.diag
        timings = self.renderer.timings

        mode_label = "VSYNC" if diag.timing_mode == TimingMode.VSYNC_MODE else "TIMER"

        print(
            f"[{mode_label}] "
            f"Frame {self.logical_frame_idx}/{self.total_frames - 1} | "
            f"Presents: {self._total_presents} | "
            f"Prepare: {timings.total_prepare_us}us | "
            f"Present block: {diag.present_block_us}us | "
            f"Present interval: {diag.present_interval_ms:.1f}ms | "
            f"Logical frame: {diag.measured_logical_frame_ms:.1f}ms | "
            f"Late: {diag.late_present_count} | "
            f"Skipped est: {diag.estimated_skipped_refreshes}"
        )


def run_lab(args: argparse.Namespace) -> None:
    """Run the Capacity Lab with the given configuration.

    Legacy CLI entry point. The primary user workflow is now through the
    integrated ControlApp (``superqr-desktop``).
    """
    runner = LabRunner(args)
    runner.run()


def main() -> None:
    """Legacy CLI entry point — kept for headless / scripted use."""
    parser = build_arg_parser()
    args = parser.parse_args()
    run_lab(args)
