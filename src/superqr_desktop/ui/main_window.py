"""Clean SuperQR desktop UI: production transfer first, PHY lab separate."""

from __future__ import annotations

import json
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

from superqr_desktop.campaign.controller import CampaignController, CampaignLifecycle
from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.presentation.transfer import PreparedQrFrame, TransferPresenter
from superqr_desktop.transfer.controller import TransferController, TransferLifecycle
from superqr_desktop.transfer.timing import TransferCadenceClock
from superqr_desktop.ui import styles


MARKER_SIZE = 1000


class MainWindow:
    """Production file sender plus an isolated physical-test lab."""

    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash
        self.root = tk.Tk()
        self.root.title("SuperQR")
        self.root.geometry("590x720")
        self.root.minsize(560, 650)
        self.root.configure(bg=styles.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        styles.setup_styles(self.root)

        pygame.init()
        DisplayController._apply_event_filter()
        self.display = DisplayController(contract)
        self.detected_displays = self.display.detect_displays()
        self.transfer_ctrl = TransferController()
        self.transfer_presenter = TransferPresenter(self.display)
        self.transfer_clock = TransferCadenceClock()
        self.campaign_ctrl = CampaignController()

        self._mode = tk.StringVar(value="TRANSFER")
        self._transfer_after_id: str | None = None
        self._transfer_waiting_for_first = False
        self._last_transfer_timing: dict[str, float] = {}

        labels = [d["label"] for d in self.detected_displays]
        self._selected_display = tk.StringVar(value=labels[0] if labels else "Display 1")
        self._fullscreen = tk.BooleanVar(value=False)

        self._transfer_mode = tk.StringVar(value=self.transfer_ctrl.mode)
        self._transfer_mode_note = tk.StringVar(value=self.transfer_ctrl.mode_note)
        self._file_label = tk.StringVar(value="No file selected")
        self._file_meta = tk.StringVar(value="Choose any file: photo, audio, video, archive, document…")
        self._transfer_progress = tk.StringVar(value="Ready")
        self._status = tk.StringVar(value="Ready")

        self._lab_preset = tk.StringVar(value=self.campaign_ctrl.preset)
        self._lab_profile = tk.StringVar(value=self.campaign_ctrl.profile)
        self._lab_dwell = tk.StringVar(value=str(self.campaign_ctrl.dwell))
        self._lab_frames = tk.StringVar(value=str(self.campaign_ctrl.frames))
        self._lab_progress = tk.StringVar(value="Lab idle")

        self._build_ui()
        self._apply_display()
        self.root.after(50, self._poll)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="SuperQR", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main,
            text="Offline file transfer • screen → camera • no pairing",
            foreground=styles.MUTED,
        ).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(main)
        row.pack(fill="x", pady=(0, 6))
        self._btn_transfer_mode = ttk.Button(row, text="TRANSFER", style="Accent.TButton", command=lambda: self._switch_mode("TRANSFER"))
        self._btn_transfer_mode.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._btn_lab_mode = ttk.Button(row, text="LAB", command=lambda: self._switch_mode("LAB"))
        self._btn_lab_mode.pack(side="left", expand=True, fill="x", padx=(4, 0))

        display_card = styles.card(main, "OUTPUT")
        row = ttk.Frame(display_card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Monitor", style="Card.TLabel").pack(side="left")
        self._display_combo = ttk.Combobox(
            row,
            textvariable=self._selected_display,
            values=[d["label"] for d in self.detected_displays],
            state="readonly",
            width=31,
        )
        self._display_combo.pack(side="left", padx=8, fill="x", expand=True)
        ttk.Checkbutton(row, text="Fullscreen", variable=self._fullscreen).pack(side="left")
        ttk.Button(row, text="Apply", command=self._apply_display).pack(side="left", padx=(8, 0))
        ttk.Label(
            display_card,
            text="Production V40 QR canvas: 1000 px • 925 px QR including quiet zone",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        self._panel_host = ttk.Frame(main)
        self._panel_host.pack(fill="x")
        self._transfer_panel = ttk.Frame(self._panel_host)
        self._lab_panel = ttk.Frame(self._panel_host)
        self._build_transfer_panel()
        self._build_lab_panel()
        self._transfer_panel.pack(fill="x")

        action = ttk.Frame(main)
        action.pack(fill="x", pady=(8, 4))
        self._start_btn = ttk.Button(action, text="START TRANSFER", style="Accent.TButton", command=self._start_current)
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._stop_btn = ttk.Button(action, text="STOP", command=self._stop_current)
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        ttk.Label(main, textvariable=self._status, foreground=styles.MUTED).pack(anchor="w", pady=(6, 0))

    def _build_transfer_panel(self) -> None:
        card = styles.card(self._transfer_panel, "SEND FILE")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Mode", style="Card.TLabel", width=7).pack(side="left")
        mode_combo = ttk.Combobox(
            row,
            textvariable=self._transfer_mode,
            values=self.transfer_ctrl.mode_options,
            state="readonly",
        )
        mode_combo.pack(side="left", fill="x", expand=True)
        mode_combo.bind("<<ComboboxSelected>>", self._transfer_mode_changed)
        ttk.Label(
            card,
            textvariable=self._transfer_mode_note,
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(4, 4))
        ttk.Label(
            card,
            text="Android stays on Auto 30 FPS and detects the selected V40 mode automatically.",
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            card,
            text="Frames repeat automatically in shuffled later passes so missed camera frames can self-heal.",
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(card, text="SELECT FILE", command=self._select_file).pack(fill="x")
        ttk.Label(card, textvariable=self._file_label, style="Card.TLabel").pack(anchor="w", pady=(8, 1))
        ttk.Label(card, textvariable=self._file_meta, style="Muted.TLabel", wraplength=530).pack(anchor="w")
        ttk.Label(card, textvariable=self._transfer_progress, style="Muted.TLabel").pack(anchor="w", pady=(5, 0))

    def _build_lab_panel(self) -> None:
        card = styles.card(self._lab_panel, "PHYSICAL PHY LAB")
        ttk.Label(
            card,
            text="Separate from production transfer. Use this only for campaigns and diagnostics.",
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Preset", style="Card.TLabel", width=9).pack(side="left")
        preset = ttk.Combobox(row, textvariable=self._lab_preset, values=self.campaign_ctrl.PRESETS, state="readonly")
        preset.pack(side="left", fill="x", expand=True)
        preset.bind("<<ComboboxSelected>>", self._lab_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Profile", style="Card.TLabel", width=9).pack(side="left")
        profile = ttk.Combobox(
            row,
            textvariable=self._lab_profile,
            values=self.campaign_ctrl.available_profiles,
            state="readonly",
        )
        profile.pack(side="left", fill="x", expand=True)
        profile.bind("<<ComboboxSelected>>", self._lab_changed)

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Dwell", style="Card.TLabel", width=9).pack(side="left")
        dwell = ttk.Combobox(
            row,
            textvariable=self._lab_dwell,
            values=[str(v) for v in self.campaign_ctrl.DWELL_OPTIONS],
            state="readonly",
            width=8,
        )
        dwell.pack(side="left")
        dwell.bind("<<ComboboxSelected>>", self._lab_changed)
        ttk.Label(row, text="Frames", style="Card.TLabel").pack(side="left", padx=(16, 6))
        frames = ttk.Spinbox(row, from_=1, to=256, textvariable=self._lab_frames, width=7, command=self._lab_changed)
        frames.pack(side="left")
        frames.bind("<FocusOut>", self._lab_changed)
        frames.bind("<Return>", self._lab_changed)
        ttk.Label(card, textvariable=self._lab_progress, style="Muted.TLabel", wraplength=530).pack(anchor="w", pady=(7, 0))

    # -------------------------------------------------------------- display

    def _selected_display_index(self) -> int:
        label = self._selected_display.get()
        item = next((d for d in self.detected_displays if d["label"] == label), self.detected_displays[0])
        return int(item["index"])

    def _apply_display(self) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            self._status.set("Stop the lab campaign before changing output")
            return
        try:
            self.display.setup_display(self._selected_display_index(), self._fullscreen.get(), MARKER_SIZE)
            self.display.render_standby()
            self._status.set(f"Output ready • {MARKER_SIZE}px canvas")
        except Exception as exc:
            self._status.set(f"Output error: {exc}")

    # ------------------------------------------------------------- transfer

    def _transfer_mode_changed(self, _event=None) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        try:
            self.transfer_ctrl.set_mode(self._transfer_mode.get())
        except Exception as exc:
            self._status.set(f"Transfer mode error: {exc}")
            self._transfer_mode.set(self.transfer_ctrl.mode)
            return
        self._transfer_mode_note.set(self.transfer_ctrl.mode_note)
        self._refresh_transfer_file_details()
        self._status.set(
            f"Mode ready • {self.transfer_ctrl.profile.label} • {self.transfer_ctrl.target_fps:.0f} FPS"
        )

    def _refresh_transfer_file_details(self) -> None:
        if not self.transfer_ctrl.has_file:
            return
        self._file_label.set(self.transfer_ctrl.filename or "Selected file")
        self._file_meta.set(
            f"{self._format_bytes(self.transfer_ctrl.file_size)} • {self.transfer_ctrl.mime_type} • "
            f"{self.transfer_ctrl.total_frames:,} optical frames • CRC {self.transfer_ctrl.file_crc32:08X}"
        )
        tested = " • best tested physical mode" if self.transfer_ctrl.mode == self.transfer_ctrl.DEFAULT_MODE else ""
        self._transfer_progress.set(
            f"Ready • nominal payload {self.transfer_ctrl.nominal_payload_kib_s:.1f} KiB/s{tested}"
        )

    def _select_file(self) -> None:
        path = filedialog.askopenfilename(title="Select a file to send")
        if not path:
            return
        self._stop_transfer()
        try:
            self.transfer_ctrl.select_file(path)
        except Exception as exc:
            messagebox.showerror("SuperQR", str(exc))
            return
        self._refresh_transfer_file_details()
        self._status.set("File prepared. Start RECEIVE on the phone, then START TRANSFER here.")

    def _start_transfer(self) -> None:
        if not self.transfer_ctrl.has_file:
            self._select_file()
            if not self.transfer_ctrl.has_file:
                return
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            self._status.set("Stop the lab campaign first")
            return
        if self.display.screen is None:
            self._apply_display()
        if not self.transfer_ctrl.start_presenting():
            return
        assert self.transfer_ctrl.session_id is not None
        self.transfer_presenter.start_stream(
            self.transfer_ctrl.get_frame_bytes,
            self.transfer_ctrl.total_frames,
            self.transfer_ctrl.session_id,
            self.transfer_ctrl.profile,
        )
        self._transfer_waiting_for_first = True
        self._transfer_progress.set(f"Preparing {self.transfer_ctrl.profile.label} stream…")
        self._status.set("Encoding ahead…")
        self._schedule_transfer_tick(1)

    def _stop_transfer(self) -> None:
        if self._transfer_after_id is not None:
            try:
                self.root.after_cancel(self._transfer_after_id)
            except Exception:
                pass
            self._transfer_after_id = None
        self.transfer_clock.stop()
        self.transfer_presenter.stop_stream()
        self.transfer_ctrl.stop_presenting()
        self._transfer_waiting_for_first = False
        if self.display.screen is not None:
            self.display.render_standby()
        if self.transfer_ctrl.has_file:
            self._transfer_progress.set("Stopped • press START TRANSFER to send again")
        self._status.set("Ready")

    def _schedule_transfer_tick(self, delay_ms: int) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._transfer_after_id = self.root.after(max(1, delay_ms), self._transfer_tick)

    def _transfer_tick(self) -> None:
        self._transfer_after_id = None
        if self.transfer_ctrl.lifecycle != TransferLifecycle.PRESENTING:
            return
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)):
                self._stop_transfer()
                return

        producer_error = self.transfer_presenter.producer_error
        if producer_error:
            self._status.set(f"Transfer encoder error: {producer_error}")
            self._stop_transfer()
            return

        if self._transfer_waiting_for_first:
            frame = self.transfer_presenter.pop_ready()
            if frame is None:
                self._schedule_transfer_tick(5)
                return
            self._present_transfer_frame(frame)
            self._transfer_waiting_for_first = False
            self.transfer_clock.start(time.perf_counter(), self.transfer_ctrl.interval_ms)
            self._schedule_transfer_tick(self.transfer_clock.delay_ms(time.perf_counter(), max_delay_ms=20))
            return

        now = time.perf_counter()
        if self.transfer_clock.due(now):
            frame = self.transfer_presenter.pop_ready()
            if frame is None:
                self._schedule_transfer_tick(3)
                return
            self._present_transfer_frame(frame)
            self.transfer_clock.mark_presented(time.perf_counter(), self.transfer_ctrl.interval_ms)

        self._schedule_transfer_tick(self.transfer_clock.delay_ms(time.perf_counter(), max_delay_ms=20))

    def _present_transfer_frame(self, frame: PreparedQrFrame) -> None:
        self._last_transfer_timing = self.transfer_presenter.render_prepared(frame, MARKER_SIZE)
        self.transfer_ctrl.note_presented(frame.frame_id, frame.loop_index)
        total = self.transfer_ctrl.total_frames
        self._transfer_progress.set(
            f"Sending • loop {frame.loop_index + 1} • frame {frame.frame_id + 1:,}/{total:,} • "
            f"{self.transfer_ctrl.target_fps:.0f} FPS • encoder buffer {self.transfer_presenter.ready_count}"
        )
        self._status.set(
            f"{self.transfer_ctrl.profile.label} live • render {self._last_transfer_timing.get('render_ms', 0.0):.1f} ms • "
            "receiver decides completion"
        )

    # ------------------------------------------------------------------ lab

    def _lab_changed(self, _event=None) -> None:
        try:
            self.campaign_ctrl.set_preset(self._lab_preset.get())
            self.campaign_ctrl.set_profile(self._lab_profile.get())
            self.campaign_ctrl.set_dwell(float(self._lab_dwell.get()))
            self.campaign_ctrl.set_frames(int(self._lab_frames.get()))
            self._lab_progress.set(f"{self.campaign_ctrl.run_count} run(s) prepared")
        except Exception as exc:
            self._lab_progress.set(str(exc))

    def _start_lab(self) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            return
        self._lab_changed()
        self.campaign_ctrl.set_display(self._selected_display_index(), self._fullscreen.get(), MARKER_SIZE)
        self.display.close()
        try:
            if self.campaign_ctrl.start():
                self._lab_progress.set("Starting campaign…")
                self._status.set("Lab owns the optical display")
            else:
                self._apply_display()
        except Exception as exc:
            self._lab_progress.set(f"Campaign error: {exc}")
            self._apply_display()

    def _stop_lab(self) -> None:
        self.campaign_ctrl.request_stop()
        self._lab_progress.set("Stopping campaign…")

    def _poll_lab(self) -> None:
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            self.campaign_ctrl.poll()
            snap = self.campaign_ctrl.snapshot()
            if snap is not None:
                self._lab_progress.set(
                    f"{snap.state.value} • run {snap.run_number}/{snap.run_total} • "
                    f"{snap.profile} • frame {snap.frame_index + 1}/{snap.frame_count} • "
                    f"logical {snap.logical_fps:.1f} FPS"
                )
            if self.campaign_ctrl.needs_display_reclaim:
                final = self.campaign_ctrl.reclaim_display()
                self._export_campaign()
                self._apply_display()
                if final is not None and final.error:
                    self._lab_progress.set(f"Campaign error: {final.error}")
                else:
                    self._lab_progress.set("Campaign complete • sender JSON exported")

    def _export_campaign(self) -> None:
        payload = self.campaign_ctrl.last_export_payload()
        if payload is None:
            return
        profile = payload.get("current", {}).get("profile", "campaign")
        filename = f"campaign_sender_{profile}_{int(time.time())}.json"
        path = os.path.abspath(filename)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            self._status.set(f"Lab export: {path}")
        except Exception as exc:
            self._status.set(f"Could not export lab JSON: {exc}")

    # -------------------------------------------------------------- actions

    def _switch_mode(self, mode: str) -> None:
        if mode == self._mode.get():
            return
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            self._status.set("Stop the running lab campaign before switching")
            return
        self._mode.set(mode)
        self._transfer_panel.pack_forget()
        self._lab_panel.pack_forget()
        if mode == "TRANSFER":
            self._transfer_panel.pack(fill="x")
            self._btn_transfer_mode.configure(style="Accent.TButton")
            self._btn_lab_mode.configure(style="TButton")
            self._start_btn.configure(text="START TRANSFER")
        else:
            self._lab_panel.pack(fill="x")
            self._btn_transfer_mode.configure(style="TButton")
            self._btn_lab_mode.configure(style="Accent.TButton")
            self._start_btn.configure(text="START TEST")

    def _start_current(self) -> None:
        if self._mode.get() == "TRANSFER":
            self._start_transfer()
        else:
            self._start_lab()

    def _stop_current(self) -> None:
        if self._mode.get() == "TRANSFER":
            self._stop_transfer()
        else:
            self._stop_lab()

    def _poll(self) -> None:
        self._poll_lab()
        if self.root.winfo_exists():
            self.root.after(50, self._poll)

    @staticmethod
    def _format_bytes(value: int) -> str:
        if value >= 1024 ** 3:
            return f"{value / (1024 ** 3):.2f} GiB"
        if value >= 1024 ** 2:
            return f"{value / (1024 ** 2):.2f} MiB"
        if value >= 1024:
            return f"{value / 1024:.1f} KiB"
        return f"{value} B"

    def close(self) -> None:
        self._stop_transfer()
        if self.campaign_ctrl.lifecycle != CampaignLifecycle.IDLE:
            self.campaign_ctrl.request_stop()
        self.transfer_ctrl.close()
        self.display.close()
        try:
            pygame.quit()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
