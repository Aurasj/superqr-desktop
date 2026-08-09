"""CLI wrapper around the reusable V7 physical PHY campaign presenter."""

from __future__ import annotations

import argparse
import json
import time

import pygame

from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    build_campaign,
)
from superqr_desktop.v7_capacity_lab.phase1_profiles import grid_profiles, qr_controls


def build_parser() -> argparse.ArgumentParser:
    profiles = list(grid_profiles()) + list(qr_controls())
    parser = argparse.ArgumentParser(description="SuperQR V7 physical PHY lab transmitter")
    parser.add_argument("--profile", choices=profiles)
    parser.add_argument("--list", action="store_true", help="list canonical profiles")
    parser.add_argument(
        "--campaign",
        choices=("selected", "all", "mono", "grid-dwell"),
        default="selected",
    )
    parser.add_argument("--dwell", type=int, choices=[2, 3], default=3)
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--marker-size", type=int, default=800)
    parser.add_argument("--display", type=int, default=0)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--ready-seconds", type=float, default=4.0)
    parser.add_argument("--done-seconds", type=float, default=2.0)
    parser.add_argument("--run-token", type=lambda value: int(value, 0))
    parser.add_argument("--json-status", action="store_true")
    return parser


def _list_profiles() -> None:
    for profile in grid_profiles().values():
        print(f"{profile['name']}: {profile['cols']}x{profile['rows']} {profile['raw_bytes_per_frame']} B/frame")
    for control in qr_controls().values():
        print(f"{control['name']}: QR V{control['version']}-{control['error_correction']} {control['frame_bytes']} B")


class Phase1Runner:
    PRESET_NAMES = {
        "selected": "Selected profile",
        "all": "All canonical profiles",
        "mono": "Monochrome density sweep",
        "grid-dwell": "Full grid dwell sweep",
    }

    def __init__(self, args: argparse.Namespace):
        self.args = args

    def run(self) -> None:
        profile = self.args.profile or "mono_128x100_qrlike"
        runs = build_campaign(
            self.PRESET_NAMES[self.args.campaign], profile, self.args.dwell, self.args.frames,
        )
        presenter = Phase1CampaignPresenter(
            runs, display_index=self.args.display, fullscreen=self.args.fullscreen,
            marker_size=self.args.marker_size, ready_seconds=self.args.ready_seconds,
            done_seconds=self.args.done_seconds, first_run_token=self.args.run_token,
        )
        clock = pygame.time.Clock()
        previous = None
        try:
            presenter.start()
            while True:
                if not presenter.tick():
                    break
                snapshot = presenter.snapshot()
                key = (snapshot.state, snapshot.run_number, snapshot.frame_index)
                if key != previous and (
                    snapshot.state != CampaignState.RUNNING or snapshot.frame_index % 10 == 0
                ):
                    if self.args.json_status:
                        print(json.dumps(snapshot.__dict__, default=str), flush=True)
                    else:
                        print(
                            f"{snapshot.state.value} run={snapshot.run_number}/{snapshot.run_total} "
                            f"token={snapshot.run_token:04X} profile={snapshot.profile} "
                            f"frame={snapshot.frame_index + 1}/{snapshot.frame_count}",
                            flush=True,
                        )
                    previous = key
                if (
                    snapshot.state == CampaignState.DONE
                    and snapshot.run_number == snapshot.run_total
                    and time.perf_counter() - presenter.state_started >= self.args.done_seconds
                ):
                    break
                clock.tick(240)
            if presenter.state == CampaignState.ERROR:
                raise RuntimeError(presenter.error or "presentation failed")
        finally:
            presenter.stop()


def main() -> None:
    args = build_parser().parse_args()
    if args.list:
        _list_profiles()
        return
    if args.campaign == "selected" and not args.profile:
        raise SystemExit("--profile is required for the selected campaign")
    if args.frames < 1 or args.frames > 256:
        raise SystemExit("--frames must be in [1, 256]")
    if args.ready_seconds < 0 or args.done_seconds < 0:
        raise SystemExit("ready/done seconds must be non-negative")
    Phase1Runner(args).run()


if __name__ == "__main__":
    main()
