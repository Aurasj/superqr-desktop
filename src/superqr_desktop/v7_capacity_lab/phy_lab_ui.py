"""Professional Tk dashboard for terminal-free V7 physical PHY campaigns."""

from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from superqr_desktop.v7_capacity_lab.analysis import analyze_jsonl, format_analysis
from superqr_desktop.v7_capacity_lab.campaign import (
    CampaignState,
    Phase1CampaignPresenter,
    Phase1CampaignWorker,
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
MARKER_SIZES = (600, 700, 800, 900, 1000)


class PhyLabWindow:
    """A resizable two-pane campaign console and live presentation dashboard."""

    def __init__(self, parent: tk.Tk, on_close=None):
        self.parent = parent
        self.on_close = on_close
        self.worker: Phase1CampaignWorker | None = None
        self._stop_pending = False
        detector = LabDisplayController()
        self.displays = detector.detect_displays()
        self.profiles = list(grid_profiles()) + list(qr_controls())

        self.window = tk.Toplevel(parent)
        self.window.title("SuperQR • Physical PHY Lab")
        self.window.geometry("1080x760")
        self.window.minsize(900, 650)
        self.window.configure(bg="#080b11")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_styles()

        labels = [display["label"] for display in self.displays]
        self.profile_var = tk.StringVar(value="mono_128x100_qrlike")
        self.preset_var = tk.StringVar(value="All canonical profiles")
        self.dwell_var = tk.IntVar(value=3)
        self.frames_var = tk.IntVar(value=256)
        self.display_var = tk.StringVar(value=labels[0] if labels else "Display 1")
        self.marker_var = tk.IntVar(value=600)
        self.fullscreen_var = tk.BooleanVar(value=True)
        self.state_var = tk.StringVar(value="READY")
        self.state_detail_var = tk.StringVar(value="Configure a campaign, then start presentation.")
        self.run_identity_var = tk.StringVar(value="No synchronized run")
        self.progress_text_var = tk.StringVar(value="0 / 0 frames")
        self.queue_summary_var = tk.StringVar(value="")
        self.diagnostics_var = tk.StringVar(value="No presentation is active.")
        self.metric_vars = {
            key: tk.StringVar(value="—")
            for key in ("frame", "logical_fps", "display_fps", "late", "prepare", "timing")
        }
        self._build(labels)
        self._refresh_queue()
        self._center_over_parent()
        self.window.after(16, self._tick)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.window)
        style.configure(
            "Lab.Treeview", background="#121823", fieldbackground="#121823",
            foreground="#dce7f7", rowheight=27, borderwidth=0,
        )
        style.map(
            "Lab.Treeview",
            background=[("selected", "#245b8f")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Lab.Treeview.Heading", background="#1a2230", foreground="#edf2ff",
            relief="flat", font=("Segoe UI", 9, "bold"),
        )
        style.map("Lab.Treeview.Heading", background=[("active", "#263247")])
        style.configure("Lab.TNotebook", background="#111722", borderwidth=0)
        style.configure(
            "Lab.TNotebook.Tab", background="#1a2230", foreground="#b7c4d7",
            padding=(12, 7), font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Lab.TNotebook.Tab",
            background=[("selected", "#245b8f"), ("active", "#263247")],
            foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
        )
        style.configure(
            "Lab.TCombobox", fieldbackground="#1a2230", background="#1a2230",
            foreground="#edf2ff", arrowcolor="#edf2ff",
        )
        style.map(
            "Lab.TCombobox", fieldbackground=[("readonly", "#1a2230")],
            foreground=[("readonly", "#edf2ff")], selectbackground=[("readonly", "#1a2230")],
            selectforeground=[("readonly", "#edf2ff")],
        )

    def _center_over_parent(self) -> None:
        self.window.update_idletasks()
        try:
            x = self.parent.winfo_rootx() + max(20, (self.parent.winfo_width() - 1080) // 2)
            y = self.parent.winfo_rooty() + 20
            self.window.geometry(f"1080x760+{x}+{y}")
        except tk.TclError:
            pass

    def _build(self, display_labels: list[str]) -> None:
        shell = ttk.Frame(self.window, padding=16)
        shell.grid(row=0, column=0, sticky="nsew")
        self.window.rowconfigure(0, weight=1)
        self.window.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        shell.columnconfigure(0, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Physical PHY Lab", font=("Segoe UI", 21, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="V7 optical benchmark • lab-only • production PHY remains unfrozen", foreground="#99a4bd").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(header, text="CAMPAIGN CONSOLE", foreground="#67c7ff", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, rowspan=2, sticky="e")

        panes = ttk.Panedwindow(shell, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        panes.add(left, weight=2)
        panes.add(right, weight=3)
        self._build_configuration(left, display_labels)
        self._build_dashboard(right)

    def _build_configuration(self, parent: ttk.Frame, display_labels: list[str]) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        setup = ttk.LabelFrame(parent, text=" Campaign setup ", padding=12)
        setup.grid(row=0, column=0, sticky="ew")
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Preset").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        preset = ttk.Combobox(setup, textvariable=self.preset_var, values=PRESETS, state="readonly", style="Lab.TCombobox")
        preset.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        preset.bind("<<ComboboxSelected>>", self._refresh_queue)
        ttk.Label(setup, text="Profile").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        profile = ttk.Combobox(setup, textvariable=self.profile_var, values=self.profiles, state="readonly", style="Lab.TCombobox")
        profile.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        profile.bind("<<ComboboxSelected>>", self._refresh_queue)
        ttk.Label(setup, text="Dwell").grid(row=2, column=0, sticky="w", pady=4)
        dwell = ttk.Combobox(setup, textvariable=self.dwell_var, values=(3, 2), state="readonly", width=5, style="Lab.TCombobox")
        dwell.grid(row=2, column=1, sticky="w", pady=4)
        dwell.bind("<<ComboboxSelected>>", self._refresh_queue)
        ttk.Label(setup, text="Frames").grid(row=2, column=2, sticky="e", padx=(16, 8), pady=4)
        frames = ttk.Spinbox(setup, from_=1, to=256, textvariable=self.frames_var, width=7, command=self._refresh_queue)
        frames.grid(row=2, column=3, sticky="e", pady=4)
        frames.bind("<FocusOut>", self._refresh_queue)
        frames.bind("<Return>", self._refresh_queue)

        queue_frame = ttk.LabelFrame(parent, text=" Campaign queue ", padding=10)
        queue_frame.grid(row=1, column=0, sticky="nsew", pady=10)
        queue_frame.rowconfigure(0, weight=1)
        queue_frame.columnconfigure(0, weight=1)
        self.queue = ttk.Treeview(queue_frame, columns=("profile", "dwell", "frames"), show="headings", height=8, style="Lab.Treeview")
        self.queue.heading("profile", text="Profile")
        self.queue.heading("dwell", text="Dwell")
        self.queue.heading("frames", text="Frames")
        self.queue.column("profile", width=215, minwidth=150, stretch=True)
        self.queue.column("dwell", width=55, minwidth=48, anchor="center", stretch=False)
        self.queue.column("frames", width=60, minwidth=55, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.queue.yview)
        self.queue.configure(yscrollcommand=scroll.set)
        self.queue.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        ttk.Label(queue_frame, textvariable=self.queue_summary_var, foreground="#99a4bd").grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))

        display = ttk.LabelFrame(parent, text=" Optical display ", padding=12)
        display.grid(row=2, column=0, sticky="ew")
        display.columnconfigure(1, weight=1)
        ttk.Label(display, text="Monitor").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(display, textvariable=self.display_var, values=display_labels, state="readonly", style="Lab.TCombobox").grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(display, text="Marker (600 recommended)").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(display, textvariable=self.marker_var, values=MARKER_SIZES, state="readonly", width=8, style="Lab.TCombobox").grid(row=1, column=1, sticky="w", pady=4)
        ttk.Checkbutton(display, text="Fullscreen presentation", variable=self.fullscreen_var).grid(row=1, column=2, columnspan=2, sticky="e", pady=4)

        controls = ttk.Frame(parent)
        controls.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(controls, text="START CAMPAIGN", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipady=5)
        self.stop_button = ttk.Button(controls, text="STOP", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(5, 0), ipady=5)

    def _build_dashboard(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        hero = ttk.LabelFrame(parent, text=" Live run ", padding=14)
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)
        self.state_label = ttk.Label(hero, textvariable=self.state_var, font=("Segoe UI", 22, "bold"), foreground="#7ee787")
        self.state_label.grid(row=0, column=0, sticky="w")
        ttk.Label(hero, textvariable=self.run_identity_var, foreground="#67c7ff", font=("Segoe UI", 11, "bold")).grid(row=0, column=1, sticky="e")
        ttk.Label(hero, textvariable=self.state_detail_var, foreground="#99a4bd").grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 9))
        progress_row = ttk.Frame(hero)
        progress_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_row, maximum=100.0)
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_row, textvariable=self.progress_text_var, width=18, anchor="e").grid(row=0, column=1, padx=(10, 0))

        metrics = ttk.Frame(parent)
        metrics.grid(row=1, column=0, sticky="ew", pady=10)
        for column in range(3):
            metrics.columnconfigure(column, weight=1, uniform="metrics")
        definitions = (
            ("frame", "FRAME"), ("logical_fps", "LOGICAL FPS"), ("display_fps", "DISPLAY FPS"),
            ("late", "LATE PRESENTS"), ("prepare", "PREPARE"), ("timing", "TIMING MODE"),
        )
        for index, (key, label) in enumerate(definitions):
            tile = ttk.LabelFrame(metrics, text=f" {label} ", padding=10)
            tile.grid(row=index // 3, column=index % 3, sticky="nsew", padx=(0 if index % 3 == 0 else 5, 0 if index % 3 == 2 else 5), pady=(0 if index < 3 else 5, 0))
            ttk.Label(tile, textvariable=self.metric_vars[key], font=("Segoe UI", 15, "bold"), foreground="#edf2ff").pack(anchor="w")

        ttk.Label(parent, textvariable=self.diagnostics_var, foreground="#99a4bd", justify="left").grid(row=2, column=0, sticky="ew", pady=(0, 10))

        notebook = ttk.Notebook(parent, style="Lab.TNotebook")
        notebook.grid(row=3, column=0, sticky="nsew")
        analysis_tab = ttk.Frame(notebook, padding=10)
        help_tab = ttk.Frame(notebook, padding=12)
        notebook.add(analysis_tab, text="Receiver analysis")
        notebook.add(help_tab, text="Test guide")
        analysis_tab.rowconfigure(1, weight=1)
        analysis_tab.columnconfigure(0, weight=1)
        actions = ttk.Frame(analysis_tab)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="Open PC camera receiver", command=self.open_camera_receiver).pack(side="left")
        ttk.Button(actions, text="Analyze Android JSONL…", command=self.analyze).pack(side="left")
        ttk.Button(actions, text="Export sender metrics…", command=self.export).pack(side="left", padx=(8, 0))
        self.analysis_text = tk.Text(
            analysis_tab, height=7, wrap="word", relief="flat",
            bg="#101620", fg="#dce7f7", insertbackground="white",
            padx=12, pady=10, font=("Consolas", 10),
        )
        self.analysis_text.grid(row=1, column=0, sticky="nsew")
        self.analysis_text.insert("1.0", "Import the Android campaign JSONL here after the run. The summary separates rejected acquisition attempts from scored PHY frames.")
        self.analysis_text.configure(state="disabled")
        guide = (
            "1. Start the Android camera and wait for ANALYZING.\n"
            "2. Start this campaign and confirm the four-digit run token matches.\n"
            "3. Keep the phone and display stationary through final DONE.\n"
            "4. Share one Android campaign JSONL, then analyze it here.\n\n"
            "READY and DONE are guard states. Only synchronized RUNNING frames are scored."
        )
        ttk.Label(help_tab, text=guide, justify="left", wraplength=540).pack(anchor="nw")

    def _runs(self):
        frames = max(1, min(256, int(self.frames_var.get())))
        return build_campaign(self.preset_var.get(), self.profile_var.get(), int(self.dwell_var.get()), frames)

    def _refresh_queue(self, _event=None) -> None:
        try:
            runs = self._runs()
            self.queue.delete(*self.queue.get_children())
            for run in runs:
                self.queue.insert("", "end", values=(run.profile, run.dwell_epochs, run.frame_count))
            total_frames = sum(run.frame_count for run in runs)
            self.queue_summary_var.set(f"{len(runs)} run{'s' if len(runs) != 1 else ''} • {total_frames:,} logical frames")
        except Exception as exc:
            self.queue_summary_var.set(str(exc))

    def _display_index(self) -> int:
        found = next((item for item in self.displays if item["label"] == self.display_var.get()), None)
        return int(found["index"]) if found else 0

    def start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        if self.worker is not None:
            self.worker.stop(timeout=0.0)
        try:
            self._set_state("PREPARING", "Building the selected control frames. QR controls can take a moment.")
            self.window.update_idletasks()
            presenter = Phase1CampaignPresenter(
                self._runs(), display_index=self._display_index(),
                fullscreen=self.fullscreen_var.get(), marker_size=int(self.marker_var.get()),
            )
            self.worker = Phase1CampaignWorker(presenter)
            self.worker.start()
            self._stop_pending = False
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        except Exception as exc:
            self._set_state("ERROR", f"{type(exc).__name__}: {exc}")
            self.worker = None
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            messagebox.showerror("Physical PHY Lab", str(exc), parent=self.window)

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self._stop_pending = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self._set_state("STOPPING", "Closing the optical window and saving final presentation metrics…")

    def _set_state(self, state: str, detail: str) -> None:
        colors = {
            "READY": "#f2cc60", "RUNNING": "#7ee787", "DONE": "#67c7ff",
            "PREPARING": "#67c7ff", "STOPPING": "#f2cc60",
            "ERROR": "#ff7070", "STOPPED": "#99a4bd",
        }
        self.state_var.set(state)
        self.state_detail_var.set(detail)
        self.state_label.configure(foreground=colors.get(state, "#edf2ff"))

    def _tick(self) -> None:
        if not self.window.winfo_exists():
            return
        worker = self.worker
        snapshot = worker.snapshot() if worker is not None else None
        if worker is not None and snapshot is not None:
            state = snapshot.state.value
            detail = f"{snapshot.profile} • dwell {snapshot.dwell_epochs} • run {snapshot.run_number} of {snapshot.run_total}"
            if snapshot.state == CampaignState.READY:
                detail += f" • starts in {snapshot.ready_remaining_s:.1f} seconds"
            elif snapshot.state == CampaignState.ERROR:
                detail = snapshot.error or "Presentation process failed."
            elif snapshot.state == CampaignState.STOPPED:
                detail = "Presentation stopped. Configure or restart the campaign when ready."
            self._set_state(state, detail)
            self.run_identity_var.set(f"TOKEN {snapshot.run_token:04X}")
            complete = snapshot.frame_index + 1 if snapshot.state != CampaignState.DONE else snapshot.frame_count
            self.progress_text_var.set(f"{complete:,} / {snapshot.frame_count:,} frames")
            self.progress["value"] = 100.0 if snapshot.state == CampaignState.DONE else 100.0 * snapshot.frame_index / max(1, snapshot.frame_count - 1)
            self.metric_vars["frame"].set(f"{snapshot.frame_index + 1} / {snapshot.frame_count}")
            self.metric_vars["logical_fps"].set(f"{snapshot.logical_fps:.2f}")
            self.metric_vars["display_fps"].set(f"{snapshot.present_fps:.2f}")
            self.metric_vars["late"].set(str(snapshot.late_presents))
            self.metric_vars["prepare"].set(f"{snapshot.render_prepare_ms:.2f} ms")
            self.metric_vars["timing"].set(snapshot.timing_mode.replace("_MODE", ""))
            self.diagnostics_var.set(
                f"Presents {snapshot.present_count:,}  •  monitor {self.display_var.get()}  •  "
                f"interval {snapshot.present_interval_ms:.2f} ms  •  {snapshot.timing_note}"
            )
            finished = not worker.is_alive()
            if snapshot.state == CampaignState.DONE and snapshot.run_number == snapshot.run_total and finished:
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
            if snapshot.state in (CampaignState.ERROR, CampaignState.STOPPED) and finished:
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self._stop_pending = False
        elif worker is not None and not worker.is_alive() and self._stop_pending:
            self._set_state("STOPPED", "Presentation stopped. Configure or restart the campaign when ready.")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._stop_pending = False
        self.window.after(16, self._tick)

    def analyze(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window, title="Analyze Android PHY Lab export",
            filetypes=(("JSON Lines", "*.jsonl"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            self._set_analysis(format_analysis(analyze_jsonl(path)))
        except Exception as exc:
            messagebox.showerror("PHY Lab analysis", str(exc), parent=self.window)

    def open_camera_receiver(self) -> None:
        """Launch the receiver separately so camera work cannot disturb VSync."""
        try:
            subprocess.Popen([
                sys.executable, "-m",
                "superqr_desktop.v7_capacity_lab.camera_receiver_ui",
            ])
        except Exception as exc:
            messagebox.showerror("PC Camera Receiver", str(exc), parent=self.window)

    def _set_analysis(self, text: str) -> None:
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", text)
        self.analysis_text.configure(state="disabled")

    def export(self) -> None:
        if self.worker is None:
            messagebox.showinfo("Physical PHY Lab", "Start a campaign before exporting sender metrics.", parent=self.window)
            return
        path = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".json",
            filetypes=(("JSON", "*.json"),), initialfile="superqr-phy-lab-sender.json",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(self.worker.export_payload(), handle, indent=2, default=str)
            except Exception as exc:
                messagebox.showerror("Physical PHY Lab", str(exc), parent=self.window)

    def close(self) -> None:
        if self.worker is not None:
            self.worker.stop(timeout=0.75)
        self.window.destroy()
        if self.on_close is not None:
            self.on_close()


def open_phy_lab(parent: tk.Tk, on_close=None) -> PhyLabWindow:
    return PhyLabWindow(parent, on_close=on_close)
