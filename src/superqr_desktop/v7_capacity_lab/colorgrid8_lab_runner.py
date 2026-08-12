"""Standalone physical sender for the ColorGrid8 LAB."""

from __future__ import annotations

import argparse
import time

import pygame

from superqr_desktop.v7_capacity_lab.colorgrid8_core import (
    FPS_SWEEP,
    GRID_SWEEP,
    ColorGrid8Profile,
)
from superqr_desktop.v7_capacity_lab.colorgrid8_renderer import ColorGrid8Renderer
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController


def _parse_grid(value: str) -> tuple[int, int]:
    try:
        cols_text, rows_text = value.lower().split("x", 1)
        dims = int(cols_text), int(rows_text)
    except Exception as exc:
        raise argparse.ArgumentTypeError("grid must look like 168x144") from exc
    if dims not in GRID_SWEEP:
        raise argparse.ArgumentTypeError(
            f"unsupported grid {value}; choose " + ", ".join(f"{c}x{r}" for c, r in GRID_SWEEP)
        )
    return dims


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SuperQR ColorGrid8 physical LAB sender")
    parser.add_argument("--grid", type=_parse_grid, default=(168, 144))
    parser.add_argument("--fps", type=int, choices=FPS_SWEEP, default=30)
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--display", type=int, default=0, help="zero-based display index")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument(
        "--calibration-seconds",
        type=float,
        default=0.35,
        help="seconds to show each of the 8 solid palette symbols before data; 0 disables",
    )
    return parser


def run(profile: ColorGrid8Profile, *, frames: int, display_index: int, fullscreen: bool, calibration_seconds: float) -> int:
    pygame.init()
    LabDisplayController._apply_event_filter()
    display = LabDisplayController(dwell_epochs=60.0 / profile.fps)
    display.setup_display(display_index=display_index, fullscreen=fullscreen, marker_size=1000)
    renderer = ColorGrid8Renderer()

    # Fit against the real SDL canvas, not the monitor dimensions. This matters in
    # --windowed mode where LabDisplayController intentionally creates a 1000px canvas.
    if display.screen is None:
        raise RuntimeError("ColorGrid8 LAB display was not created")
    canvas_width, canvas_height = display.screen.get_size()
    max_width = max(1, int(canvas_width * 0.98))
    max_height = max(1, int(canvas_height * 0.98))

    try:
        if calibration_seconds > 0:
            for symbol in range(8):
                surface, _ = renderer.render_calibration(
                    symbol, profile, max_width=max_width, max_height=max_height
                )
                deadline = time.perf_counter() + calibration_seconds
                while time.perf_counter() < deadline:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT or (
                            event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                        ):
                            return 0
                    display.present(surface)

        display.configure_dwell(60.0 / profile.fps)
        frame_index = 0
        render_ms_total = 0.0
        surface = None
        started = time.perf_counter()
        while frames <= 0 or frame_index < frames:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    return 0

            if surface is None:
                t0 = time.perf_counter()
                surface, geometry = renderer.render(
                    profile,
                    frame_index & 0xFFFF,
                    max_width=max_width,
                    max_height=max_height,
                )
                render_ms_total += (time.perf_counter() - t0) * 1000.0
                if frame_index == 0:
                    print(
                        f"{profile.name}: cell={geometry.cell_px}px, "
                        f"raw={profile.raw_kib_s:.2f} KiB/s, "
                        f"payload={profile.payload_kib_s:.2f} KiB/s, "
                        f"post20={profile.post_fec_kib_s():.2f} KiB/s"
                    )

            display.present(surface)
            if display.dwell.record_present():
                display.record_dwell_complete()
                display.dwell.advance_logical_frame()
                frame_index += 1
                surface = None
                if frame_index and frame_index % 30 == 0:
                    elapsed = max(1e-9, time.perf_counter() - started)
                    print(
                        f"frame={frame_index} logical={frame_index / elapsed:.2f} fps "
                        f"render_avg={render_ms_total / frame_index:.2f} ms "
                        f"late={display.diag.late_present_count}"
                    )
        return 0
    finally:
        display.close()
        pygame.quit()


def main() -> int:
    args = build_parser().parse_args()
    cols, rows = args.grid
    if args.frames < 0:
        raise SystemExit("--frames must be >= 0 (0 means continuous)")
    profile = ColorGrid8Profile(cols=cols, rows=rows, fps=args.fps)
    return run(
        profile,
        frames=args.frames,
        display_index=args.display,
        fullscreen=not args.windowed,
        calibration_seconds=max(0.0, args.calibration_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
