"""Standalone physical sender for the ColorGrid8 LAB."""

from __future__ import annotations

import argparse
from pathlib import Path
import queue
import threading
import time
from collections.abc import Callable

import numpy as np
import pygame

from superqr_desktop.lab.colorgrid8_core import (
    FPS_SWEEP,
    ALL_GRIDS,
    DIAGNOSTIC_GRIDS,
    TRANSFER_GRIDS,
    DIAGNOSTIC_HEADER_VERSION,
    TRANSFER_FPS_SWEEP,
    TRANSFER_HEADER_VERSION,
    ColorGrid8Profile,
    build_symbol_frame,
)
from superqr_desktop.lab.colorgrid8_renderer import ColorGrid8Renderer, ColorGrid8RenderGeometry
from superqr_desktop.lab.colorgrid8_transfer import ColorGrid8TransferSession
from superqr_desktop.lab.lab_display import LabDisplayController


class _FramePrefetcher:
    """Bounded symbol-matrix producer that keeps PRNG work off frame transitions."""

    def __init__(
        self,
        frame_factory: Callable[[int], np.ndarray],
        frame_limit: int,
        depth: int = 64,
    ):
        self.frame_factory = frame_factory
        self.frame_limit = frame_limit
        self.queue: queue.Queue[tuple[int, np.ndarray] | BaseException] = queue.Queue(maxsize=depth)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="colorgrid8-prefetch", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        frame_index = 0
        try:
            while not self.stop_event.is_set() and (self.frame_limit <= 0 or frame_index < self.frame_limit):
                matrix = self.frame_factory(frame_index)
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
    if dims not in ALL_GRIDS:
        raise argparse.ArgumentTypeError(
            f"unsupported grid {value}; choose " + ", ".join(f"{c}x{r}" for c, r in ALL_GRIDS)
        )
    return dims


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SuperQR ColorGrid8 physical LAB sender")
    parser.add_argument("--grid", type=_parse_grid)
    parser.add_argument("--fps", type=int, choices=sorted(set(FPS_SWEEP + TRANSFER_FPS_SWEEP)))
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--file", type=Path, help="send a file continuously with ColorGrid8 transport v2")
    parser.add_argument("--display", type=int, default=0, help="zero-based display index")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument(
        "--calibration-seconds",
        type=float,
        default=1.0,
        help="seconds to show one balanced 8-color warm-up board before data; 0 disables",
    )
    return parser


def print_test_summary(
    profile: ColorGrid8Profile,
    display: LabDisplayController,
    geometry: ColorGrid8RenderGeometry | None,
    frame_index: int,
    started_time: float,
) -> None:
    elapsed = max(1e-9, time.perf_counter() - started_time)
    achieved_fps = frame_index / elapsed if frame_index > 0 else 0.0
    log_p50, log_p95 = display.diag.logical_frame_percentiles()
    rnd_p50, rnd_p95 = display.diag.render_percentiles()
    late_skipped = f"{display.diag.late_present_count} late / {display.diag.estimated_skipped_refreshes} skipped"
    cell_px = geometry.cell_px if geometry else 0
    carrier_px = f"{geometry.carrier_width}x{geometry.carrier_height}" if geometry else "unknown"
    finder_px = geometry.finder_size_px if geometry else 0
    warning_str = display.diag.timing_warning if display.diag.timing_warning else "none (refresh is divisible)"

    print("\n" + "=" * 40)
    print("COLORGRID8 SENDER TEST")
    print(f"profile: {profile.name}")
    print(f"logical FPS: {profile.fps}")
    print(f"detected refresh: {display.diag.reported_refresh_hz:.1f} Hz")
    print(f"achieved logical FPS: {achieved_fps:.2f}")
    print(f"cell px: {cell_px}")
    print(f"carrier px: {carrier_px}")
    print(f"finder px: {finder_px}")
    print(f"logical frame p50: {log_p50:.2f} ms")
    print(f"logical frame p95: {log_p95:.2f} ms")
    print(f"late/skipped presents: {late_skipped}")
    print(f"render p50/p95: {rnd_p50:.2f} ms / {rnd_p95:.2f} ms")
    print(f"warning if refresh is not suitable: {warning_str}")
    print("=" * 40 + "\n")


