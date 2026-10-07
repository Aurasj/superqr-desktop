"""Standalone physical sender for Macrochroma v4 (480x388 @ 30 FPS)."""

from __future__ import annotations

import argparse
from pathlib import Path
import queue
import struct
import threading
import time
import zlib
from collections.abc import Callable

import numpy as np
import pygame

from superqr_desktop.lab.lab_display import LabDisplayController
from superqr_desktop.lab.macrochroma import (
    MACROCHROMA_VERSION,
    HEADER_MAGIC,
    HEADER_ROWS,
    TILE_PAYLOAD_BYTES,
    PALETTE_RGB,
    MacrochromaProfile,
    MacrochromaTile,
    generate_spatial_parity_tiles,
    encode_macrochroma_frame_grid,
    render_macrochroma_rgb_image,
)

FIDUCIAL_MODULES = 7
MIN_FINDER_MODULE_PX = 6
ORIENTATION_CORNER = "TL"


class _FramePrefetcher:
    def __init__(self, frame_factory: Callable[[int], pygame.Surface], total_frames: int, depth: int = 16):
        self.frame_factory = frame_factory
        self.total_frames = total_frames
        self.queue: queue.Queue[tuple[int, pygame.Surface] | BaseException] = queue.Queue(maxsize=depth)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="macrochroma-prefetch", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        idx = 0
        try:
            while not self.stop_event.is_set():
                surf = self.frame_factory(idx)
                item = (idx, surf)
                while not self.stop_event.is_set():
                    try:
                        self.queue.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                idx += 1
                if self.total_frames > 0 and idx >= self.total_frames:
                    idx = 0
        except BaseException as exc:
            while not self.stop_event.is_set():
                try:
                    self.queue.put(exc, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def get(self) -> tuple[int, pygame.Surface]:
        item = self.queue.get()
        if isinstance(item, BaseException):
            raise RuntimeError("Macrochroma frame prefetch failed") from item
        return item

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)


def build_package(file_path: Path) -> tuple[bytes, str, int, int]:
    raw_data = file_path.read_bytes()
    filename = file_path.name
    mime = "application/octet-stream"
    file_size = len(raw_data)
    file_crc = zlib.crc32(raw_data) & 0xFFFFFFFF

    fn_bytes = filename.encode("utf-8")
    mime_bytes = mime.encode("utf-8")
    header = struct.pack(
        ">4sHHQI",
        b"SQP7",
        len(fn_bytes),
        len(mime_bytes),
        file_size,
        file_crc,
    ) + fn_bytes + mime_bytes
    package = header + raw_data
    return package, filename, file_size, file_crc


