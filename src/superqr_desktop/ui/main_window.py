"""SuperQR V7 main control window with TRANSFER and PHASE 1 TEST modes.

TRANSFER sends frames in-process from the existing SDL display window.
PHASE 1 TEST campaigns run in a child process for timing isolation.
"""

from __future__ import annotations

import json
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

from superqr_desktop.campaign.controller import CampaignController, CampaignLifecycle
from superqr_desktop.diagnostics.collector import DiagnosticsCollector
from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.presentation.transfer import TransferPresenter
from superqr_desktop.transfer.controller import TransferController, TransferLifecycle
from superqr_desktop.transfer.timing import TransferCadenceClock
from superqr_desktop.ui import styles
from superqr_desktop.v7.profiles import BY_LABEL, PROFILES
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
from superqr_desktop.v7_capacity_lab.advanced_phy import (
    advanced_profile,
    advanced_profiles,
    build_advanced_envelope,
    build_advanced_qr_matrix,
)
from superqr_desktop.v7_capacity_lab.advanced_renderer import AdvancedFrameComposer
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    GridFrameSequence,
    build_qr_matrix,
    build_run_envelope,
    grid_profiles,
    qr_controls,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_phy_selection_manifest
from superqr_desktop.v7_capacity_lab.run_sync import LabRunEnvelope, RunState
from superqr_desktop.v7_capacity_lab.shapegrid import (
    build_shapegrid_frame_cells,
    shapegrid_profile,
    shapegrid_profiles,
)
from superqr_desktop.v7_capacity_lab.shapegrid_renderer import ShapeGridFrameComposer


SIZE_PRESETS = [1000, 900, 800, 700, 600, 500, 400]


