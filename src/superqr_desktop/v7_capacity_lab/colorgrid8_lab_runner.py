"""Standalone physical sender for the ColorGrid8 LAB."""

from __future__ import annotations

import argparse
import queue
import threading
import time

import numpy as np
import pygame

from superqr_desktop.v7_capacity_lab.colorgrid8_core import (
    FPS_SWEEP,
    GRID_SWEEP,
    ColorGrid8Profile,
    build_symbol_frame,
)
from superqr_desktop.v7_capacity_lab.colorgrid8_renderer import ColorGrid8Renderer
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController


class _FramePrefetcher:
    """Bounded symbol-matrix producer that keeps PRNG work off frame transitions."""

    def __init__(self, profile: ColorGrid8Profile, frame_limit: int, depth: int = 64):
        self.profile = profile
        self.frame_limit = frame_limit
        self.queue: queue.Queue[tuple[int, np.ndarray] | BaseException] = queue.Queue(maxsize=depth)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="colorgrid8-prefetch", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        frame_index = 0
        try:
            while not self.stop_event.is_set() and (self.frame_limit <= 0 or frame_index < self.frame_limit):
                matrix = build_symbol_frame(self.profile, frame_index & 0xFFFF)
                item: tuple[int, np.ndarray] | BaseException = (frame_index, matrix)
                while not self.stop_event.is_set():
                    try:
                        self.queue.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                frame_index += 1
        except BaseException as exc:  # propagate producer failures to the presenter
            while not self.stop_event.is_set():
                try:
                    self.queue.put(exc, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def get(self, expected_index: int) -> np.ndarray:
        item = self.queue.get()
        if isinstance(item, BaseException):
            raise RuntimeError("ColorGrid8 frame prefetch failed") from item
        frame_index, matrix = item
        if frame_index != expected_index:
            raise RuntimeError(
                f"ColorGrid8 prefetch desynchronized: expected {expected_index}, got {frame_index}"
            )
        return matrix

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)


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
        default=1.0,
        help="seconds to show one balanced 8-color warm-up board before data; 0 disables",
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

    # A default 256-frame 168x144 campaign is only ~6 MiB as uint8 symbols. Let
    # finite campaigns prefetch completely while the balanced warm-up is visible,
    # keeping the Python PRNG thread out of most timing-critical presentation.
    # Continuous mode stays bounded to ~64 frames (~1.5 MiB at the default grid).
    prefetch_depth = max(1, frames) if 0 < frames <= 512 else 64
    prefetch = _FramePrefetcher(profile, frames, depth=prefetch_depth)

    try:
        if calibration_seconds > 0:
            surface, warmup_geometry = renderer.render_calibration_board(
                profile, max_width=max_width, max_height=max_height
            )
            print(
                f"warmup: balanced 8-color board, cell={warmup_geometry.cell_px}px, "
                f"duration={calibration_seconds:.2f}s, prefetch_depth={prefetch_depth}"
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
                symbols = prefetch.get(frame_index)
                t0 = time.perf_counter()
                surface, geometry = renderer.render_symbols(
                    profile,
                    symbols,
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
                        f"live_render_avg={render_ms_total / frame_index:.2f} ms "
                        f"prefetch_q={prefetch.queue.qsize()} "
                        f"late={display.diag.late_present_count}"
                    )
        return 0
    finally:
        prefetch.close()
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