def create_carrier_background(
    grid_w_px: int,
    grid_h_px: int,
    max_w: int,
    max_h: int,
) -> tuple[pygame.Surface, int, int, int, int]:
    finder_module_px = max(MIN_FINDER_MODULE_PX, min(max_w, max_h) // 160)
    finder_size_px = FIDUCIAL_MODULES * finder_module_px
    quiet_zone_px = max(16, finder_module_px * 3)
    outer_margin_px = finder_size_px + quiet_zone_px

    carrier_w = grid_w_px + 2 * outer_margin_px
    carrier_h = grid_h_px + 2 * outer_margin_px

    carrier = pygame.Surface((carrier_w, carrier_h))
    carrier.fill((255, 255, 255))

    grid_left = outer_margin_px
    grid_top = outer_margin_px

    # Draw 4 finders (7x7 module standard concentric squares)
    finder_inset = max(6, finder_module_px)
    cx_left = finder_inset
    cx_right = carrier_w - finder_inset - finder_size_px
    cy_top = finder_inset
    cy_bottom = carrier_h - finder_inset - finder_size_px

    corners = [
        (cx_left, cy_top),
        (cx_right, cy_top),
        (cx_right, cy_bottom),
        (cx_left, cy_bottom),
    ]

    for fx, fy in corners:
        # Outer 7x7 black
        pygame.draw.rect(carrier, (0, 0, 0), (fx, fy, finder_size_px, finder_size_px))
        # Inner 5x5 white
        w_inset = finder_module_px
        w_size = finder_size_px - 2 * w_inset
        pygame.draw.rect(carrier, (255, 255, 255), (fx + w_inset, fy + w_inset, w_size, w_size))
        # Center 3x3 black
        c_inset = finder_module_px * 2
        c_size = finder_size_px - 2 * c_inset
        pygame.draw.rect(carrier, (0, 0, 0), (fx + c_inset, fy + c_inset, c_size, c_size))

    # Asymmetric orientation marker in TL quadrant
    om_size = max(6, finder_module_px)
    om_x = int(cx_left + finder_size_px + (grid_left - (cx_left + finder_size_px) - om_size) / 2.0)
    om_y = int(cy_top + (finder_size_px - om_size) / 2.0)
    pygame.draw.rect(carrier, (0, 0, 0), (om_x, om_y, om_size, om_size))

    return carrier, grid_left, grid_top, carrier_w, carrier_h


class MacrochromaTransferSession:
    def __init__(
        self,
        file_path: Path,
        profile: MacrochromaProfile,
        carousel_block: int = 12,
    ):
        self.profile = profile
        self.carousel_block = carousel_block
        self.package, self.filename, self.file_size, self.file_crc = build_package(file_path)

        frame_cap = profile.data_tiles_per_frame * TILE_PAYLOAD_BYTES
        self.total_data_frames = (len(self.package) + frame_cap - 1) // frame_cap
        self.carousel_groups = (self.total_data_frames + carousel_block - 1) // carousel_block

        # Pre-slice data tiles
        self.data_frames_tiles: list[list[MacrochromaTile]] = []
        for f_idx in range(self.total_data_frames):
            offset = f_idx * frame_cap
            chunk = self.package[offset : offset + frame_cap]
            tiles = []
            for t_idx in range(profile.data_tiles_per_frame):
                t_off = t_idx * TILE_PAYLOAD_BYTES
                t_chunk = chunk[t_off : t_off + TILE_PAYLOAD_BYTES]
                if len(t_chunk) < TILE_PAYLOAD_BYTES:
                    t_chunk = t_chunk + bytes(TILE_PAYLOAD_BYTES - len(t_chunk))
                tiles.append(MacrochromaTile(tile_index=t_idx, frame_index=f_idx, payload=t_chunk, is_parity=False))
            # Generate spatial parity tiles
            spatial_parities = generate_spatial_parity_tiles(
                tiles, profile.parity_tiles_per_frame, f_idx
            )
            tiles.extend(spatial_parities)
            self.data_frames_tiles.append(tiles)

        # Generate carousel parity frames
        self.carousel_frames_tiles: list[list[MacrochromaTile]] = []
        for b in range(self.carousel_groups):
            start_f = b * carousel_block
            end_f = min(self.total_data_frames, (b + 1) * carousel_block)
            c_frame_idx = self.total_data_frames + b
            c_tiles = []
            for t_idx in range(profile.data_tiles_per_frame):
                group_payloads = [self.data_frames_tiles[f][t_idx].payload for f in range(start_f, end_f)]
                mat = np.frombuffer(b"".join(group_payloads), dtype=np.uint8).reshape((len(group_payloads), TILE_PAYLOAD_BYTES))
                accum = np.bitwise_xor.reduce(mat, axis=0).tobytes()
                c_tiles.append(MacrochromaTile(tile_index=t_idx, frame_index=c_frame_idx, payload=accum, is_parity=False))
            # Generate spatial parity for carousel frame
            c_spatial = generate_spatial_parity_tiles(
                c_tiles, profile.parity_tiles_per_frame, c_frame_idx
            )
            c_tiles.extend(c_spatial)
            self.carousel_frames_tiles.append(c_tiles)

        # Build complete frame sequence with 12+1 interleaved carousel parity
        self.sequence_tiles: list[tuple[int, list[MacrochromaTile]]] = []
        for b in range(self.carousel_groups):
            start_f = b * carousel_block
            end_f = min(self.total_data_frames, (b + 1) * carousel_block)
            for f in range(start_f, end_f):
                self.sequence_tiles.append((f, self.data_frames_tiles[f]))
            self.sequence_tiles.append((self.total_data_frames + b, self.carousel_frames_tiles[b]))

        self.total_sequence_frames = len(self.sequence_tiles)

    def get_frame_tiles(self, seq_idx: int) -> tuple[int, list[MacrochromaTile]]:
        return self.sequence_tiles[seq_idx % self.total_sequence_frames]


def run_sender(
    file_path: Path,
    fps: int = 30,
    display_index: int = 0,
    fullscreen: bool = True,
    windowed: bool = False,
    frames_limit: int = 0,
) -> int:
    profile = MacrochromaProfile(
        cols=480,
        rows=388,
        fps=fps,
        preset="MEDIUM",
    )
    session = MacrochromaTransferSession(file_path, profile)

    pygame.init()
    LabDisplayController._apply_event_filter()
    display = LabDisplayController(requested_fps=profile.fps)
    display.setup_display(
        display_index=display_index,
        fullscreen=not windowed,
    )
    if display.screen is None:
        raise RuntimeError("Display screen not initialized")

    max_w, max_h = display.screen.get_size()
    cell_px = 2
    grid_w_px = profile.cols * cell_px
    grid_h_px = profile.rows * cell_px

    background_surface, grid_left, grid_top, carrier_w, carrier_h = create_carrier_background(
        grid_w_px, grid_h_px, max_w, max_h
    )

    print("\n" + "=" * 50)
    print("MACROCHROMA V4 PHYSICAL OPTICAL SENDER")
    print(f"File: {session.filename} ({session.file_size:,} bytes, CRC32={session.file_crc:08X})")
    print(f"Grid: 480x388 @ {fps} FPS (cell={cell_px}px, carrier={carrier_w}x{carrier_h}px)")
    print(f"Data Frames: {session.total_data_frames} (Carousel Parity Frames: {session.carousel_groups})")
    print(f"Total Sequence Length: {session.total_sequence_frames} frames (12+1 Carousel Interleaved)")
    print(f"Theoretical Protected Goodput: {profile.protected_goodput_kib_s:.1f} KiB/s ({profile.protected_goodput_kib_s/1024.0:.3f} MiB/s)")
    print("=" * 50 + "\n")

    print("Pre-rendering frame surfaces to memory...")
    pre_start = time.perf_counter()
    cached_surfaces: list[pygame.Surface] = []
    for seq_idx in range(session.total_sequence_frames):
        f_idx, tiles = session.get_frame_tiles(seq_idx)
        luma, chroma = encode_macrochroma_frame_grid(profile, f_idx, tiles)
        rgb_img = render_macrochroma_rgb_image(profile, luma, chroma, cell_px=cell_px)
        surf_grid = pygame.surfarray.make_surface(np.transpose(rgb_img, (1, 0, 2)))
        carrier = background_surface.copy()
        carrier.blit(surf_grid, (grid_left, grid_top))
        cached_surfaces.append(carrier)
    print(f"Pre-rendered {len(cached_surfaces)} frames in {time.perf_counter() - pre_start:.2f}s.\n")

    display.configure_dwell(profile.fps)
    started = time.perf_counter()
    frame_count = 0

    try:
        while frames_limit <= 0 or frame_count < frames_limit:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    return 0

            surf = cached_surfaces[frame_count % len(cached_surfaces)]
            display.present(surf)
            if display.dwell.record_present():
                display.record_dwell_complete()
                display.dwell.advance_logical_frame()
                frame_count += 1

                if frame_count % 30 == 0:
                    elapsed = max(1e-9, time.perf_counter() - started)
                    fps_achieved = frame_count / elapsed
                    r_p50, r_p95 = display.diag.render_percentiles()
                    print(
                        f"Frame {frame_count:4d} | FPS: {fps_achieved:5.2f} | "
                        f"p50/p95: {r_p50:.1f}/{r_p95:.1f} ms | "
                        f"Late: {display.diag.late_present_count}"
                    )
        return 0
    finally:
        display.close()
        pygame.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Macrochroma v4 Physical Sender")
    parser.add_argument("--file", type=Path, required=True, help="File to transfer")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS")
    parser.add_argument("--display", type=int, default=0, help="Display index")
    parser.add_argument("--windowed", action="store_true", help="Run windowed instead of fullscreen")
    parser.add_argument("--frames", type=int, default=0, help="Number of frames to send (0=loop)")
    args = parser.parse_args()

    return run_sender(
        file_path=args.file,
        fps=args.fps,
        display_index=args.display,
        windowed=args.windowed,
        frames_limit=args.frames,
    )


if __name__ == "__main__":
    raise SystemExit(main())
