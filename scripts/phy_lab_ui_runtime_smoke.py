"""Exercise the real Tk -> campaign -> SDL path and report UI responsiveness.

This intentionally uses the native video driver. It is a workstation smoke test,
not a headless CI test. The optical window closes automatically on completion or
after ``--stop-after`` seconds.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import statistics
import time
import tkinter as tk

from superqr_desktop.app import ControlApp
from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v7_capacity_lab.phy_lab_ui import PhyLabWindow


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the Physical PHY Lab GUI runtime")
    parser.add_argument("--profile", default="mono_64x50_matched")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--marker-size", type=int, default=600)
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--stop-after", type=float)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-ui-gap-ms", type=float, default=200.0)
    parser.add_argument("--max-ui-p95-ms", type=float, default=40.0)
    parser.add_argument("--max-start-handler-ms", type=float, default=100.0)
    parser.add_argument("--max-stop-handler-ms", type=float, default=50.0)
    parser.add_argument(
        "--full-app", action="store_true",
        help="enter the lab through the real SuperQR application shell",
    )
    args = parser.parse_args()

    app: ControlApp | None = None
    if args.full_app:
        contract, contract_hash = load_contract()
        app = ControlApp(contract, contract_hash)
        root = app.root
        app.open_phy_lab()
        lab = app.phy_lab_window
        assert lab is not None
    else:
        root = tk.Tk()
        root.title("SuperQR PHY Lab runtime smoke controller")
        root.geometry("420x160")
        lab = PhyLabWindow(root)
    lab.preset_var.set("Selected profile")
    lab.profile_var.set(args.profile)
    lab.frames_var.set(args.frames)
    lab.marker_var.set(args.marker_size)
    lab.fullscreen_var.set(not args.windowed)
    lab._refresh_queue()

    started = time.perf_counter()
    heartbeat_times = [started]
    stop_handler_ms: float | None = None
    start_handler_ms: float | None = None
    stop_sent = False
    result: dict = {}

    def finish(reason: str) -> None:
        nonlocal result
        gaps = [(right - left) * 1000.0 for left, right in zip(heartbeat_times, heartbeat_times[1:])]
        snapshot = lab.worker.snapshot() if lab.worker is not None else None
        payload = None
        if lab.worker is not None:
            try:
                payload = lab.worker.export_payload()
            except RuntimeError:
                pass
        result = {
            "reason": reason,
            "state": snapshot.state.value if snapshot is not None else lab.state_var.get(),
            "ui_heartbeat_count": len(gaps),
            "ui_gap_mean_ms": statistics.fmean(gaps) if gaps else 0.0,
            "ui_gap_p95_ms": _percentile(gaps, 0.95),
            "ui_gap_max_ms": max(gaps) if gaps else 0.0,
            "stop_handler_ms": stop_handler_ms,
            "start_handler_ms": start_handler_ms,
            "present_fps": snapshot.present_fps if snapshot is not None else 0.0,
            "timing_mode": snapshot.timing_mode if snapshot is not None else "UNKNOWN",
            "vsync_verified": snapshot.vsync_verified if snapshot is not None else False,
            "present_interval_ms": snapshot.present_interval_ms if snapshot is not None else 0.0,
            "timing_note": snapshot.timing_note if snapshot is not None else "no snapshot",
            "presenter_process_id": payload.get("presenter_process_id") if payload else None,
            "ui_process_id": multiprocessing.current_process().pid,
        }
        if app is not None:
            app.close()
        else:
            lab.close()
            root.destroy()

    def heartbeat() -> None:
        nonlocal stop_handler_ms, stop_sent
        now = time.perf_counter()
        heartbeat_times.append(now)
        elapsed = now - started
        worker = lab.worker
        if args.stop_after is not None and elapsed >= args.stop_after and not stop_sent:
            before = time.perf_counter()
            lab.stop()
            stop_handler_ms = (time.perf_counter() - before) * 1000.0
            stop_sent = True
        if worker is not None and not worker.is_alive():
            snapshot = worker.snapshot()
            if snapshot is not None:
                finish("terminal_state")
                return
        if elapsed >= args.timeout:
            finish("timeout")
            return
        root.after(10, heartbeat)

    def start_campaign() -> None:
        nonlocal start_handler_ms
        before = time.perf_counter()
        lab.start()
        start_handler_ms = (time.perf_counter() - before) * 1000.0

    root.after(150, start_campaign)
    root.after(10, heartbeat)
    if app is not None:
        app.run()
    else:
        root.mainloop()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("reason") != "terminal_state":
        return 1
    if result.get("ui_gap_max_ms", float("inf")) > args.max_ui_gap_ms:
        return 2
    if result.get("presenter_process_id") == result.get("ui_process_id"):
        return 3
    if result.get("ui_gap_p95_ms", float("inf")) > args.max_ui_p95_ms:
        return 4
    if result.get("start_handler_ms", float("inf")) > args.max_start_handler_ms:
        return 5
    if (
        result.get("stop_handler_ms") is not None
        and result["stop_handler_ms"] > args.max_stop_handler_ms
    ):
        return 6
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