class MainWindow:
    """Single SuperQR V7 desktop control application.

    Two modes:
      TRANSFER     — file transfer on the main-process SDL display
      PHASE 1 TEST — physical PHY campaign testing in an isolated SDL process
    """

    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash

        # -- root window must exist before any Tk variables --
        self.root = tk.Tk()
        self.root.title("SuperQR V7")
        self.root.geometry("570x700")
        self.root.minsize(540, 640)
        self.root.configure(bg=styles.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # -- back end --
        pygame.init()
        DisplayController._apply_event_filter()
        self.display = DisplayController(contract)
        self.detected_displays = self.display.detect_displays()
        self.transfer_ctrl = TransferController()
        self.campaign_ctrl = CampaignController()
        self.transfer_presenter = TransferPresenter(self.display)
        self.transfer_clock = TransferCadenceClock()
        self.diag = DiagnosticsCollector()

        # -- UI state --
        self._mode = tk.StringVar(value="TRANSFER")
        self._transfer_after_id: str | None = None

        # -- display vars --
        labels = [d["label"] for d in self.detected_displays]
        self._selected_display_str = tk.StringVar(value=labels[0] if labels else "Display 1")
        self._selected_size_var = tk.IntVar(value=1000)
        self._window_mode_var = tk.StringVar(value="windowed")

        # -- transfer vars --
        self._transfer_profile_var = tk.StringVar(value=PROFILES[0].label)
        self._transfer_cadence_var = tk.StringVar(value="100 ms")
        self._transfer_file_label = tk.StringVar(value="No file selected")
        self._transfer_meta_label = tk.StringVar(value="")
        self._transfer_speed_label = tk.StringVar(value="")
        self._transfer_progress_label = tk.StringVar(value="")

        # -- campaign vars --
        self._campaign_preset_var = tk.StringVar(value="Selected profile")
        self._campaign_candidate_var = tk.StringVar(value="mono_64x50_matched")
        self._campaign_frames_var = tk.IntVar(value=256)
        self._campaign_dwell_var = tk.StringVar(value="3")
        self._campaign_progress_label = tk.StringVar(value="")
        self._campaign_speed_label = tk.StringVar(value="")

        # -- build UI --
        self._style = styles.setup_styles(self.root)
        self._build_ui()
        self._update_campaign_ui()
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
        self._build_display_card(main)
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

    def _build_display_card(self, parent):
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
        # profile
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Profile", style="Card.TLabel").pack(side="left")
        self._transfer_profile_combo = ttk.Combobox(
            row, textvariable=self._transfer_profile_var,
            values=[p.label for p in PROFILES], state="readonly", width=24,
        )
        self._transfer_profile_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._transfer_profile_combo.bind("<<ComboboxSelected>>", self._on_transfer_profile_changed)
        # cadence
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(5, 0))
        ttk.Label(row, text="Interval", style="Card.TLabel").pack(side="left")
        values = [f"{v} ms" for v in TransferController.INTERVAL_PRESETS]
        self._transfer_cadence_combo = ttk.Combobox(
            row, textvariable=self._transfer_cadence_var,
            values=values, state="readonly", width=10,
        )
        self._transfer_cadence_combo.pack(side="left", padx=8)
        self._transfer_cadence_combo.bind("<<ComboboxSelected>>", self._on_transfer_cadence_changed)
        self._lbl_transfer_detail = ttk.Label(row, text="", style="Muted.TLabel")
        self._lbl_transfer_detail.pack(side="left", padx=8)

        # file
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Select file", command=self._on_select_file).pack(
            side="left", fill="x", expand=True)
        # nav
        nav = ttk.Frame(card, style="Card.TFrame")
        nav.pack(fill="x", pady=(5, 0))
        self._btn_prev = ttk.Button(nav, text="◀ Prev", command=self._on_prev_frame)
        self._btn_prev.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._btn_next = ttk.Button(nav, text="Next ▶", command=self._on_next_frame)
        self._btn_next.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._lbl_file = ttk.Label(card, textvariable=self._transfer_file_label,
                                    style="Card.TLabel")
        self._lbl_file.pack(anchor="w", pady=(6, 2))
        self._lbl_meta = ttk.Label(card, textvariable=self._transfer_meta_label,
                                    style="Muted.TLabel")
        self._lbl_meta.pack(anchor="w")
        self._lbl_speed = ttk.Label(card, textvariable=self._transfer_speed_label,
                                     style="Muted.TLabel")
        self._lbl_speed.pack(anchor="w", pady=(2, 0))
        self._lbl_progress = ttk.Label(card, textvariable=self._transfer_progress_label,
                                        style="Muted.TLabel")
        self._lbl_progress.pack(anchor="w", pady=(2, 0))

    def _build_phase1_panel(self, parent):
        card = styles.card(parent, "PHASE 1 TEST")
        # campaign preset
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Campaign", style="Card.TLabel").pack(side="left")
        self._campaign_preset_combo = ttk.Combobox(
            row, textvariable=self._campaign_preset_var,
            values=CampaignController.PRESETS, state="readonly", width=28,
        )
        self._campaign_preset_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._campaign_preset_combo.bind("<<ComboboxSelected>>", self._on_campaign_preset_changed)
        # candidate
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Candidate", style="Card.TLabel").pack(side="left")
        self._campaign_candidate_combo = ttk.Combobox(
            row, textvariable=self._campaign_candidate_var,
            values=self.campaign_ctrl.available_profiles, state="readonly", width=28,
        )
        self._campaign_candidate_combo.pack(side="left", padx=8, fill="x", expand=True)
        self._campaign_candidate_combo.bind("<<ComboboxSelected>>", self._on_campaign_candidate_changed)
        # frames + dwell
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
        # test frame + run count
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self._btn_test_frame = ttk.Button(row, text="TEST FRAME",
                                           command=self._on_test_frame)
        self._btn_test_frame.pack(side="left")
        ttk.Label(row, text="Runs:", style="Card.TLabel").pack(side="left", padx=(12, 0))
        self._lbl_run_count = ttk.Label(row, text=str(self.campaign_ctrl.run_count),
                                         style="Card.TLabel")
        self._lbl_run_count.pack(side="left", padx=8)
        # progress
        self._lbl_campaign_progress = ttk.Label(
            card, textvariable=self._campaign_progress_label, style="Muted.TLabel",
        )
        self._lbl_campaign_progress.pack(anchor="w", pady=(9, 0))
        # speed in seconds
        self._lbl_campaign_speed = ttk.Label(
            card, textvariable=self._campaign_speed_label, style="Muted.TLabel",
        )
        self._lbl_campaign_speed.pack(anchor="w", pady=(4, 0))

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
        self._ensure_both_workers_stopped()
        # ensure display is back after campaign
        if self.display.screen is None:
            self._apply_display()

        self._mode.set(mode)
        self._update_mode_button_styles()
        self._swap_mode_panel()
        self._update_status()
        self._update_transfer_ui()
        self._update_campaign_ui()

    def _update_mode_button_styles(self):
        if self._mode.get() == "TRANSFER":
            self._btn_transfer.configure(style="Accent.TButton")
            self._btn_phase1.configure(style="Mode.TButton")
        else:
            self._btn_transfer.configure(style="Mode.TButton")
            self._btn_phase1.configure(style="Accent.TButton")

    def _swap_mode_panel(self):
        self._transfer_panel.pack_forget()
        self._phase1_panel.pack_forget()
        if self._mode.get() == "TRANSFER":
            self._transfer_panel.pack(fill="x")
        else:
            self._phase1_panel.pack(fill="x")

    def _ensure_both_workers_stopped(self):
        if self.campaign_ctrl.lifecycle not in (CampaignLifecycle.IDLE, CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
            self.campaign_ctrl.request_stop()
        self._drain_campaign_completion()
        self._cancel_transfer_tick()
        self.transfer_ctrl.stop_presenting()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_size_selected(self, _event=None):
        try:
            self._selected_size_var.set(int(self._size_combo.get().replace(" px", "")))
        except ValueError:
            pass

    def _on_transfer_profile_changed(self, _event=None):
        profile = BY_LABEL.get(self._transfer_profile_var.get())
        if profile is None:
            return
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._cancel_transfer_tick()
            self.transfer_ctrl.stop_presenting()
        self.transfer_ctrl.set_profile(profile)
        self.transfer_presenter.invalidate_renderer()
        if self.transfer_ctrl.has_file:
            self._render_transfer_frame()
        self._update_transfer_ui()

    def _on_transfer_cadence_changed(self, _event=None):
        try:
            ms = int(self._transfer_cadence_var.get().replace(" ms", ""))
            self.transfer_ctrl.set_interval(ms)
            if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
                self.transfer_clock.reschedule(time.monotonic(), ms)
                self._schedule_transfer_tick(replace=True)
            self._update_transfer_ui()
        except ValueError:
            pass

    def _apply_display(self):
        try:
            if self.campaign_ctrl.lifecycle not in (
                CampaignLifecycle.IDLE, CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED,
            ):
                return
            if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
                self._cancel_transfer_tick()
                self.transfer_ctrl.stop_presenting()

            idx = self._selected_display_index()
            marker = self._selected_size_var.get()
            fullscreen = self._window_mode_var.get() == "fullscreen"
            metrics = self.display.setup_display(idx, fullscreen, marker)
            self.campaign_ctrl.set_display(idx, fullscreen, marker)
            self.transfer_presenter.invalidate_renderer()

            canvas = self.display.screen.get_size()
            self._lbl_display_info.config(
                text=f"Display {canvas[0]}×{canvas[1]}  •  marker {marker}px  "
                     f"•  active {metrics.active_width}×{metrics.active_height}",
            )
            self.display.render_standby()
            self._update_transfer_ui()
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
            self._cancel_transfer_tick()
            self.transfer_ctrl.stop_presenting()
            self._update_transfer_ui()
        else:
            if self.campaign_ctrl.lifecycle in (CampaignLifecycle.STARTING, CampaignLifecycle.RUNNING):
                self.campaign_ctrl.request_stop()

    def _on_select_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        try:
            if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
                self._cancel_transfer_tick()
                self.transfer_ctrl.stop_presenting()
            self.transfer_ctrl.select_file(path)
            self.diag.reset()
            self._render_transfer_frame()
            self._update_transfer_ui()
        except Exception as exc:
            self._set_error(exc, "Could not prepare transfer")

    def _on_prev_frame(self):
        if not self.transfer_ctrl.has_file or self.transfer_ctrl.lifecycle != TransferLifecycle.IDLE:
            return
        self.transfer_ctrl.prev_frame()
        self._render_transfer_frame()
        self._update_transfer_ui()

    def _on_next_frame(self):
        if not self.transfer_ctrl.has_file or self.transfer_ctrl.lifecycle != TransferLifecycle.IDLE:
            return
        self.transfer_ctrl.next_frame()
        self._render_transfer_frame()
        self._update_transfer_ui()

    def _render_transfer_frame(self):
        """Render one transfer frame on the existing SDL display."""
        if not self.transfer_ctrl.has_file or self.display.screen is None:
            return
        p = self.transfer_ctrl.profile
        if p.is_qr:
            frame_bytes = self.transfer_ctrl.get_frame_bytes()
            timing = self.transfer_presenter.render_qr_bytes(
                frame_bytes, self.display.marker_size, p,
            )
        else:
            symbols = self.transfer_ctrl.get_frame_symbols()
            timing = self.transfer_presenter.render_frame(
                symbols, self.display.marker_size, p,
            )
        self.diag.record_present(
            self.transfer_ctrl.current_frame_idx,
            self.transfer_ctrl.interval_ms,
            timing["render_ms"],
            timing["flip_ms"],
        )

    def _on_test_frame(self):
        """Render one static test frame for the selected candidate profile."""
        marker = self.display.marker_size
        screen = self.display.screen
        if screen is None:
            return
        candidate = self._campaign_candidate_var.get()

        try:
            renderer = LabRenderer(marker)
            manifest = load_phy_selection_manifest()

            if candidate in grid_profiles():
                sequence = GridFrameSequence(candidate)
                _frame_index, matrix = sequence.next_frame()
                envelope = build_run_envelope(
                    candidate, 0x0001, 0, 1,
                    float(self._campaign_dwell_var.get()),
                )
                renderer.prepare_logical_frame(
                    matrix,
                    payload_bbox=manifest["payload_bbox"],
                    sync_bits=envelope.bits(),
                    sync_bboxes=(manifest["run_sync"]["top_bbox"],
                                 manifest["run_sync"]["bottom_bbox"]),
                    sync_rows=int(manifest["run_sync"]["rows"]),
                    sync_cols=int(manifest["run_sync"]["cols"]),
                )
            elif candidate in qr_controls():
                control = qr_controls()[candidate]
                quiet = int(control["quiet_zone_modules"])
                matrix = build_qr_matrix(
                    control, 0, run_token=0x0001, frame_count=1,
                    dwell_epochs=float(self._campaign_dwell_var.get()),
                )
                native = renderer.build_qr_native_surface(matrix, quiet)
                renderer.prepare_qr_native_surface(native)
            elif candidate in advanced_profiles():
                prof = advanced_profile(candidate)
                composer = AdvancedFrameComposer(renderer)
                lane_surfaces = {}
                for lane in prof["lanes"]:
                    if lane["kind"] == "qr":
                        lane_id = int(lane["lane_id"])
                        quiet = int(lane["quiet_zone_modules"])
                        matrix = build_advanced_qr_matrix(
                            prof,
                            lane,
                            0,
                            run_token=0x0001,
                            frame_count=1,
                            dwell_epochs=float(self._campaign_dwell_var.get()),
                        )
                        native = renderer.build_qr_native_surface(matrix, quiet)
                        lane_surfaces[lane_id] = native
                sync_bits = None
                if bool(prof["requires_carrier"]):
                    sync_bits = build_advanced_envelope(
                        prof,
                        0x0001,
                        0,
                        1,
                        float(self._campaign_dwell_var.get()),
                    ).bits()
                composer.prepare(prof, 0, lane_surfaces, sync_bits=sync_bits)
            elif candidate in shapegrid_profiles():
                prof = shapegrid_profile(candidate)
                composer = ShapeGridFrameComposer(renderer)
                if composer.subcell_scale(prof) < 1:
                    minimum = int(prof.get("minimum_reference_marker_px_for_subcell_scale_1", 0))
                    suffix = f"; profile minimum reference marker is ~{minimum}px" if minimum else ""
                    raise ValueError(
                        f"ShapeGrid {prof['name']} projects below 1 px/subcell at marker "
                        f"{renderer.marker_size}px{suffix}"
                    )
                cells = build_shapegrid_frame_cells(
                    prof,
                    0,
                    run_token=0x0001,
                    state=RunState.RUNNING,
                    frame_count=1,
                    dwell_epochs=float(self._campaign_dwell_var.get()),
                )
                sync_bits = LabRunEnvelope(
                    state=RunState.RUNNING,
                    profile_id=int(prof["profile_id"]),
                    run_token=0x0001,
                    frame_index=0,
                    frame_count=1,
                    dwell_epochs=float(self._campaign_dwell_var.get()),
                ).bits()
                composer.prepare(prof, cells, sync_bits=sync_bits)
            else:
                return

            surface = renderer.cached_frame_display
            if surface is None:
                return

            cw, ch = screen.get_size()
            screen.fill((8, 10, 14))
            screen.blit(surface, ((cw - marker) // 2, (ch - marker) // 2))
            pygame.display.flip()
            self._lbl_err.config(text=f"Test frame: {candidate}")
        except Exception as exc:
            self._set_error(exc)

    def _start_transfer(self):
        if not self.transfer_ctrl.has_file:
            messagebox.showwarning("SuperQR V7", "Select a file first.")
            return
        if self.transfer_ctrl.lifecycle != TransferLifecycle.IDLE:
            return

        ok = self.transfer_ctrl.start_presenting()
        if not ok:
            messagebox.showwarning("SuperQR V7", "Could not start transfer.")
            return

        try:
            self.diag.reset()
            # Frame 0 is physically presented immediately; the cadence clock then
            # schedules frame 1 rather than making START wait one whole interval.
            self._render_transfer_frame()
            self.transfer_clock.start(time.monotonic(), self.transfer_ctrl.interval_ms)
            self._schedule_transfer_tick()
        except Exception as exc:
            self._cancel_transfer_tick()
            self.transfer_ctrl.stop_presenting()
            self._set_error(exc)
        self._update_transfer_ui()
        self._update_status()

    def _schedule_transfer_tick(self, *, replace: bool = False):
        if replace and self._transfer_after_id is not None:
            try:
                self.root.after_cancel(self._transfer_after_id)
            except tk.TclError:
                pass
            self._transfer_after_id = None
        if self.transfer_ctrl.lifecycle != TransferLifecycle.PRESENTING or not self.transfer_clock.running:
            return
        if self._transfer_after_id is not None:
            return
        delay_ms = self.transfer_clock.delay_ms(time.monotonic())
        self._transfer_after_id = self.root.after(delay_ms, self._on_transfer_tick)

    def _cancel_transfer_tick(self):
        after_id = self._transfer_after_id
        self._transfer_after_id = None
        self.transfer_clock.stop()
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def _on_transfer_tick(self):
        self._transfer_after_id = None
        if self.transfer_ctrl.lifecycle != TransferLifecycle.PRESENTING or not self.transfer_clock.running:
            return
        now = time.monotonic()
        if not self.transfer_clock.due(now):
            self._schedule_transfer_tick()
            return
        try:
            self.transfer_ctrl.advance_frame()
            self._render_transfer_frame()
            self.transfer_clock.mark_presented(time.monotonic(), self.transfer_ctrl.interval_ms)
        except Exception as exc:
            self._cancel_transfer_tick()
            self.transfer_ctrl.stop_presenting()
            self._set_error(exc)
            self._update_transfer_ui()
            return
        self._schedule_transfer_tick()

    def _start_campaign(self):
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            return

        idx = self._selected_display_index()
        marker = self._selected_size_var.get()
        fullscreen = self._window_mode_var.get() == "fullscreen"
        self.campaign_ctrl.set_display(idx, fullscreen, marker)

        self.display.close()

        ok = self.campaign_ctrl.start()
        if not ok:
            self._apply_display()
            messagebox.showwarning("SuperQR V7", "No campaign runs configured.")
            return
        self._update_status()
        self._update_campaign_ui()

    def _on_campaign_preset_changed(self, _event=None):
        preset = self._campaign_preset_var.get()
        self.campaign_ctrl.set_preset(preset)
        self._update_campaign_ui()

    def _on_campaign_candidate_changed(self, _event=None):
        self.campaign_ctrl.set_profile(self._campaign_candidate_var.get())
        self._update_campaign_ui()

    def _on_campaign_frames_changed(self, _event=None):
        try:
            self.campaign_ctrl.set_frames(self._campaign_frames_var.get())
            self._update_campaign_ui()
        except (ValueError, tk.TclError):
            pass

    def _on_campaign_dwell_changed(self, _event=None):
        try:
            self.campaign_ctrl.set_dwell(float(self._campaign_dwell_var.get()))
            self._update_campaign_ui()
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # UI/status polling loop (presentation cadence is scheduled separately)
    # ------------------------------------------------------------------

    def _tick(self):
        try:
            self.campaign_ctrl.poll()

            # campaign display reclaim
            if self.campaign_ctrl.needs_display_reclaim:
                snapshot = self.campaign_ctrl.reclaim_display()
                self._apply_display()
                if snapshot is not None:
                    if snapshot.error:
                        self._lbl_err.config(text=f"Campaign error: {snapshot.error}")
                    self._export_campaign_results()
                self._update_campaign_ui()
                self._update_status()

            # campaign progress
            if self.campaign_ctrl.lifecycle in (CampaignLifecycle.STARTING, CampaignLifecycle.RUNNING):
                snap = self.campaign_ctrl.snapshot()
                if snap is not None:
                    self._campaign_progress_label.set(
                        f"Run {snap.run_number}/{snap.run_total}  "
                        f"•  frame {snap.frame_index + 1}/{snap.frame_count}  "
                        f"•  {snap.state.value}  "
                        f"•  {snap.present_fps:.1f} fps",
                    )
                    if snap.error:
                        self._lbl_err.config(text=f"Error: {snap.error}")
                    self._update_status()

            # transfer progress; cadence itself is NOT driven by this 20 Hz loop.
            if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
                diag = self.diag.snapshot()
                measured_fps = float(diag["present_measured_fps"])
                self._transfer_progress_label.set(
                    f"Session {self.transfer_ctrl.session_id}  •  "
                    f"frame {self.transfer_ctrl.current_frame_idx + 1}/{self.transfer_ctrl.total_frames}  "
                    f"•  {diag['present_count']} presents  "
                    f"•  {measured_fps:.1f} fps measured  "
                    f"•  late {diag['late_present_count']}",
                )

            # SDL events (only when main process owns the display)
            if self.display.screen is not None:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT or (
                        event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                    ):
                        self.close()
                        return

            self.root.after(50, self._tick)
        except tk.TclError:
            return
        except Exception:
            self.root.after(50, self._tick)

    def _drain_campaign_completion(self):
        """Block until the campaign worker finishes (with timeout)."""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.campaign_ctrl.poll()
            if self.campaign_ctrl.needs_display_reclaim:
                self.campaign_ctrl.reclaim_display()
                self._apply_display()
                break
            if self.campaign_ctrl.lifecycle == CampaignLifecycle.IDLE:
                break
            time.sleep(0.05)
            self.root.update()

    # ------------------------------------------------------------------
    # Campaign export
    # ------------------------------------------------------------------

    def _export_campaign_results(self):
        export = self.campaign_ctrl.last_export_payload()
        if export is None:
            return
        campaign_id = export.get("current", {}).get("profile", "unknown")
        path = os.path.join(os.path.dirname(__file__), "..", "..",
            f"campaign_sender_{campaign_id}_{int(time.time())}.json")
        try:
            with open(path, "w") as f:
                json.dump(export, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI updates
    # ------------------------------------------------------------------

    def _update_transfer_ui(self):
        ctrl = self.transfer_ctrl
        p = ctrl.profile
        if p.is_qr:
            self._lbl_transfer_detail.config(
                text=f"QR V{p.qr_version}-{p.qr_ecc}  •  {p.frame_size} B/frame  •  {p.payload_size} B payload",
            )
        else:
            self._lbl_transfer_detail.config(
                text=f"{p.frame_size} B/frame  •  cell {p.cell_width:.1f}×{p.cell_height:.1f}px @ 1000",
            )
        if ctrl.has_file:
            self._transfer_file_label.set(
                f"{ctrl.filename}  •  {ctrl.mime_type}",
            )
            self._transfer_meta_label.set(
                f"{ctrl.file_size:,} B  •  CRC32 {ctrl.file_crc32:08X}",
            )
            rotation_s = ctrl.total_frames * ctrl.interval_ms / 1000.0
            payload_kibs = p.payload_kib_s(ctrl.interval_ms)
            self._transfer_speed_label.set(
                f"Rotation {rotation_s:.1f}s ({ctrl.total_frames} frames × {ctrl.interval_ms}ms)  "
                f"•  {payload_kibs:.1f} KiB/s theoretical payload",
            )
            if ctrl.lifecycle != TransferLifecycle.PRESENTING:
                self._transfer_progress_label.set(
                    f"Session {ctrl.session_id}  •  "
                    f"frame {ctrl.current_frame_idx + 1}/{ctrl.total_frames}  •  {p.key}",
                )
        else:
            self._transfer_file_label.set("No file selected")
            self._transfer_meta_label.set(
                f"AUTO receiver profile id {p.id}  •  {p.grid}×{p.grid}  •  {p.color_count} colors",
            )
            self._transfer_speed_label.set("")
            self._transfer_progress_label.set("")

        # frame nav: only in IDLE with a file loaded
        can_nav = ctrl.has_file and ctrl.lifecycle == TransferLifecycle.IDLE
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

        candidate = self._campaign_candidate_var.get()
        dwell_str = self._campaign_dwell_var.get()
        try:
            dwell = float(dwell_str)
        except (ValueError, tk.TclError):
            dwell = 3.0
        try:
            frames = int(self._campaign_frames_var.get())
        except (ValueError, tk.TclError):
            frames = 256

        # VSYNC dwell-based effective FPS (60 Hz canonical reference)
        eff_fps = 60.0 / dwell if dwell > 0 else 0.0
        frame_ms = dwell * 1000.0 / 60.0
        run_sec = frames * dwell / 60.0

        # Frame bytes from profile
        frame_bytes = 0
        if candidate in grid_profiles():
            gp = grid_profiles()[candidate]
            frame_bytes = int(gp.get("raw_bytes_per_frame", 0))
        elif candidate in qr_controls():
            qc = qr_controls()[candidate]
            frame_bytes = int(qc.get("frame_bytes", 0))

        kib_s = (frame_bytes * eff_fps) / 1024.0 if dwell > 0 else 0.0
        run_sec_total = run_sec + 1.25  # READY + DONE per run

        self._campaign_speed_label.set(
            f"{eff_fps:.1f} FPS • {frame_ms:.0f}ms/frame • {frame_bytes} B/frame • {kib_s:.1f} KiB/s • {run_sec_total:.0f}s"
        )

        if ctrl.lifecycle == CampaignLifecycle.IDLE:
            self._campaign_progress_label.set(
                f"{ctrl.run_count} run(s) queued  •  {ctrl.frames} frames/run  •  dwell {ctrl.dwell}",
            )

    def _update_status(self):
        cl = self.campaign_ctrl.lifecycle
        tl = self.transfer_ctrl.lifecycle

        if cl == CampaignLifecycle.IDLE and tl == TransferLifecycle.IDLE:
            self._lbl_status.config(text="READY", foreground=styles.GOOD)
        elif cl not in (CampaignLifecycle.IDLE, CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
            self._lbl_status.config(text=cl.value, foreground=styles.ACCENT)
        elif tl == TransferLifecycle.PRESENTING:
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
        self._cancel_transfer_tick()
        self.transfer_ctrl.stop_presenting()
        self.campaign_ctrl.request_stop()
        self._drain_campaign_completion()
        self.display.close()
        pygame.quit()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
