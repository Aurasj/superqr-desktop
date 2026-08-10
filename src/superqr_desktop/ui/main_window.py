"""SuperQR V7 main control window with TRANSFER and PHASE 1 TEST modes."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.diagnostics.collector import DiagnosticsCollector
from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.presentation.transfer import TransferPresenter
from superqr_desktop.transfer.controller import TransferController
from superqr_desktop.ui import styles
from superqr_desktop.v7.profiles import BY_LABEL, PROFILES

SIZE_PRESETS = [1000, 900, 800, 700, 600, 500, 400]


class MainWindow:
    """Single clean SuperQR V7 desktop control application.

    Two modes:
      TRANSFER    — file transfer via optical profile
      PHASE 1 TEST — physical PHY campaign testing
    """

    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash

        # -- back end --
        pygame.init()
        self.display = DisplayController(contract)
        self.detected_displays = self.display.detect_displays()
        self.transfer_ctrl = TransferController()
        self.campaign_ctrl = CampaignController()
        self.transfer_presenter = TransferPresenter(self.display)
        self.diag = DiagnosticsCollector()

        # -- UI state --
        self._mode = tk.StringVar(value="TRANSFER")
        self._standby_rendered = False

        # -- display vars --
        labels = [d["label"] for d in self.detected_displays]
        self._selected_display_str = tk.StringVar(value=labels[0] if labels else "Display 1")
        self._selected_size_var = tk.IntVar(value=800)
        self._window_mode_var = tk.StringVar(value="windowed")

        # -- profile vars (mode-dependent) --
        self._profile_var = tk.StringVar(value=PROFILES[0].label)
        self._cadence_var = tk.StringVar(value="100 ms")
        self._cadence_transfer_values = [f"{v} ms" for v in TransferController.INTERVAL_PRESETS]
        self._cadence_campaign_values = ["2 epochs", "3 epochs"]

        # -- transfer vars --
        self._transfer_file_label = tk.StringVar(value="No file selected")
        self._transfer_meta_label = tk.StringVar(value="")
        self._transfer_progress_label = tk.StringVar(value="")

        # -- campaign vars --
        self._campaign_preset_var = tk.StringVar(value="Selected profile")
        self._campaign_candidate_var = tk.StringVar(value="mono_64x50_matched")
        self._campaign_frames_var = tk.IntVar(value=256)
        self._campaign_dwell_var = tk.StringVar(value="3")
        self._campaign_progress_label = tk.StringVar(value="")

        # -- build --
        self.root = tk.Tk()
        self.root.title("SuperQR V7")
        self.root.geometry("570x700")
        self.root.minsize(540, 640)
        self.root.configure(bg=styles.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style = styles.setup_styles(self.root)
        self._build_ui()
        self._apply_display()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="SuperQR V7", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Adaptive offline screen → camera transfer",
                  foreground=styles.MUTED).pack(anchor="w", pady=(0, 8))

        self._build_mode_toggle(main)
        self._build_common_controls(main)
        self._build_action_buttons(main)
        self._build_mode_panels(main)
        self._build_status_bar(main)

    def _build_mode_toggle(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        self._btn_transfer = ttk.Button(row, text="TRANSFER", style="Mode.TButton",
                                         command=lambda: self._switch_mode("TRANSFER"))
        self._btn_transfer.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._btn_phase1 = ttk.Button(row, text="PHASE 1 TEST", style="Mode.TButton",
                                       command=lambda: self._switch_mode("PHASE1"))
        self._btn_phase1.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._update_mode_button_styles()

    def _build_common_controls(self, parent):
        # -- display card --
        card = styles.card(parent, "DISPLAY")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Monitor", style="Card.TLabel").pack(side="left")
        self._disp_combo = ttk.Combobox(
            row, textvariable=self._selected_display_str,
            values=[d["label"] for d in self.detected_displays],
            state="readonly", width=26,
        )
        self._disp_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._size_combo = ttk.Combobox(
            row, values=[f"{v} px" for v in SIZE_PRESETS],
            state="readonly", width=9,
        )
        self._size_combo.set("800 px")
        self._size_combo.pack(side="left")
        self._size_combo.bind("<<ComboboxSelected>>", self._on_size_selected)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Radiobutton(row, text="Windowed", value="windowed",
                        variable=self._window_mode_var).pack(side="left")
        ttk.Radiobutton(row, text="Fullscreen", value="fullscreen",
                        variable=self._window_mode_var).pack(side="left", padx=(14, 0))
        ttk.Button(row, text="Apply", command=self._apply_display).pack(side="right")

        # -- profile card --
        card = styles.card(parent, "PROFILE")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Profile", style="Card.TLabel").pack(side="left")
        self._profile_combo = ttk.Combobox(
            row, textvariable=self._profile_var,
            values=[p.label for p in PROFILES], state="readonly", width=34,
        )
        self._profile_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._profile_combo.bind("<<ComboboxSelected>>", self._on_profile_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Cadence", style="Card.TLabel").pack(side="left")
        self._cadence_combo = ttk.Combobox(
            row, textvariable=self._cadence_var,
            values=self._cadence_transfer_values, state="readonly", width=12,
        )
        self._cadence_combo.pack(side="left", padx=8)
        self._cadence_combo.bind("<<ComboboxSelected>>", self._on_cadence_changed)
        self._lbl_profile_detail = ttk.Label(row, text="", style="Muted.TLabel")
        self._lbl_profile_detail.pack(side="left", padx=8)

    def _build_action_buttons(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        self._btn_start = ttk.Button(row, text="START", style="Accent.TButton",
                                      command=self._on_start)
        self._btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._btn_stop = ttk.Button(row, text="STOP", command=self._on_stop)
        self._btn_stop.pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_mode_panels(self, parent):
        self._transfer_panel = ttk.Frame(parent)
        self._build_transfer_panel(self._transfer_panel)
        self._phase1_panel = ttk.Frame(parent)
        self._build_phase1_panel(self._phase1_panel)
        self._transfer_panel.pack(fill="x")

    def _build_transfer_panel(self, parent):
        card = styles.card(parent, "TRANSFER")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Select file", command=self._on_select_file).pack(
            side="left", fill="x", expand=True)
        nav = ttk.Frame(card, style="Card.TFrame")
        nav.pack(fill="x", pady=(8, 0))
        self._btn_prev = ttk.Button(nav, text="◀ Prev", command=self._on_prev_frame)
        self._btn_prev.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._btn_next = ttk.Button(nav, text="Next ▶", command=self._on_next_frame)
        self._btn_next.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._lbl_file = ttk.Label(card, textvariable=self._transfer_file_label,
                                    style="Card.TLabel")
        self._lbl_file.pack(anchor="w", pady=(9, 2))
        self._lbl_meta = ttk.Label(card, textvariable=self._transfer_meta_label,
                                    style="Muted.TLabel")
        self._lbl_meta.pack(anchor="w")
        self._lbl_progress = ttk.Label(card, textvariable=self._transfer_progress_label,
                                        style="Muted.TLabel")
        self._lbl_progress.pack(anchor="w", pady=(2, 0))

    def _build_phase1_panel(self, parent):
        card = styles.card(parent, "PHASE 1 TEST")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Campaign", style="Card.TLabel").pack(side="left")
        self._campaign_preset_combo = ttk.Combobox(
            row, textvariable=self._campaign_preset_var,
            values=CampaignController.PRESETS, state="readonly", width=28,
        )
        self._campaign_preset_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._campaign_preset_combo.bind("<<ComboboxSelected>>", self._on_campaign_preset_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Candidate", style="Card.TLabel").pack(side="left")
        self._campaign_candidate_combo = ttk.Combobox(
            row, textvariable=self._campaign_candidate_var,
            values=self.campaign_ctrl.available_profiles, state="readonly", width=28,
        )
        self._campaign_candidate_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._campaign_candidate_combo.bind("<<ComboboxSelected>>", self._on_campaign_candidate_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Frames", style="Card.TLabel").pack(side="left")
        self._campaign_frames_spin = ttk.Spinbox(
            row, textvariable=self._campaign_frames_var,
            from_=1, to=256, width=6,
        )
        self._campaign_frames_spin.pack(side="left", padx=8)
        self._campaign_frames_spin.bind("<Return>", self._on_campaign_frames_changed)
        ttk.Label(row, text="Dwell", style="Card.TLabel").pack(side="left", padx=(12, 0))
        self._campaign_dwell_combo = ttk.Combobox(
            row, textvariable=self._campaign_dwell_var,
            values=[str(v) for v in CampaignController.DWELL_OPTIONS],
            state="readonly", width=4,
        )
        self._campaign_dwell_combo.pack(side="left", padx=8)
        self._campaign_dwell_combo.bind("<<ComboboxSelected>>", self._on_campaign_dwell_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Runs:", style="Card.TLabel").pack(side="left")
        self._lbl_run_count = ttk.Label(row, text=str(self.campaign_ctrl.run_count),
                                         style="Card.TLabel")
        self._lbl_run_count.pack(side="left", padx=8)

        self._lbl_campaign_progress = ttk.Label(
            card, textvariable=self._campaign_progress_label, style="Muted.TLabel",
        )
        self._lbl_campaign_progress.pack(anchor="w", pady=(9, 0))

    def _build_status_bar(self, parent):
        card = styles.card(parent, "STATUS")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        self._lbl_status = ttk.Label(row, text="READY", style="Card.TLabel",
                                      font=("Segoe UI", 10, "bold"))
        self._lbl_status.pack(side="left")
        self._lbl_mode = ttk.Label(row, text="Mode: TRANSFER", style="Muted.TLabel")
        self._lbl_mode.pack(side="right")
        self._lbl_display_info = ttk.Label(card, text="Display: -", style="Muted.TLabel")
        self._lbl_display_info.pack(anchor="w", pady=(5, 0))
        self._lbl_err = ttk.Label(card, text="", style="Muted.TLabel")
        self._lbl_err.pack(anchor="w", pady=(2, 0))

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _switch_mode(self, mode: str):
        if self._mode.get() == mode:
            return
        self._on_stop()
        if self.campaign_ctrl.is_running:
            self.campaign_ctrl.stop()
            self._on_campaign_finished()
        self._mode.set(mode)
        self._update_mode_button_styles()
        self._update_common_dropdowns_for_mode()
        self._swap_mode_panel()
        self._update_status()

        if mode == "TRANSFER":
            self.transfer_presenter.render_standby()
            self._standby_rendered = True
        self._update_transfer_ui()
        self._update_campaign_ui()

    def _update_mode_button_styles(self):
        if self._mode.get() == "TRANSFER":
            self._btn_transfer.configure(style="Accent.TButton")
            self._btn_phase1.configure(style="Mode.TButton")
        else:
            self._btn_transfer.configure(style="Mode.TButton")
            self._btn_phase1.configure(style="Accent.TButton")

    def _update_common_dropdowns_for_mode(self):
        if self._mode.get() == "TRANSFER":
            self._profile_combo.configure(values=[p.label for p in PROFILES])
            self._profile_var.set(self.transfer_ctrl.profile.label)
            self._cadence_combo.configure(values=self._cadence_transfer_values)
            self._cadence_var.set(f"{self.transfer_ctrl.interval_ms} ms")
        else:
            candidates = self.campaign_ctrl.available_profiles
            self._profile_combo.configure(values=candidates)
            self._profile_var.set(self.campaign_ctrl.profile)
            self._cadence_combo.configure(values=self._cadence_campaign_values)
            self._cadence_var.set(f"{self.campaign_ctrl.dwell} epochs")

    def _swap_mode_panel(self):
        self._transfer_panel.pack_forget()
        self._phase1_panel.pack_forget()
        if self._mode.get() == "TRANSFER":
            self._transfer_panel.pack(fill="x")
        else:
            self._phase1_panel.pack(fill="x")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_size_selected(self, _event=None):
        try:
            self._selected_size_var.set(int(self._size_combo.get().replace(" px", "")))
        except ValueError:
            pass

    def _on_profile_changed(self, _event=None):
        if self._mode.get() == "TRANSFER":
            profile = BY_LABEL.get(self._profile_var.get())
            if profile is None:
                return
            self.transfer_ctrl.set_profile(profile)
            self.transfer_presenter.invalidate_renderer()
            self.diag.reset()
            if self.transfer_ctrl.has_file:
                self._render_current_transfer_frame()
            self._update_transfer_ui()
        else:
            self.campaign_ctrl.set_profile(self._profile_var.get())
            self._update_campaign_ui()

    def _on_cadence_changed(self, _event=None):
        val = self._cadence_var.get()
        if self._mode.get() == "TRANSFER":
            try:
                ms = int(val.replace(" ms", ""))
                self.transfer_ctrl.set_interval(ms)
                self.diag.reset()
                self._update_transfer_ui()
            except ValueError:
                pass
        else:
            try:
                epochs = int(val.replace(" epochs", ""))
                self.campaign_ctrl.set_dwell(epochs)
                self._update_campaign_ui()
            except ValueError:
                pass

    def _apply_display(self):
        try:
            idx = self._selected_display_index()
            marker = self._selected_size_var.get()
            fullscreen = self._window_mode_var.get() == "fullscreen"
            metrics = self.display.setup_display(idx, fullscreen, marker)
            self.campaign_ctrl.set_display(idx, fullscreen, marker)
            self.transfer_presenter.invalidate_renderer()
            self.diag.reset()

            canvas = self.display.screen.get_size()
            self._lbl_display_info.config(
                text=f"Display {canvas[0]}×{canvas[1]}  •  marker {marker}px  "
                     f"•  active {metrics.active_width}×{metrics.active_height}",
            )
            if self.transfer_ctrl.has_file:
                self._render_current_transfer_frame()
            else:
                self.transfer_presenter.render_standby()
                self._standby_rendered = True
            self._update_status()
        except Exception as exc:
            self._set_error(exc)

    def _on_start(self):
        if self._mode.get() == "TRANSFER":
            self._start_transfer()
        else:
            self._start_campaign()

    def _on_stop(self):
        if self._mode.get() == "TRANSFER":
            self.transfer_ctrl.stop()
            self._update_transfer_ui()
        else:
            self.campaign_ctrl.request_stop()

    def _on_select_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        try:
            self.transfer_ctrl.select_file(path)
            self.diag.reset()
            self._last_tick = time.monotonic()
            self._render_current_transfer_frame()
            self._update_transfer_ui()
        except Exception as exc:
            self._set_error(exc, "Could not prepare transfer")

    def _on_prev_frame(self):
        if not self.transfer_ctrl.has_file:
            return
        self.transfer_ctrl.stop()
        self.transfer_ctrl.prev_frame()
        self._render_current_transfer_frame()
        self._update_transfer_ui()

    def _on_next_frame(self):
        if not self.transfer_ctrl.has_file:
            return
        self.transfer_ctrl.stop()
        self.transfer_ctrl.next_frame()
        self._render_current_transfer_frame()
        self._update_transfer_ui()

    def _start_transfer(self):
        if not self.transfer_ctrl.has_file:
            messagebox.showwarning("SuperQR V7", "Select a file first.")
            return
        self.transfer_ctrl.start()
        self._last_tick = time.monotonic()
        self.diag.reset()
        self._render_current_transfer_frame()
        self._update_transfer_ui()

    def _start_campaign(self):
        if self.campaign_ctrl.is_running:
            return
        self.display.close()
        self._standby_rendered = False
        ok = self.campaign_ctrl.start()
        if not ok:
            messagebox.showwarning("SuperQR V7", "No campaign runs configured.")
            return
        self._update_status()
        self._update_campaign_ui()

    def _on_campaign_preset_changed(self, _event=None):
        preset = self._campaign_preset_var.get()
        self.campaign_ctrl.set_preset(preset)
        is_selected = (preset == "Selected profile")
        self._campaign_candidate_combo.configure(
            state="readonly" if is_selected else "disabled")
        self._update_campaign_ui()

    def _on_campaign_candidate_changed(self, _event=None):
        self.campaign_ctrl.set_profile(self._campaign_candidate_var.get())
        if self._mode.get() == "PHASE1":
            self._profile_var.set(self._campaign_candidate_var.get())
        self._update_campaign_ui()

    def _on_campaign_frames_changed(self, _event=None):
        try:
            self.campaign_ctrl.set_frames(self._campaign_frames_var.get())
            self._update_campaign_ui()
        except (ValueError, tk.TclError):
            pass

    def _on_campaign_dwell_changed(self, _event=None):
        try:
            self.campaign_ctrl.set_dwell(int(self._campaign_dwell_var.get()))
            self._update_campaign_ui()
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_current_transfer_frame(self):
        if not self.transfer_ctrl.has_file:
            return
        symbols = self.transfer_ctrl.get_frame_symbols()
        timing = self.transfer_presenter.render_frame(
            symbols, self.display.marker_size, self.transfer_ctrl.profile,
        )
        self.diag.record_present(timing["render_ms"], timing["flip_ms"])
        self._standby_rendered = False

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    def _tick(self):
        try:
            if self._mode.get() == "TRANSFER":
                self._tick_transfer()
            else:
                self._tick_phase1()

            # process pygame events (only when main process owns SDL)
            if not self.campaign_ctrl.is_running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT or (
                        event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                    ):
                        self.close()
                        return
            self.root.after(2, self._tick)
        except tk.TclError:
            return

    def _tick_transfer(self):
        if self.transfer_ctrl.state == "SENDING" and self.transfer_ctrl.has_file:
            now = time.monotonic()
            if now - getattr(self, "_last_tick", 0) >= self.transfer_ctrl.interval_ms / 1000.0:
                self._last_tick = now
                self.transfer_ctrl.advance_frame()
                try:
                    self._render_current_transfer_frame()
                    self._update_transfer_ui()
                except Exception as exc:
                    self.transfer_ctrl.stop()
                    self._set_error(exc)

    def _tick_phase1(self):
        if not self.campaign_ctrl.is_running:
            return
        snapshot = self.campaign_ctrl.snapshot()
        if snapshot is not None:
            self._campaign_progress_label.set(
                f"Run {snapshot.run_number}/{snapshot.run_total}  "
                f"•  frame {snapshot.frame_index + 1}/{snapshot.frame_count}  "
                f"•  {snapshot.state.value}  "
                f"•  {snapshot.present_fps:.1f} fps",
            )
            if snapshot.error:
                self._lbl_err.config(text=f"Error: {snapshot.error}")
            self._update_status()

        if not self.campaign_ctrl.is_running:
            # campaign finished or stopped — reclaim display
            self._on_campaign_finished()

    def _on_campaign_finished(self):
        snapshot = self.campaign_ctrl.snapshot()
        self.campaign_ctrl.stop()
        try:
            self._apply_display()
        except Exception as exc:
            self._set_error(exc)
        if snapshot is not None:
            if snapshot.error:
                self._lbl_err.config(text=f"Campaign error: {snapshot.error}")
            elif snapshot.state.value == "DONE":
                self._lbl_err.config(text="Campaign completed.")

    # ------------------------------------------------------------------
    # UI updates
    # ------------------------------------------------------------------

    def _update_transfer_ui(self):
        ctrl = self.transfer_ctrl
        p = ctrl.profile
        self._lbl_profile_detail.config(
            text=f"{p.frame_size} B/frame  •  cell {p.cell_width:.1f}×{p.cell_height:.1f}px @ 1000",
        )
        if ctrl.has_file:
            self._transfer_file_label.set(
                f"{ctrl.filename}  •  {ctrl.mime_type}",
            )
            self._transfer_meta_label.set(
                f"{ctrl.file_size:,} B  •  CRC32 {ctrl.file_crc32:08X}",
            )
            self._transfer_progress_label.set(
                f"Session {ctrl.session_id}  •  "
                f"frame {ctrl.current_frame_idx + 1}/{ctrl.total_frames}  •  {p.key}",
            )
        else:
            self._transfer_file_label.set("No file selected")
            self._transfer_meta_label.set(
                f"AUTO receiver profile id {p.id}  •  {p.grid}×{p.grid}  •  {p.color_count} colors",
            )
            self._transfer_progress_label.set("")

        # frame nav buttons
        can_nav = ctrl.has_file and ctrl.state != "SENDING"
        state = "normal" if can_nav else "disabled"
        self._btn_prev.configure(state=state)
        self._btn_next.configure(state=state)
        self._update_status()

    def _update_campaign_ui(self):
        ctrl = self.campaign_ctrl
        self._lbl_run_count.configure(text=str(ctrl.run_count))

        is_selected = self._campaign_preset_var.get() == "Selected profile"
        self._campaign_candidate_combo.configure(
            state="readonly" if is_selected else "disabled",
        )

        if not ctrl.is_running:
            p = ctrl.profile
            self._lbl_profile_detail.config(text=f"Candidate: {p}")
            self._campaign_progress_label.set(
                f"{ctrl.run_count} run(s) queued  •  {ctrl.frames} frames/run  •  dwell {ctrl.dwell}",
            )

    def _update_status(self):
        if self.campaign_ctrl.is_running:
            snap = self.campaign_ctrl.snapshot()
            if snap is not None:
                self._lbl_status.config(
                    text=snap.state.value, foreground=styles.ACCENT,
                )
            else:
                self._lbl_status.config(text="STARTING", foreground=styles.WARN)
        elif self._mode.get() == "TRANSFER" and self.transfer_ctrl.state == "SENDING":
            self._lbl_status.config(text="SENDING", foreground=styles.ACCENT)
        else:
            self._lbl_status.config(text="READY", foreground=styles.GOOD)

        self._lbl_mode.config(text=f"Mode: {self._mode.get().replace('PHASE1', 'PHASE 1 TEST')}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _selected_display_index(self) -> int:
        label = self._selected_display_str.get()
        found = next((d for d in self.detected_displays if d["label"] == label), None)
        return found["index"] if found else 0

    def _set_error(self, exc: Exception, title: str | None = None):
        msg = f"{type(exc).__name__}: {exc}"
        self.diag.set_error(msg)
        self._lbl_err.config(text=f"Last error: {msg}")
        self._update_status()
        if title:
            messagebox.showerror(title, msg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self):
        self.root.after(0, self._tick)
        self.root.mainloop()

    def close(self):
        self.campaign_ctrl.stop()
        self.display.close()
        pygame.quit()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
