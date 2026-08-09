"""Standalone transmitter for the V7 Phase 1 PHY-selection experiment."""

from __future__ import annotations

import argparse
import time

import pygame

from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController, TimingMode
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_matrix,
    encode_frame_index_strip,
    grid_profiles,
    qr_controls,
    validate_grid_vectors,
    validate_qr_vectors,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest


def build_parser() -> argparse.ArgumentParser:
    profiles = list(grid_profiles()) + list(qr_controls())
    parser = argparse.ArgumentParser(description="SuperQR V7 Phase 1 PHY transmitter")
    parser.add_argument("--profile", choices=profiles)
    parser.add_argument("--list", action="store_true", help="list canonical profiles")
    parser.add_argument("--dwell", type=int, choices=[2, 3], default=3)
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--marker-size", type=int, default=800)
    parser.add_argument("--display", type=int, default=0)
    parser.add_argument("--fullscreen", action="store_true")
    return parser


def _list_profiles() -> None:
    for profile in grid_profiles().values():
        print(
            f"{profile['name']}: {profile['cols']}x{profile['rows']} "
            f"{profile['raw_bytes_per_frame']} B/frame"
        )
    for control in qr_controls().values():
        print(
            f"{control['name']}: QR V{control['version']}-{control['error_correction']} "
            f"{control['frame_bytes']} B @ {control['target_fps']:g} fps"
        )


class Phase1Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.manifest = load_phy_selection_manifest()
        self.grid = grid_profiles().get(args.profile)
        self.qr = qr_controls().get(args.profile)
        self.display = LabDisplayController(dwell_epochs=args.dwell)
        self.renderer: LabRenderer | None = None
        self.grid_sequence = GridFrameSequence(args.profile) if self.grid else None
        self.qr_matrices: list[tuple[bytes, ...]] = []
        self.qr_surfaces: list[pygame.Surface] = []
        self.frame_index = 0
        self.last_advance = time.perf_counter()

    def prepare(self) -> None:
        validate_grid_vectors()
        validate_qr_vectors()
        if self.qr:
            print(f"Pre-encoding {self.args.frames} QR controls outside the timed presentation loop...")
            self.qr_matrices = [
                build_qr_matrix(self.qr, index) for index in range(self.args.frames)
            ]
        pygame.init()
        marker_size = int(self.qr["display_size_px"]) if self.qr else self.args.marker_size
        self.display.setup_display(
            display_index=self.args.display,
            fullscreen=self.args.fullscreen,
            marker_size=marker_size,
        )
        self.renderer = LabRenderer(marker_size)
        if self.qr:
            quiet = int(self.qr["quiet_zone_modules"])
            self.qr_surfaces = [
                self.renderer.build_qr_native_surface(matrix, quiet)
                for matrix in self.qr_matrices
            ]
            self.qr_matrices.clear()
        self._prepare_frame()
        print(
            f"READY profile={self.args.profile} frames={self.args.frames} "
            f"timing={self.display.diag.timing_mode.name}. Space starts; Esc quits."
        )

    def _prepare_frame(self) -> None:
        assert self.renderer is not None
        if self.grid:
            assert self.grid_sequence is not None
            frame_index, matrix = self.grid_sequence.next_frame()
            if frame_index != self.frame_index % 256:
                raise RuntimeError("grid sequence index drift")
            self.renderer.prepare_logical_frame(
                matrix,
                payload_bbox=self.manifest["payload_bbox"],
                frame_index_bits=encode_frame_index_strip(frame_index),
                frame_index_bbox=self.manifest["frame_index_strip"]["bbox"],
            )
        else:
            self.renderer.prepare_qr_native_surface(self.qr_surfaces[self.frame_index])

    def run(self) -> None:
        self.prepare()
        assert self.renderer is not None
        running = True
        started = False
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
                ):
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    started = not started
                    self.last_advance = time.perf_counter()
                    print("RUNNING" if started else "PAUSED")

            if self.renderer.cached_frame_display is not None:
                self.display.present(self.renderer.cached_frame_display)

            if not started:
                continue

            advance = False
            if self.grid and self.display.diag.timing_mode == TimingMode.VSYNC_MODE:
                advance = self.display.dwell.record_present()
            else:
                fps = (
                    float(self.qr["target_fps"])
                    if self.qr
                    else self.display.diag.reported_refresh_hz / self.args.dwell
                )
                now = time.perf_counter()
                if now - self.last_advance >= 1.0 / fps:
                    self.last_advance += 1.0 / fps
                    advance = True

            if advance:
                self.frame_index += 1
                if self.frame_index >= self.args.frames:
                    print("COMPLETE")
                    break
                self._prepare_frame()
        self.display.close()


def main() -> None:
    args = build_parser().parse_args()
    if args.list:
        _list_profiles()
        return
    if not args.profile:
        raise SystemExit("--profile is required unless --list is used")
    if args.frames < 1 or args.frames > 256:
        raise SystemExit("--frames must be in [1, 256]")
    Phase1Runner(args).run()


if __name__ == "__main__":
    main()
