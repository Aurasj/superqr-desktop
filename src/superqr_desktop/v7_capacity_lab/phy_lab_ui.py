"""Tk UI for complete terminal-free V7 physical PHY campaigns."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from superqr_desktop.v7_capacity_lab.analysis import analyze_jsonl, format_analysis
from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    build_campaign,
)
from superqr_desktop.v7_capacity_lab.lab_display import LabDisplayController
from superqr_desktop.v7_capacity_lab.phase1_profiles import grid_profiles, qr_controls


PRESETS = (
    "Selected profile",
    "All canonical profiles",
    "Monochrome density sweep",
    "Full grid dwell sweep",
)
MARKER_SIZES = (1000, 900, 800, 700, 600)


class PhyLabWindow:
    def __init__(self, parent: tk.Tk, on_close=None):
        self.parent = parent
        self.on_close = on_close
        self.presenter: Phase1CampaignPresenter | None = None
        detector = LabDisplayController()
        self.displays = detector.detect_displays()
        self.window = tk.Toplevel(parent)
        self.window.title("SuperQR • V7 Physical PHY Lab")
        self.window.geometry("720x780")
        self.window.minsize(660, 700)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        profiles = list(grid_profiles()) + list(qr_controls())
        labels = [display["label"] for display in self.displays]
        self.profile_var = tk.StringVar(value="mono_128x100_qrlike")
        self.preset_var = tk.StringVar(value="All canonical profiles")
        self.dwell_var = tk.IntVar(value=3)
        self.frames_var = tk.IntVar(value=256)
        self.display_var = tk.StringVar(value=labels[0] if labels else "Display 1")
        self.marker_var = tk.IntVar(value=800)
        self.fullscreen_var = tk.BooleanVar(value=True)
        self.state_var = tk.StringVar(value="READY TO CONFIGURE")
        self.run_var = tk.StringVar(value="No campaign active")
        self.metrics_var = tk.StringVar(value="Presentation metrics will appear here.")
        self.queue_var = tk.StringVar(value="")
        self.profiles = profiles
        self._build(labels)
        self._refresh_queue()
        self.window.after(16, self._tick)

    def _section(self, parent, title: str) -> ttk.Frame:
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill="x", pady=5)
        return frame

    def _build(self, display_labels: list[str]) -> None:
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="V7 Physical PHY Lab", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(root, text="Lab-only campaign sender • optical synchronization • reusable profiles").pack(anchor="w")

        config = self._section(root, "CAMPAIGN")
        row = ttk.Frame(config); row.pack(fill="x")
        ttk.Label(row, text="Preset", width=11).pack(side="left")
        combo = ttk.Combobox(row, textvariable=self.preset_var, values=PRESETS, state="readonly")
        combo.pack(side="left", fill="x", expand=True); combo.bind("<<ComboboxSelected>>", self._refresh_queue)
        row = ttk.Frame(config); row.pack(fill="x", pady=(7, 0))
        ttk.Label(row, text="Profile", width=11).pack(side="left")
        combo = ttk.Combobox(row, textvariable=self.profile_var, values=self.profiles, state="readonly")
        combo.pack(side="left", fill="x", expand=True); combo.bind("<<ComboboxSelected>>", self._refresh_queue)
        ttk.Label(row, text="Dwell").pack(side="left", padx=(8, 3))
        combo = ttk.Combobox(row, textvariable=self.dwell_var, values=(3, 2), state="readonly", width=4)
        combo.pack(side="left"); combo.bind("<<ComboboxSelected>>", self._refresh_queue)
        ttk.Label(row, text="Frames").pack(side="left", padx=(8, 3))
        spin = ttk.Spinbox(row, from_=1, to=256, textvariable=self.frames_var, width=5, command=self._refresh_queue)
        spin.pack(side="left")
        ttk.Label(config, textvariable=self.queue_var, wraplength=650).pack(anchor="w", pady=(7, 0))

        display = self._section(root, "DISPLAY")
        row = ttk.Frame(display); row.pack(fill="x")
        ttk.Label(row, text="Monitor", width=11).pack(side="left")
        ttk.Combobox(row, textvariable=self.display_var, values=display_labels, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Label(row, text="Marker").pack(side="left", padx=(8, 3))
        ttk.Combobox(row, textvariable=self.marker_var, values=MARKER_SIZES, state="readonly", width=6).pack(side="left")
        ttk.Checkbutton(row, text="Fullscreen", variable=self.fullscreen_var).pack(side="left", padx=(8, 0))

        control = self._section(root, "RUN CONTROL")
        row = ttk.Frame(control); row.pack(fill="x")
        self.start_button = ttk.Button(row, text="START CAMPAIGN", command=self.start)
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.stop_button = ttk.Button(row, text="STOP", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Label(control, textvariable=self.state_var, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(9, 0))
        ttk.Label(control, textvariable=self.run_var).pack(anchor="w", pady=(3, 0))
        self.progress = ttk.Progressbar(control, maximum=100.0)
        self.progress.pack(fill="x", pady=(7, 0))

        live = self._section(root, "LIVE PRESENTATION")
        ttk.Label(live, textvariable=self.metrics_var, justify="left").pack(anchor="w")

        results = self._section(root, "RESULTS")
        row = ttk.Frame(results); row.pack(fill="x")
        ttk.Button(row, text="Analyze receiver JSONL…", command=self.analyze).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Export sender metrics…", command=self.export).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.analysis_text = tk.Text(results, height=6, wrap="word")
        self.analysis_text.pack(fill="both", expand=True, pady=(8, 0))
        self.analysis_text.insert("1.0", "Import an Android PHY Lab JSONL export for an immediate summary.")
        self.analysis_text.configure(state="disabled")

    def _runs(self):
        frames = max(1, min(256, int(self.frames_var.get())))
        return build_campaign(self.preset_var.get(), self.profile_var.get(), int(self.dwell_var.get()), frames)

    def _refresh_queue(self, _event=None) -> None:
        try:
            runs = self._runs()
            preview = " → ".join(f"{run.profile} (d{run.dwell_epochs})" for run in runs[:4])
            if len(runs) > 4:
                preview += f" → … ({len(runs)} runs)"
            self.queue_var.set(preview)
        except Exception as exc:
            self.queue_var.set(str(exc))

    def _display_index(self) -> int:
        found = next((item for item in self.displays if item["label"] == self.display_var.get()), None)
        return int(found["index"]) if found else 0

    def start(self) -> None:
        if self.presenter is not None:
            self.presenter.stop()
        try:
            self.state_var.set("PREPARING • QR controls may take a moment")
            self.window.update_idletasks()
            self.presenter = Phase1CampaignPresenter(
                self._runs(), display_index=self._display_index(),
                fullscreen=self.fullscreen_var.get(), marker_size=int(self.marker_var.get()),
            )
            self.presenter.start()
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        except Exception as exc:
            self.state_var.set(f"ERROR • {type(exc).__name__}: {exc}")
            self.presenter = None
            messagebox.showerror("PHY Lab", str(exc), parent=self.window)

    def stop(self) -> None:
        if self.presenter is not None:
            self.presenter.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.state_var.set("STOPPED")

    def _tick(self) -> None:
        if not self.window.winfo_exists():
            return
        presenter = self.presenter
        if presenter is not None and presenter.state not in (CampaignState.STOPPED, CampaignState.ERROR):
            presenter.tick()
            snapshot = presenter.snapshot()
            token = f"{snapshot.run_token:04X}"
            state = snapshot.state.value
            if snapshot.state == CampaignState.READY:
                state += f" • starts in {snapshot.ready_remaining_s:.1f}s"
            self.state_var.set(state)
            self.run_var.set(
                f"Run {snapshot.run_number}/{snapshot.run_total} • token {token} • "
                f"{snapshot.profile} • dwell {snapshot.dwell_epochs}"
            )
            progress = 100.0 * snapshot.frame_index / max(1, snapshot.frame_count - 1)
            if snapshot.state == CampaignState.DONE:
                progress = 100.0
            self.progress["value"] = progress
            self.metrics_var.set(
                f"Frame {snapshot.frame_index + 1}/{snapshot.frame_count} • logical {snapshot.logical_fps:.2f} fps\n"
                f"Presents {snapshot.present_count} • display {snapshot.present_fps:.2f} fps • late {snapshot.late_presents}\n"
                f"Prepare {snapshot.render_prepare_ms:.2f} ms • timing {snapshot.timing_mode}"
            )
            if snapshot.state == CampaignState.ERROR:
                self.stop_button.configure(state="disabled")
                self.start_button.configure(state="normal")
        self.window.after(16, self._tick)

    def analyze(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, title="Analyze Android PHY Lab export",
            filetypes=(("JSON Lines", "*.jsonl"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            text = format_analysis(analyze_jsonl(path))
            self.analysis_text.configure(state="normal")
            self.analysis_text.delete("1.0", "end")
            self.analysis_text.insert("1.0", text)
            self.analysis_text.configure(state="disabled")
        except Exception as exc:
            messagebox.showerror("PHY Lab analysis", str(exc), parent=self.window)

    def export(self) -> None:
        if self.presenter is None:
            messagebox.showinfo("PHY Lab", "Start a campaign before exporting sender metrics.", parent=self.window)
            return
        path = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".json",
            filetypes=(("JSON", "*.json"),), initialfile="superqr-phy-lab-sender.json",
        )
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.presenter.snapshot().__dict__, handle, indent=2, default=str)

    def close(self) -> None:
        if self.presenter is not None:
            self.presenter.stop()
        self.window.destroy()
        if self.on_close is not None:
            self.on_close()


def open_phy_lab(parent: tk.Tk, on_close=None) -> PhyLabWindow:
    return PhyLabWindow(parent, on_close=on_close)
