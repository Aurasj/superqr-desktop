"""Clean SuperQR desktop UI: production transfer first, PHY lab separate."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import pygame
from PIL import Image, ImageTk

from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.presentation.transfer import PreparedQrFrame, TransferPresenter
from superqr_desktop.receive.camera import ProductionCameraReceiver
from superqr_desktop.transfer.controller import TransferController, TransferLifecycle
from superqr_desktop.transfer.timing import TransferCadenceClock
from superqr_desktop.ui import styles


MARKER_SIZE = 1000


class MainWindow:
    """Production file sender plus an isolated physical-test lab."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SuperQR")
        self.root.geometry("700x850")
        self.root.minsize(620, 720)
        self.root.configure(bg=styles.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        styles.setup_styles(self.root)

        pygame.init()
        DisplayController._apply_event_filter()
        self.display = DisplayController()
        self.detected_displays = self.display.detect_displays()
        self.transfer_ctrl = TransferController()
        self.transfer_presenter = TransferPresenter(self.display)
        self.transfer_clock = TransferCadenceClock()
        self.receive_ctrl = ProductionCameraReceiver()

        self._mode = tk.StringVar(value="SEND")
        self._transfer_after_id: str | None = None
        self._transfer_waiting_for_first = False
        self._last_transfer_timing: dict[str, float] = {}
        self._send_started_at = 0.0
        self._send_presented = 0
        self._send_first_pass: set[int] = set()

        labels = [d["label"] for d in self.detected_displays]
        self._selected_display = tk.StringVar(value=labels[0] if labels else "Display 1")
        self._fullscreen = tk.BooleanVar(value=False)

        self._transfer_mode = tk.StringVar(value=self.transfer_ctrl.mode)
        self._transfer_mode_note = tk.StringVar(value=self.transfer_ctrl.mode_note)
        self._file_label = tk.StringVar(value="No file selected")
        self._file_meta = tk.StringVar(value="Choose any file: photo, audio, video, archive, document…")
        self._transfer_progress = tk.StringVar(value="Ready")
        self._status = tk.StringVar(value="Ready")

        self._camera_index = tk.StringVar(value="0")
        self._receive_progress = tk.DoubleVar(value=0.0)
        self._receive_summary = tk.StringVar(value="Camera idle")
        self._receive_diagnostics = tk.StringVar(value="Start the camera, then show the Desktop sender QR.")
        self._receive_preview_image = None
        self._receive_artifact_shown = None
        self._share_link: Path | None = None
        self._video_capture = None
        self._video_after_id: str | None = None

        self._lab_progress = tk.StringVar(value="ColorGrid8 ready")
        self._grid8_grid = tk.StringVar(value="336x288")
        self._grid8_fps = tk.StringVar(value="60")
        self._grid8_file: Path | None = None
        self._grid8_file_label = tk.StringVar(value="No LAB transfer file selected")
        self._grid8_process: subprocess.Popen[str] | None = None
        self._grid8_output: queue.Queue[str] = queue.Queue()

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
        self._btn_send_mode = ttk.Button(row, text="SEND", style="Accent.TButton", command=lambda: self._switch_mode("SEND"))
        self._btn_send_mode.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._btn_receive_mode = ttk.Button(row, text="RECEIVE", command=lambda: self._switch_mode("RECEIVE"))
        self._btn_receive_mode.pack(side="left", expand=True, fill="x", padx=3)
        self._btn_lab_mode = ttk.Button(row, text="LAB / EXPERIMENTS", command=lambda: self._switch_mode("LAB"))
        self._btn_lab_mode.pack(side="left", expand=True, fill="x", padx=(3, 0))

        display_card = styles.card(main, "OUTPUT — WINDOWED BY DEFAULT")
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
        self._receive_panel = ttk.Frame(self._panel_host)
        self._lab_panel = ttk.Frame(self._panel_host)
        self._build_transfer_panel()
        self._build_receive_panel()
        self._build_lab_panel()
        self._transfer_panel.pack(fill="x")

        action = ttk.Frame(main)
        action.pack(fill="x", pady=(8, 4))
        self._start_btn = ttk.Button(action, text="START TRANSFER", style="Accent.TButton", command=self._start_current)
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._stop_btn = ttk.Button(action, text="STOP", command=self._stop_current)
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        ttk.Label(main, textvariable=self._status, foreground=styles.MUTED).pack(anchor="w", pady=(6, 0))

    def _build_receive_panel(self) -> None:
        card = styles.card(self._receive_panel, "RECEIVE FILE")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Camera", style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row, from_=0, to=9, textvariable=self._camera_index, width=5).pack(side="left", padx=(8, 12))
        ttk.Label(
            row,
            text="Verified files stay temporary until you choose Save, Share/Open, or Discard.",
            style="Muted.TLabel",
        ).pack(side="left", fill="x", expand=True)
        ttk.Progressbar(card, variable=self._receive_progress, maximum=100.0).pack(fill="x", pady=(9, 5))
        ttk.Label(card, textvariable=self._receive_summary, style="Card.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            textvariable=self._receive_diagnostics,
            style="Muted.TLabel",
            wraplength=630,
        ).pack(anchor="w", pady=(3, 7))
        self._camera_preview = ttk.Label(card, anchor="center")
        self._camera_preview.pack(fill="x")
        self._received_preview_host = ttk.Frame(card, style="Card.TFrame")
        self._received_preview_host.pack(fill="both", expand=True, pady=(7, 0))

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
        card = styles.card(self._lab_panel, "LAB / EXPERIMENTS")
        ttk.Label(
            card,
            text="PROMISING · COLORGRID8",
            style="Card.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            card,
            text="High-speed experimental file transport. Production V40 remains separate and unchanged.",
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Grid", style="Card.TLabel", width=9).pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self._grid8_grid,
            values=("240x216", "336x288", "384x336"),
            state="readonly",
            width=13,
        ).pack(side="left")
        ttk.Label(row, text="FPS", style="Card.TLabel").pack(side="left", padx=(16, 6))
        ttk.Combobox(row, textvariable=self._grid8_fps, values=("30", "45", "60", "90"), state="readonly", width=7).pack(side="left")
        ttk.Button(card, text="SELECT FILE FOR HIGH-SPEED LAB", command=self._select_grid8_file).pack(fill="x", pady=(7, 0))
        ttk.Label(card, textvariable=self._grid8_file_label, style="Card.TLabel", wraplength=620).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            card,
            text="Frames repeat continuously with 8+1 XOR recovery. Leave Fullscreen off for the fixed phone setup. Channel budgets are not measured speeds.",
            style="Muted.TLabel",
            wraplength=620,
        ).pack(anchor="w", pady=(5, 0))
        ttk.Label(card, textvariable=self._lab_progress, style="Muted.TLabel", wraplength=620).pack(anchor="w", pady=(7, 0))

    # -------------------------------------------------------------- display

    def _selected_display_index(self) -> int:
        label = self._selected_display.get()
        item = next((d for d in self.detected_displays if d["label"] == label), self.detected_displays[0])
        return int(item["index"])

    def _apply_display(self) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self._grid8_process is not None:
            self._status.set("Stop ColorGrid8 before changing output")
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
        self._send_started_at = time.perf_counter()
        self._send_presented = 0
        self._send_first_pass.clear()
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
        total = self.transfer_ctrl.total_frames
        self._send_presented += 1
        if frame.loop_index == 0:
            self._send_first_pass.add(frame.frame_id)
        elapsed = max(1e-9, time.perf_counter() - self._send_started_at)
        measured_fps = self._send_presented / elapsed
        presented_kib_s = self._send_presented * self.transfer_ctrl.profile.payload_size / 1024.0 / elapsed
        remaining = max(0, total - len(self._send_first_pass))
        eta = remaining / measured_fps if measured_fps > 0 else 0.0
        self._transfer_progress.set(
            f"Sending • first pass {len(self._send_first_pass):,}/{total:,} • carousel {frame.loop_index + 1} • "
            f"measured {measured_fps:.1f} FPS / {presented_kib_s:.1f} KiB/s • ETA {eta:.1f}s"
        )
        self._status.set(
            f"{self.transfer_ctrl.profile.label} live • render {self._last_transfer_timing.get('render_ms', 0.0):.1f} ms • "
            f"encoder buffer {self.transfer_presenter.ready_count} • receiver decides completion"
        )

    # -------------------------------------------------------------- receive

    def _start_receive(self) -> None:
        if self.receive_ctrl.artifact is not None:
            self._status.set("Save, Share/Open, or Discard the verified file first")
            return
        try:
            camera_index = int(self._camera_index.get())
        except ValueError:
            self._status.set("Camera index must be a number")
            return
        current_progress = self.receive_ctrl.accumulator.progress
        if camera_index != self.receive_ctrl.camera_index:
            if current_progress.total_frames:
                camera_index = self.receive_ctrl.camera_index
                self._camera_index.set(str(camera_index))
                self._status.set("Partial transfer retained; continuing on its original camera")
            else:
                self.receive_ctrl.discard()
                self.receive_ctrl = ProductionCameraReceiver(camera_index=camera_index)
                self._receive_artifact_shown = None
                self._receive_progress.set(0.0)
        self._receive_summary.set("Opening camera…")
        self._receive_diagnostics.set(
            "Resuming partial carousel…" if current_progress.total_frames else "Searching for a production V40 QR frame"
        )
        self.receive_ctrl.start()
        self._status.set("Production receiver running")

    def _stop_receive(self) -> None:
        self.receive_ctrl.stop()
        if self.receive_ctrl.artifact is None:
            self._receive_summary.set("Camera stopped • partial frames retained until Restart/Discard")
        self._status.set("Receiver stopped")

    def _poll_receive(self) -> None:
        snapshot = self.receive_ctrl.snapshot()
        self._receive_progress.set(snapshot.progress * 100.0)
        total_text = f"/{snapshot.total_frames:,}" if snapshot.total_frames else ""
        self._receive_summary.set(
            f"{snapshot.state} • {snapshot.unique_frames:,}{total_text} unique • "
            f"{snapshot.duplicate_frames:,} duplicate • {snapshot.real_payload_kib_s:.1f} KiB/s"
        )
        self._receive_diagnostics.set(
            f"camera {snapshot.camera_fps:.1f} FPS • decode p50/p95 "
            f"{snapshot.decode_p50_ms:.1f}/{snapshot.decode_p95_ms:.1f} ms • "
            f"decoded {snapshot.decoded_frames:,}/{snapshot.camera_frames:,} camera frames"
            + (f" • {snapshot.failure}" if snapshot.failure else "")
        )
        preview = self.receive_ctrl.preview()
        if preview is not None and self.receive_ctrl.artifact is None:
            rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            image.thumbnail((620, 260))
            photo = ImageTk.PhotoImage(image)
            self._receive_preview_image = photo
            self._camera_preview.configure(image=photo)
        artifact = self.receive_ctrl.artifact
        if artifact is not None and artifact is not self._receive_artifact_shown:
            self._receive_artifact_shown = artifact
            self._camera_preview.configure(image="")
            self._show_received_artifact(artifact)

    def _clear_received_preview(self) -> None:
        self._stop_media_preview()
        for child in self._received_preview_host.winfo_children():
            child.destroy()
        self._receive_preview_image = None

    def _show_received_artifact(self, artifact) -> None:
        self._clear_received_preview()
        ttk.Label(
            self._received_preview_host,
            text=f"VERIFIED • {artifact.filename} • {self._format_bytes(artifact.file_size)}",
            style="Card.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self._received_preview_host,
            text=f"{artifact.mime_type} • SHA-256 {artifact.sha256}",
            style="Muted.TLabel",
            wraplength=620,
        ).pack(anchor="w", pady=(2, 6))

        suffix = Path(artifact.filename).suffix.lower()
        is_text = artifact.mime_type.startswith("text/") or suffix in {
            ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".log", ".py", ".kt"
        }
        is_image = artifact.mime_type.startswith("image/")
        if is_text:
            with artifact.path.open("rb") as handle:
                content = handle.read(256 * 1024)
            view = tk.Text(self._received_preview_host, height=9, wrap="word")
            view.insert("1.0", content.decode("utf-8", errors="replace"))
            view.configure(state="disabled")
            view.pack(fill="both", expand=True)
            if artifact.file_size > len(content):
                ttk.Label(
                    self._received_preview_host,
                    text="Preview limited to the first 256 KiB; the full file remains on disk.",
                    style="Muted.TLabel",
                ).pack(anchor="w")
        elif is_image and artifact.file_size <= 64 * 1024 * 1024:
            try:
                with Image.open(artifact.path) as source:
                    width, height = source.size
                    if width * height > 20_000_000:
                        raise ValueError(f"image is {width:,}×{height:,}; inline preview intentionally bounded")
                    source.thumbnail((620, 300))
                    preview_image = source.convert("RGB").copy()
                photo = ImageTk.PhotoImage(preview_image)
                self._receive_preview_image = photo
                ttk.Label(self._received_preview_host, image=photo).pack()
            except Exception as exc:
                ttk.Label(
                    self._received_preview_host,
                    text=f"Image metadata is verified; inline preview unavailable: {exc}",
                    style="Muted.TLabel",
                    wraplength=620,
                ).pack(anchor="w")
        elif artifact.mime_type.startswith("audio/") or artifact.mime_type.startswith("video/"):
            media = ttk.Frame(self._received_preview_host, style="Card.TFrame")
            media.pack(fill="x")
            ttk.Button(media, text="PLAY PREVIEW", command=self._play_media_preview).pack(side="left")
            ttk.Button(media, text="STOP PREVIEW", command=self._stop_media_preview).pack(side="left", padx=(7, 0))
            ttk.Label(
                self._received_preview_host,
                text="Playback streams from the verified temporary file; it is not loaded fully into memory.",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(4, 0))
        else:
            ttk.Label(
                self._received_preview_host,
                text="Binary/archive/document preview: verified filename, MIME type, size, CRC32 and SHA-256 are shown above.",
                style="Muted.TLabel",
                wraplength=620,
            ).pack(anchor="w")

        actions = ttk.Frame(self._received_preview_host, style="Card.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="SAVE AS…", style="Accent.TButton", command=self._save_received).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ttk.Button(actions, text="SHARE / OPEN", command=self._share_received).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(actions, text="DISCARD", command=self._discard_received).pack(side="left", expand=True, fill="x", padx=(3, 0))

    def _save_received(self) -> None:
        artifact = self.receive_ctrl.artifact
        if artifact is None:
            return
        path = filedialog.asksaveasfilename(title="Save verified file", initialfile=artifact.filename)
        if not path:
            return
        try:
            artifact.save_to(path)
            self._status.set(f"Saved verified file: {path}")
        except Exception as exc:
            messagebox.showerror("SuperQR", f"Could not save file: {exc}")

    def _share_received(self) -> None:
        artifact = self.receive_ctrl.artifact
        if artifact is None:
            return
        self._cleanup_share_link()
        directory = Path(tempfile.mkdtemp(prefix="superqr-share-"))
        link = directory / artifact.filename
        try:
            try:
                os.link(artifact.path, link)
            except OSError:
                artifact.save_to(link)
            self._share_link = link
            os.startfile(link)  # type: ignore[attr-defined]
            self._status.set("Opened the verified temporary file for preview/sharing")
        except Exception as exc:
            self._cleanup_share_link()
            messagebox.showerror("SuperQR", f"Could not open file: {exc}")

    def _discard_received(self) -> None:
        self._cleanup_share_link()
        self._clear_received_preview()
        self.receive_ctrl.discard()
        self._receive_artifact_shown = None
        self._receive_progress.set(0.0)
        self._receive_summary.set("Discarded • ready for another file")
        self._receive_diagnostics.set("Start the camera when ready")
        self._status.set("Verified temporary file discarded")

    def _cleanup_share_link(self) -> None:
        if self._share_link is not None:
            parent = self._share_link.parent
            self._share_link.unlink(missing_ok=True)
            try:
                parent.rmdir()
            except OSError:
                pass
            self._share_link = None

    def _play_media_preview(self) -> None:
        artifact = self.receive_ctrl.artifact
        if artifact is None:
            return
        self._stop_media_preview()
        if artifact.mime_type.startswith("audio/"):
            try:
                pygame.mixer.music.load(str(artifact.path))
                pygame.mixer.music.play()
                self._status.set("Playing received audio preview")
            except Exception as exc:
                self._status.set(f"Audio preview unavailable: {exc}")
            return
        self._video_capture = cv2.VideoCapture(str(artifact.path))
        if not self._video_capture.isOpened():
            self._video_capture.release()
            self._video_capture = None
            self._status.set("Video preview codec is unavailable")
            return
        self._status.set("Playing received video preview")
        self._video_preview_tick()

    def _video_preview_tick(self) -> None:
        if self._video_capture is None:
            return
        ok, frame = self._video_capture.read()
        if not ok:
            self._stop_media_preview()
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((620, 300))
        photo = ImageTk.PhotoImage(image)
        self._receive_preview_image = photo
        self._camera_preview.configure(image=photo)
        fps = self._video_capture.get(cv2.CAP_PROP_FPS)
        delay = max(15, int(1000.0 / fps)) if fps > 0 else 33
        self._video_after_id = self.root.after(delay, self._video_preview_tick)

    def _stop_media_preview(self) -> None:
        pygame.mixer.music.stop()
        if self._video_after_id is not None:
            try:
                self.root.after_cancel(self._video_after_id)
            except Exception:
                pass
            self._video_after_id = None
        if self._video_capture is not None:
            self._video_capture.release()
            self._video_capture = None
        if hasattr(self, "_camera_preview"):
            self._camera_preview.configure(image="")

    # ------------------------------------------------------------------ lab

    def _select_grid8_file(self) -> None:
        selected = filedialog.askopenfilename(title="Select file for ColorGrid8 LAB")
        if not selected:
            return
        self._grid8_file = Path(selected).resolve()
        self._grid8_file_label.set(
            f"{self._grid8_file.name} • {self._format_bytes(self._grid8_file.stat().st_size)}"
        )
        self._lab_progress.set("ColorGrid8 high-speed transfer ready")

    def _start_lab(self) -> None:
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self._grid8_process is not None:
            return
        self._start_grid8()

    def _stop_lab(self) -> None:
        if self._grid8_process is not None:
            process = self._grid8_process
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
            self._grid8_process = None
            self._lab_progress.set("Grid8 stopped")
            self._apply_display()
            return
        self._lab_progress.set("ColorGrid8 is not running")

    def _start_grid8(self) -> None:
        if self._grid8_file is None or not self._grid8_file.is_file():
            self._lab_progress.set("Select a file for the ColorGrid8 LAB transfer")
            return
        self.display.close()
        command = [
            sys.executable,
            "-u",
            "-m",
            "superqr_desktop.lab.colorgrid8_lab_runner",
            "--grid",
            self._grid8_grid.get(),
            "--fps",
            self._grid8_fps.get(),
            "--frames",
            "0",
            "--file",
            str(self._grid8_file),
            "--display",
            str(self._selected_display_index()),
            "--calibration-seconds",
            "1.0",
        ]
        if not self._fullscreen.get():
            command.append("--windowed")
        try:
            self._grid8_process = subprocess.Popen(
                command,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self._grid8_process.stdout is not None
            threading.Thread(
                target=self._read_grid8_output,
                args=(self._grid8_process.stdout,),
                name="superqr-grid8-ui-output",
                daemon=True,
            ).start()
            mode = "fullscreen" if self._fullscreen.get() else "windowed"
            self._lab_progress.set(
                f"Grid8 sending {self._grid8_file.name} • {self._grid8_grid.get()} • {self._grid8_fps.get()} FPS • {mode}"
            )
            self._status.set("Grid8 LAB owns the optical display")
        except Exception as exc:
            self._grid8_process = None
            self._lab_progress.set(f"Grid8 start error: {exc}")
            self._apply_display()

    def _read_grid8_output(self, stream) -> None:
        try:
            for line in stream:
                if line.strip():
                    self._grid8_output.put(line.strip())
        finally:
            stream.close()

    def _poll_lab(self) -> None:
        latest_grid8 = None
        while True:
            try:
                latest_grid8 = self._grid8_output.get_nowait()
            except queue.Empty:
                break
        if latest_grid8 is not None:
            self._lab_progress.set(latest_grid8)
        if self._grid8_process is not None and self._grid8_process.poll() is not None:
            code = self._grid8_process.returncode
            self._grid8_process = None
            self._apply_display()
            if code == 0:
                self._lab_progress.set("Grid8 complete")
            else:
                self._lab_progress.set(f"Grid8 exited with code {code}")
    # -------------------------------------------------------------- actions

    def _switch_mode(self, mode: str) -> None:
        if mode == self._mode.get():
            return
        if self.transfer_ctrl.lifecycle == TransferLifecycle.PRESENTING:
            self._stop_transfer()
        if self._grid8_process is not None:
            self._status.set("Stop the running Grid8 experiment before switching")
            return
        if self._mode.get() == "RECEIVE":
            self._stop_receive()
        self._mode.set(mode)
        self._transfer_panel.pack_forget()
        self._receive_panel.pack_forget()
        self._lab_panel.pack_forget()
        self._btn_send_mode.configure(style="TButton")
        self._btn_receive_mode.configure(style="TButton")
        self._btn_lab_mode.configure(style="TButton")
        if mode == "SEND":
            self._transfer_panel.pack(fill="x")
            self._btn_send_mode.configure(style="Accent.TButton")
            self._start_btn.configure(text="START TRANSFER")
        elif mode == "RECEIVE":
            self._receive_panel.pack(fill="both", expand=True)
            self._btn_receive_mode.configure(style="Accent.TButton")
            self._start_btn.configure(text="START CAMERA")
        else:
            self._lab_panel.pack(fill="x")
            self._btn_lab_mode.configure(style="Accent.TButton")
            self._start_btn.configure(text="START LAB TRANSFER")

    def _start_current(self) -> None:
        if self._mode.get() == "SEND":
            self._start_transfer()
        elif self._mode.get() == "RECEIVE":
            self._start_receive()
        else:
            self._start_lab()

    def _stop_current(self) -> None:
        if self._mode.get() == "SEND":
            self._stop_transfer()
        elif self._mode.get() == "RECEIVE":
            self._stop_receive()
        else:
            self._stop_lab()

    def _poll(self) -> None:
        self._poll_lab()
        if self._mode.get() == "RECEIVE":
            self._poll_receive()
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
        self.receive_ctrl.stop()
        self.receive_ctrl.discard()
        self._cleanup_share_link()
        if self._grid8_process is not None:
            self._stop_lab()
        self.transfer_ctrl.close()
        self.display.close()
        try:
            pygame.quit()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
