"""Standalone UI and CLI for the Desktop-camera Phase 1 receiver."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from superqr_desktop.v7_capacity_lab.camera_receiver import (
    CameraConfig,
    CameraReceiverWorker,
    probe_cameras,
    run_headless,
)


CAPTURE_MODES = ("640×480 @ 30", "320×240 @ 30", "1280×720 @ 30")


def _parse_mode(value: str) -> tuple[int, int, float]:
    dimensions, fps = value.split(" @ ")
    width, height = dimensions.split("×")
    return int(width), int(height), float(fps)


class CameraReceiverWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.worker: CameraReceiverWorker | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._last_preview_at = 0
        self._probe_thread: threading.Thread | None = None
        self._probe_results: queue.Queue = queue.Queue(maxsize=1)
        root.title("SuperQR • PC Camera PHY Receiver")
        root.geometry("1120x790")
        root.minsize(920, 680)
        root.configure(bg="#080b11")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._styles()

        self.camera_var = tk.StringVar(value="Camera 0")
        self.mode_var = tk.StringVar(value=CAPTURE_MODES[0])
        self.state_var = tk.StringVar(value="CAMERA STOPPED")
        self.detail_var = tk.StringVar(value="Start the camera, then show the complete sender marker.")
        self.run_var = tk.StringVar(value="UNSYNCED")
        self.frame_var = tk.StringVar(value="—")
        self.capture_var = tk.StringVar(value="—")
        self.analysis_var = tk.StringVar(value="—")
        self.geometry_var = tk.StringVar(value="NONE")
        self.finders_var = tk.StringVar(value="0 / 4")
        self.scored_var = tk.StringVar(value="0 / 0")
        self.unique_var = tk.StringVar(value="0")
        self.ber_var = tk.StringVar(value="0.000%")
        self.erasure_var = tk.StringVar(value="0.000%")
        self.yield_var = tk.StringVar(value="0.0%")
        self.pipeline_var = tk.StringVar(value="—")
        self.failure_var = tk.StringVar(value="No observations yet.")
        self._build()
        root.after(100, self._tick)
        root.after(50, self._probe)

    def _styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Receiver.TCombobox", fieldbackground="#1a2230", foreground="#edf2ff")
        style.map("Receiver.TCombobox", fieldbackground=[("readonly", "#1a2230")], foreground=[("readonly", "#edf2ff")])

    def _build(self) -> None:
        shell = ttk.Frame(self.root, padding=16)
        shell.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        shell.columnconfigure(0, weight=3)
        shell.columnconfigure(1, weight=2)
        shell.rowconfigure(2, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="PC Camera PHY Receiver", font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Phase 1 diagnostic receiver • exact analyzed camera frame", foreground="#99a4bd").grid(row=1, column=0, sticky="w")
        self.state_label = ttk.Label(header, textvariable=self.state_var, font=("Segoe UI", 15, "bold"), foreground="#f2cc60")
        self.state_label.grid(row=0, column=1, rowspan=2, sticky="e")

        controls = ttk.LabelFrame(shell, text=" Camera setup ", padding=10)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Device").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.camera_box = ttk.Combobox(controls, textvariable=self.camera_var, values=("Camera 0",), state="readonly", style="Receiver.TCombobox")
        self.camera_box.grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Refresh", command=self._probe).grid(row=0, column=2, padx=8)
        ttk.Label(controls, text="Capture mode").grid(row=0, column=3, padx=(12, 8))
        ttk.Combobox(controls, textvariable=self.mode_var, values=CAPTURE_MODES, state="readonly", width=18, style="Receiver.TCombobox").grid(row=0, column=4)
        self.start_button = ttk.Button(controls, text="START CAMERA", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=5, padx=(12, 6), ipady=3)
        self.stop_button = ttk.Button(controls, text="STOP", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=6, ipady=3)

        preview_frame = ttk.LabelFrame(shell, text=" Exact analyzed frame • full frame • no crop ", padding=8)
        preview_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview = tk.Label(preview_frame, bg="#05070a", fg="#8f9bad", text="Camera preview appears here", font=("Segoe UI", 14))
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(preview_frame, textvariable=self.detail_var, foreground="#99a4bd", wraplength=670).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        dashboard = ttk.Frame(shell)
        dashboard.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        dashboard.columnconfigure(0, weight=1)
        dashboard.columnconfigure(1, weight=1)
        dashboard.rowconfigure(5, weight=1)

        hero = ttk.LabelFrame(dashboard, text=" Optical lock ", padding=12)
        hero.grid(row=0, column=0, columnspan=2, sticky="ew")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, textvariable=self.run_var, font=("Segoe UI", 16, "bold"), foreground="#67c7ff").grid(row=0, column=0, sticky="w")
        ttk.Label(hero, textvariable=self.frame_var, foreground="#edf2ff").grid(row=1, column=0, sticky="w", pady=(4, 0))

        definitions = (
            ("CAPTURE FPS", self.capture_var), ("ANALYSIS FPS", self.analysis_var),
            ("GEOMETRY", self.geometry_var), ("FINDERS", self.finders_var),
            ("ANALYZED / SCORED", self.scored_var), ("UNIQUE FRAMES", self.unique_var),
            ("BER", self.ber_var), ("ERASURES", self.erasure_var),
            ("RAW VALID YIELD", self.yield_var), ("PIPELINE MEAN / P95", self.pipeline_var),
        )
        for index, (name, variable) in enumerate(definitions):
            tile = ttk.LabelFrame(dashboard, text=f" {name} ", padding=9)
            tile.grid(row=1 + index // 2, column=index % 2, sticky="nsew", padx=(0 if index % 2 == 0 else 4, 4 if index % 2 == 0 else 0), pady=(8, 0))
            ttk.Label(tile, textvariable=variable, font=("Segoe UI", 12, "bold"), foreground="#edf2ff").pack(anchor="w")

        failures = ttk.LabelFrame(dashboard, text=" Latest diagnostic ", padding=10)
        failures.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        ttk.Label(failures, textvariable=self.failure_var, justify="left", wraplength=400, foreground="#f2cc60").pack(anchor="nw")

        actions = ttk.Frame(shell)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="EXPORT RECEIVER JSONL…", command=self.export).pack(side="left")
        ttk.Button(actions, text="SAVE DIAGNOSTIC FRAME…", command=self.save_frame).pack(side="left", padx=(8, 0))
        ttk.Label(actions, text="Keep the complete marker visible. Start the sender only after the camera reports live capture.", foreground="#99a4bd").pack(side="right")

    def _probe(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self._probe_thread and self._probe_thread.is_alive():
            return
        self.state_var.set("PROBING CAMERAS")
        self._probe_thread = threading.Thread(target=self._probe_worker, name="superqr-camera-probe", daemon=True)
        self._probe_thread.start()

    def _probe_worker(self) -> None:
        try:
            probes = probe_cameras()
            self._probe_results.put((probes, None))
        except Exception as exc:
            self._probe_results.put(([], str(exc)))

    def _apply_probe_result(self) -> None:
        try:
            probes, error = self._probe_results.get_nowait()
        except queue.Empty:
            return
        if error:
            self.state_var.set("CAMERA ERROR")
            self.detail_var.set(error)
            return
        values = tuple(
            f"Camera {probe.index} • {probe.name} • {probe.backend} • {probe.width}×{probe.height}"
            for probe in probes
        )
        if values:
            self.camera_box.configure(values=values)
            self.camera_var.set(values[0])
            self.state_var.set("CAMERA READY")
            self.detail_var.set("Camera detected. Start it to see the exact analyzed frame.")
        else:
            self.state_var.set("NO CAMERA")
            self.detail_var.set("No usable camera endpoint was found.")

    def _camera_index(self) -> int:
        parts = self.camera_var.get().split()
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        width, height, fps = _parse_mode(self.mode_var.get())
        self.worker = CameraReceiverWorker(CameraConfig(self._camera_index(), width, height, fps, "AUTO"))
        self.worker.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.state_var.set("STARTING CAMERA")
        self.state_label.configure(foreground="#67c7ff")

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.state_var.set("CAMERA STOPPED")
        self.state_label.configure(foreground="#f2cc60")

    def _tick(self) -> None:
        self._apply_probe_result()
        worker = self.worker
        if worker:
            snapshot = worker.snapshot()
            if snapshot:
                self._update_snapshot(snapshot)
            preview = worker.preview()
            if preview is not None:
                self._show_preview(preview)
            if not worker.is_alive() and snapshot and snapshot.state == "ERROR":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
        self.root.after(100, self._tick)

    def _show_preview(self, bgr) -> None:
        available_w = max(320, self.preview.winfo_width())
        available_h = max(240, self.preview.winfo_height())
        height, width = bgr.shape[:2]
        scale = min(available_w / width, available_h / height)
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        rgb = cv2.cvtColor(cv2.resize(bgr, target, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.preview.configure(image=self._photo, text="")

    def _update_snapshot(self, snapshot) -> None:
        if snapshot.error:
            self.state_var.set("CAMERA ERROR")
            self.state_label.configure(foreground="#ff7070")
            self.detail_var.set(snapshot.error)
            return
        locked = snapshot.run_token is not None
        self.state_var.set("OPTICAL LOCK" if locked else "SEARCHING")
        self.state_label.configure(foreground="#7ee787" if locked else "#f2cc60")
        self.run_var.set(
            f"TOKEN {snapshot.run_token:04X} • {snapshot.profile}" if locked else "RUN UNSYNCED"
        )
        self.frame_var.set(
            f"{snapshot.run_state} • frame {snapshot.frame_index + 1 if snapshot.frame_index is not None else '—'} / {snapshot.frame_count or '—'}"
        )
        self.capture_var.set(f"{snapshot.capture_fps:.1f} • {snapshot.capture_width}×{snapshot.capture_height}")
        self.analysis_var.set(f"{snapshot.analysis_fps:.1f}")
        self.geometry_var.set(snapshot.geometry_state)
        self.finders_var.set(f"{snapshot.finder_count} / 4 • {snapshot.candidate_count} candidates")
        self.scored_var.set(f"{snapshot.analyzed_frames} / {snapshot.scored_frames}")
        self.unique_var.set(f"{snapshot.unique_frames} / {snapshot.frame_count or '—'}")
        self.ber_var.set(f"{snapshot.ber:.3%}")
        self.erasure_var.set(f"{snapshot.erasure_rate:.3%}")
        self.yield_var.set(f"{snapshot.raw_valid_yield:.1%}")
        self.pipeline_var.set(f"{snapshot.pipeline_mean_ms:.1f} / {snapshot.pipeline_p95_ms:.1f} ms")
        counts = ", ".join(f"{name}={count}" for name, count in snapshot.failure_counts.items())
        self.failure_var.set(f"{snapshot.failure_reason}\n{counts or 'No failures recorded.'}")
        self.detail_var.set(
            f"Analyzing the negotiated {snapshot.capture_width}×{snapshot.capture_height} DirectShow frame. "
            "The preview and overlay use these same pixels with no crop."
        )

    def export(self) -> None:
        if not self.worker or not self.worker.records():
            messagebox.showinfo("PC Camera Receiver", "No receiver observations are available yet.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".jsonl",
            filetypes=(("JSON Lines", "*.jsonl"),), initialfile="superqr-pc-camera-receiver.jsonl",
        )
        if path:
            try:
                self.worker.export(path)
            except Exception as exc:
                messagebox.showerror("PC Camera Receiver", str(exc), parent=self.root)

    def save_frame(self) -> None:
        frame = self.worker.preview() if self.worker else None
        if frame is None:
            messagebox.showinfo("PC Camera Receiver", "No analyzed camera frame is available yet.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".png",
            filetypes=(("PNG image", "*.png"),), initialfile="superqr-pc-camera-diagnostic.png",
        )
        if path and not cv2.imwrite(path, frame):
            messagebox.showerror("PC Camera Receiver", "The diagnostic image could not be saved.", parent=self.root)

    def close(self) -> None:
        if self.worker:
            self.worker.stop()
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SuperQR Phase 1 PC-camera receiver")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--backend", choices=("AUTO", "DSHOW", "MSMF"), default="AUTO")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--output", default="superqr-pc-camera-receiver.jsonl")
    parser.add_argument("--snapshot", help="save the final annotated analyzed frame as PNG")
    parser.add_argument("--probe", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.probe:
        print(json.dumps([asdict(probe) for probe in probe_cameras()], indent=2))
        return
    config = CameraConfig(args.camera, args.width, args.height, args.fps, args.backend)
    if args.headless:
        snapshot = run_headless(config, args.output, args.duration, args.snapshot)
        print(json.dumps(asdict(snapshot), indent=2))
        if snapshot.error:
            raise SystemExit(1)
        return
    root = tk.Tk()
    CameraReceiverWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
