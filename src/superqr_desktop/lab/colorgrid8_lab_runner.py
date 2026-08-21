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
    TRANSFER_FPS_SWEEP,
    TRANSFER_HEADER_VERSION,
    ColorGrid8Profile,
    build_symbol_frame,
)
from superqr_desktop.lab.colorgrid8_renderer import ColorGrid8Renderer
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
    display = LabDisplayController(dwell_epochs=60.0 / profile.fps)
    display.setup_display(
        display_index=display_index,
        fullscreen=fullscreen,
        marker_size=1000,
        window_size=(1100, 950) if not fullscreen else None,
    )
    renderer = ColorGrid8Renderer()

    # Fit against the real SDL canvas, not the monitor dimensions. This matters in
    # --windowed mode where LabDisplayController intentionally creates a 1000px canvas.
    if display.screen is None:
        raise RuntimeError("ColorGrid8 LAB display was not created")
    canvas_width, canvas_height = display.screen.get_size()
    max_width = max(1, int(canvas_width * 0.98))
    max_height = max(1, int(canvas_height * 0.98))

    # A default 256-frame 168x144 run is only ~6 MiB as uint8 symbols. Let
    # finite runs prefetch completely while the balanced warm-up is visible,
    # keeping the Python PRNG thread out of most timing-critical presentation.
    # Transfer mode uses a smaller fixed queue because dense v2 matrices are
    # larger and package bytes are regenerated from disk on every carousel.
    prefetch_depth = 12 if transfer is not None else (max(1, frames) if 0 < frames <= 512 else 64)
    factory = transfer.symbol_frame if transfer is not None else (
        lambda index: build_symbol_frame(profile, index & 0xFFFF)
    )
    prefetch = _FramePrefetcher(factory, frames, depth=prefetch_depth)

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
                    print(
                        f"frame={frame_index} logical={frame_index / elapsed:.2f} fps "
                        f"live_render_avg={render_ms_total / frame_index:.2f} ms "
                        f"prefetch_q={prefetch.queue.qsize()} "
                        f"late={display.diag.late_present_count}"
                    )
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
    version = TRANSFER_HEADER_VERSION if args.file is not None else 1
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