def run(
    profile: ColorGrid8Profile,
    *,
    frames: int,
    display_index: int,
    fullscreen: bool,
    calibration_seconds: float,
    transfer: ColorGrid8TransferSession | None = None,
) -> int:
    pygame.init()
    LabDisplayController._apply_event_filter()
    display = LabDisplayController(requested_fps=profile.fps)
    display.setup_display(
        display_index=display_index,
        fullscreen=fullscreen,
    )
    renderer = ColorGrid8Renderer()

    if display.screen is None:
        raise RuntimeError("ColorGrid8 LAB display was not created")
    max_width, max_height = display.screen.get_size()

    if display.diag.timing_warning:
        print(f"\n[TIMING WARNING] {display.diag.timing_warning}\n")

    prefetch_depth = 12 if transfer is not None else (max(1, frames) if 0 < frames <= 512 else 64)
    factory = transfer.symbol_frame if transfer is not None else (
        lambda index: build_symbol_frame(profile, index & 0xFFFF)
    )
    prefetch = _FramePrefetcher(factory, frames, depth=prefetch_depth)
    last_geometry: ColorGrid8RenderGeometry | None = None
    frame_index = 0
    started = time.perf_counter()

    try:
        if calibration_seconds > 0:
            surface, warmup_geometry = renderer.render_calibration_board(
                profile, max_width=max_width, max_height=max_height
            )
            last_geometry = warmup_geometry
            print(
                f"warmup: balanced 8-color board, cell={warmup_geometry.cell_px}px, "
                f"carrier={warmup_geometry.carrier_width}x{warmup_geometry.carrier_height}px, "
                f"finder={warmup_geometry.finder_size_px}px, "
                f"duration={calibration_seconds:.2f}s, prefetch_depth={prefetch_depth}"
            )
            deadline = time.perf_counter() + calibration_seconds
            while time.perf_counter() < deadline:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT or (
                        event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                    ):
                        print_test_summary(profile, display, last_geometry, 0, started)
                        return 0
                display.present(surface)

        display.configure_dwell(profile.fps)
        surface = None
        started = time.perf_counter()
        while frames <= 0 or frame_index < frames:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    print_test_summary(profile, display, last_geometry, frame_index, started)
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
                render_ms = (time.perf_counter() - t0) * 1000.0
                display.diag.record_render_duration(render_ms)
                last_geometry = geometry
                if frame_index == 0:
                    print(
                        f"geometry: cell={geometry.cell_px}px, "
                        f"grid={geometry.grid_width}x{geometry.grid_height}px, "
                        f"carrier={geometry.carrier_width}x{geometry.carrier_height}px, "
                        f"margin={geometry.outer_margin_px}px, "
                        f"finder={geometry.finder_size_px}px, "
                        f"orientation={geometry.orientation_corner}"
                    )
                    if transfer is None:
                        print(
                            f"{profile.name}: cell={geometry.cell_px}px, "
                            f"raw={profile.raw_kib_s:.2f} KiB/s, "
                            f"payload={profile.payload_kib_s:.2f} KiB/s, "
                            f"post20={profile.post_fec_kib_s():.2f} KiB/s"
                        )
                    else:
                        info = transfer.info
                        print(
                            f"transfer={info.filename} size={info.file_size} session={info.session_id:08X} "
                            f"data_frames={info.total_data_frames} carousel={info.carousel_frames} "
                            f"chunk={info.chunk_bytes} cell={geometry.cell_px}px "
                            f"channel_budget={info.channel_kib_s:.1f} KiB/s "
                            f"xor8_budget={info.protected_kib_s:.1f} KiB/s"
                        )

            display.present(surface)
            if display.dwell.record_present():
                display.record_dwell_complete()
                display.dwell.advance_logical_frame()
                frame_index += 1
                surface = None
                if frame_index and frame_index % 30 == 0:
                    elapsed = max(1e-9, time.perf_counter() - started)
                    r_p50, r_p95 = display.diag.render_percentiles()
                    print(
                        f"frame={frame_index} logical={frame_index / elapsed:.2f} fps "
                        f"render_p50/p95={r_p50:.2f}/{r_p95:.2f} ms "
                        f"prefetch_q={prefetch.queue.qsize()} "
                        f"late={display.diag.late_present_count}"
                    )
        print_test_summary(profile, display, last_geometry, frame_index, started)
        return 0
    finally:
        prefetch.close()
        if transfer is not None:
            transfer.close()
        display.close()
        pygame.quit()


def main() -> int:
    args = build_parser().parse_args()
    cols, rows = args.grid or ((336, 288) if args.file is not None else (168, 144))
    fps = args.fps or (60 if args.file is not None else 30)
    if args.frames < 0:
        raise SystemExit("--frames must be >= 0 (0 means continuous)")
    version = (
        TRANSFER_HEADER_VERSION
        if (args.file is not None or (cols, rows) in TRANSFER_GRIDS)
        else DIAGNOSTIC_HEADER_VERSION
    )
    profile = ColorGrid8Profile(cols=cols, rows=rows, fps=fps, version=version)
    transfer = ColorGrid8TransferSession(args.file, profile) if args.file is not None else None
    try:
        return run(
            profile,
            frames=args.frames,
            display_index=args.display,
            fullscreen=not args.windowed,
            calibration_seconds=max(0.0, args.calibration_seconds),
            transfer=transfer,
        )
    finally:
        if transfer is not None:
            transfer.close()


if __name__ == "__main__":
    raise SystemExit(main())
