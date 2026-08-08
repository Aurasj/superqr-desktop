import os
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.display import CANONICAL_SIZE, DisplayController
from superqr_desktop.v7.sender import V7SenderSession
from superqr_desktop.v7.transport import GRID_SIZE, PAYLOAD_SIZE
from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer

SIZE_PRESETS = [1000, 900, 800, 700, 600, 500, 400]
DEBUG_PATTERNS = [
    ("Random Grid", "deterministic_random"),
    ("Checkerboard", "checkerboard"),
    ("All Black", "black"),
    ("All White", "white"),
]


class ControlApp:
    """Single SuperQR Desktop application.

    V7 is the active transfer protocol. The physically validated V6 carrier and
    debug patterns remain available as diagnostics, but there is no V6/V7
    product-mode switch.
    """

    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash
        self.last_error = "None"
        self.renderer_status = "READY"

        pygame.init()
        self.display_controller = DisplayController(self.contract)
        self.detected_displays = self.display_controller.detect_displays()
        self.sender = V7SenderSession()
        self.sender_last_tick = 0.0
        self.v7_renderer: LabRenderer | None = None

        self.root = tk.Tk()
        self.root.title("SuperQR")
        self.root.geometry("500x790")
        self.root.minsize(470, 720)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.bg_color = "#181825"
        self.panel_bg = "#1e1e2e"
        self.panel_border = "#313244"
        self.accent_color = "#89b4fa"
        self.text_primary = "#cdd6f4"
        self.text_secondary = "#a6adc8"
        self.status_ok_color = "#a6e3a1"
        self.status_err_color = "#f38ba8"
        self.root.configure(bg=self.bg_color)

        self.style.configure(".", background=self.bg_color, foreground=self.text_primary, font=("Segoe UI", 9))
        self.style.configure("TLabelframe", background=self.panel_bg, bordercolor=self.panel_border, relief="solid", borderwidth=1)
        self.style.configure("TLabelframe.Label", background=self.panel_bg, foreground=self.accent_color, font=("Segoe UI", 9, "bold"))
        self.style.configure("TLabel", background=self.panel_bg, foreground=self.text_primary)
        self.style.configure("Header.TLabel", background=self.bg_color, foreground=self.text_primary, font=("Segoe UI", 13, "bold"))
        self.style.configure("SubHeader.TLabel", background=self.bg_color, foreground=self.text_secondary, font=("Segoe UI", 8))
        self.style.configure("TCombobox", fieldbackground="#313244", background="#313244", foreground=self.text_primary, selectbackground="#45475a")
        self.style.configure("TRadiobutton", background=self.panel_bg, foreground=self.text_primary)
        self.style.configure("TCheckbutton", background=self.panel_bg, foreground=self.text_primary)
        self.style.configure("TButton", background="#313244", foreground=self.text_primary, bordercolor=self.panel_border, font=("Segoe UI", 9, "bold"))
        self.style.map("TButton", background=[("active", "#45475a"), ("pressed", "#585b70")])

        self.selected_display_str = tk.StringVar()
        labels = [d["label"] for d in self.detected_displays]
        if labels:
            self.selected_display_str.set(labels[0])
        self.selected_size_var = tk.IntVar(value=1000)
        self.window_mode_var = tk.StringVar(value="windowed")
        self.debug_pattern_var = tk.StringVar(value="deterministic_random")
        self.show_debug_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.apply_display()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        header = tk.Frame(main, bg=self.bg_color)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="SuperQR", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="V7 • offline screen-to-camera file transfer • V6 proven carrier",
            style="SubHeader.TLabel",
        ).pack(anchor="w")

        display_frame = ttk.LabelFrame(main, text=" Display ", padding=10)
        display_frame.pack(fill="x", pady=4)

        row = ttk.Frame(display_frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Target display:").pack(side="left")
        self.disp_combo = ttk.Combobox(
            row,
            textvariable=self.selected_display_str,
            values=[d["label"] for d in self.detected_displays],
            state="readonly",
            width=24,
        )
        self.disp_combo.pack(side="left", padx=8, fill="x", expand=True)

        row = ttk.Frame(display_frame)
        row.pack(fill="x", pady=(6, 2))
        ttk.Label(row, text="Marker:").pack(side="left")
        self.size_combo = ttk.Combobox(
            row,
            values=[f"{v} px" for v in SIZE_PRESETS],
            state="readonly",
            width=10,
        )
        self.size_combo.set("1000 px")
        self.size_combo.pack(side="left", padx=8)
        self.size_combo.bind("<<ComboboxSelected>>", self._on_size_selected)
        ttk.Radiobutton(row, text="Windowed", value="windowed", variable=self.window_mode_var).pack(side="left", padx=8)
        ttk.Radiobutton(row, text="Fullscreen", value="fullscreen", variable=self.window_mode_var).pack(side="left")
        ttk.Button(display_frame, text="Apply Display", command=self.apply_display).pack(fill="x", pady=(7, 0))

        transfer_frame = ttk.LabelFrame(main, text=" Send File — V7 ", padding=10)
        transfer_frame.pack(fill="x", pady=4)

        buttons = ttk.Frame(transfer_frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Select File", command=self.select_file).pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_start = ttk.Button(buttons, text="Start Transfer", command=self.start_transfer)
        self.btn_start.pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(buttons, text="Stop", command=self.stop_transfer).pack(side="left", expand=True, fill="x", padx=(4, 0))

        nav = ttk.Frame(transfer_frame)
        nav.pack(fill="x", pady=(5, 2))
        self.btn_prev = ttk.Button(nav, text="Previous", command=self.prev_frame)
        self.btn_prev.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_show = ttk.Button(nav, text="Show Frame", command=self.show_frame)
        self.btn_show.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_next = ttk.Button(nav, text="Next", command=self.next_frame)
        self.btn_next.pack(side="left", expand=True, fill="x", padx=(4, 0))

        speed = ttk.Frame(transfer_frame)
        speed.pack(fill="x", pady=(6, 2))
        ttk.Label(speed, text="Frame interval:").pack(side="left")
        self.interval_combo = ttk.Combobox(
            speed,
            values=[f"{v} ms" for v in V7SenderSession.INTERVAL_PRESETS],
            state="readonly",
            width=9,
        )
        self.interval_combo.set("67 ms")
        self.interval_combo.pack(side="left", padx=8)
        self.interval_combo.bind("<<ComboboxSelected>>", self._on_interval_selected)
        ttk.Label(speed, text="40×40 • 4 colors • 400 B/frame", foreground=self.text_secondary).pack(side="left", padx=6)

        info = ttk.Frame(transfer_frame)
        info.pack(fill="x", pady=(6, 0))
        self.lbl_sender_state = ttk.Label(info, text="State: IDLE", font=("Segoe UI", 9, "bold"))
        self.lbl_sender_state.grid(row=0, column=0, sticky="w", columnspan=2)
        self.lbl_sender_file = ttk.Label(info, text="File: -")
        self.lbl_sender_file.grid(row=1, column=0, sticky="w", columnspan=2)
        self.lbl_sender_meta = ttk.Label(info, text="Size: -")
        self.lbl_sender_meta.grid(row=2, column=0, sticky="w")
        self.lbl_sender_session = ttk.Label(info, text="Session: -")
        self.lbl_sender_session.grid(row=2, column=1, sticky="w")
        self.lbl_sender_frame = ttk.Label(info, text="Frame: -")
        self.lbl_sender_frame.grid(row=3, column=0, sticky="w")
        self.lbl_sender_crc = ttk.Label(info, text="CRC32: -")
        self.lbl_sender_crc.grid(row=3, column=1, sticky="w")
        info.columnconfigure(0, weight=1)
        info.columnconfigure(1, weight=1)

        status_frame = ttk.LabelFrame(main, text=" Live Status ", padding=10)
        status_frame.pack(fill="x", pady=4)
        self.lbl_status = ttk.Label(status_frame, text="READY", foreground=self.status_ok_color, font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(anchor="w")
        self.lbl_display = ttk.Label(status_frame, text="Display: -")
        self.lbl_display.pack(anchor="w", pady=1)
        self.lbl_throughput = ttk.Label(status_frame, text="Link: -")
        self.lbl_throughput.pack(anchor="w", pady=1)
        self.lbl_last_err = ttk.Label(status_frame, text="Last Error: None", font=("Segoe UI", 8))
        self.lbl_last_err.pack(anchor="w", pady=1)
        ttk.Button(status_frame, text="Copy Diagnostics", command=self.copy_diagnostics).pack(fill="x", pady=(7, 0))

        debug_toggle = ttk.Checkbutton(
            main,
            text="Show V6 carrier/debug tools",
            variable=self.show_debug_var,
            command=self._toggle_debug,
        )
        debug_toggle.pack(anchor="w", pady=(5, 1))

        self.debug_frame = ttk.LabelFrame(main, text=" Debug Tools — preserved from V6 ", padding=10)
        pattern_grid = ttk.Frame(self.debug_frame)
        pattern_grid.pack(fill="x")
        for idx, (label, value) in enumerate(DEBUG_PATTERNS):
            ttk.Radiobutton(
                pattern_grid,
                text=label,
                value=value,
                variable=self.debug_pattern_var,
                command=self.render_debug_pattern,
            ).grid(row=idx // 2, column=idx % 2, sticky="w", padx=8, pady=2)
        pattern_grid.columnconfigure(0, weight=1)
        pattern_grid.columnconfigure(1, weight=1)
        ttk.Label(
            self.debug_frame,
            text="These patterns use the frozen V6 renderer only for geometry/camera diagnostics.",
            foreground=self.text_secondary,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

        self._update_sender_ui()

    def _toggle_debug(self):
        if self.show_debug_var.get():
            self.debug_frame.pack(fill="x", pady=4)
        else:
            self.debug_frame.pack_forget()

    def _get_selected_display_index(self) -> int:
        label = self.selected_display_str.get()
        match = next((d for d in self.detected_displays if d["label"] == label), None)
        return match["index"] if match else 0

    def _on_size_selected(self, _event=None):
        try:
            value = int(self.size_combo.get().replace(" px", ""))
            if value in SIZE_PRESETS:
                self.selected_size_var.set(value)
        except ValueError:
            pass

    def _on_interval_selected(self, _event=None):
        try:
            value = int(self.interval_combo.get().replace(" ms", ""))
            self.sender.set_interval(value)
            self._update_sender_ui()
        except ValueError:
            pass

    def _ensure_v7_renderer(self):
        marker_size = self.display_controller.marker_size
        if self.v7_renderer is None or self.v7_renderer.marker_size != marker_size:
            self.v7_renderer = LabRenderer(marker_size=marker_size)

    def apply_display(self):
        try:
            disp_idx = self._get_selected_display_index()
            fullscreen = self.window_mode_var.get() == "fullscreen"
            marker_size = self.selected_size_var.get()
            metrics = self.display_controller.setup_display(disp_idx, fullscreen, marker_size)
            self.v7_renderer = LabRenderer(marker_size=self.display_controller.marker_size)
            canvas = self.display_controller.screen.get_size()
            self.lbl_display.config(
                text=f"Display: {canvas[0]}×{canvas[1]} • marker {self.display_controller.marker_size}px • active {metrics.active_width}×{metrics.active_height}"
            )
            self.renderer_status = "READY"
            self.last_error = "None"
            self.lbl_last_err.config(text="Last Error: None")
            self._update_status_ui()
            if self.sender.total_frames:
                self._render_current_transfer_frame()
            else:
                self.display_controller.render("deterministic_random")
        except Exception as exc:
            self._set_error(exc)

    def select_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        try:
            self.sender.prepare_transfer(path)
            self.last_error = "None"
            self.lbl_last_err.config(text="Last Error: None")
            self._render_current_transfer_frame()
            self._update_sender_ui()
            self._update_status_ui()
        except Exception as exc:
            self._set_error(exc, "Failed to prepare V7 transfer")

    def start_transfer(self):
        if not self.sender.total_frames:
            messagebox.showwarning("No file", "Select a file first.")
            return
        if self.sender.start_transfer():
            self.sender_last_tick = time.monotonic()
            self._render_current_transfer_frame()
            self._update_sender_ui()
            self._update_status_ui()

    def stop_transfer(self):
        self.sender.stop_transfer()
        self._update_sender_ui()
        self._update_status_ui()

    def prev_frame(self):
        if self.sender.transfer_state == "SENDING" or not self.sender.total_frames:
            return
        self.sender.prev_frame()
        self._render_current_transfer_frame()
        self._update_sender_ui()

    def next_frame(self):
        if self.sender.transfer_state == "SENDING" or not self.sender.total_frames:
            return
        self.sender.next_frame()
        self._render_current_transfer_frame()
        self._update_sender_ui()

    def show_frame(self):
        if self.sender.total_frames:
            self._render_current_transfer_frame()

    def _render_current_transfer_frame(self):
        self._ensure_v7_renderer()
        matrix = self.sender.get_current_matrix()
        self.v7_renderer.prepare_logical_frame(matrix)
        frame_surface = self.v7_renderer.cached_frame_display
        screen = self.display_controller.screen
        if frame_surface is None or screen is None:
            return
        canvas_w, canvas_h = screen.get_size()
        marker = self.display_controller.marker_size
        x = (canvas_w - marker) // 2
        y = (canvas_h - marker) // 2
        screen.fill((0, 0, 0))
        screen.blit(frame_surface, (x, y))
        pygame.display.flip()

    def render_debug_pattern(self):
        if self.sender.transfer_state == "SENDING":
            self.sender.stop_transfer()
        try:
            self.display_controller.render(self.debug_pattern_var.get())
            self._update_sender_ui()
            self._update_status_ui()
        except Exception as exc:
            self._set_error(exc)

    def _update_sender_ui(self):
        self.lbl_sender_state.config(text=f"State: {self.sender.transfer_state}")
        if self.sender.filename:
            self.lbl_sender_file.config(text=f"File: {self.sender.filename} • {self.sender.mime_type}")
            self.lbl_sender_meta.config(text=f"Size: {self.sender.file_size:,} B • package {self.sender.package_size:,} B")
            self.lbl_sender_session.config(text=f"Session: {self.sender.session_id}")
            self.lbl_sender_frame.config(text=f"Frame: {self.sender.current_frame_idx + 1}/{self.sender.total_frames}")
            self.lbl_sender_crc.config(text=f"CRC32: {self.sender.file_crc32:08X}")
        else:
            self.lbl_sender_file.config(text="File: -")
            self.lbl_sender_meta.config(text="Size: -")
            self.lbl_sender_session.config(text="Session: -")
            self.lbl_sender_frame.config(text="Frame: -")
            self.lbl_sender_crc.config(text="CRC32: -")

        can_nav = self.sender.total_frames > 0 and self.sender.transfer_state in ("READY", "STOPPED")
        state = "normal" if can_nav else "disabled"
        self.btn_prev.config(state=state)
        self.btn_show.config(state=state)
        self.btn_next.config(state=state)

        fps = 1000.0 / self.sender.interval_ms
        raw_kib = (400.0 * fps) / 1024.0
        payload_kib = (PAYLOAD_SIZE * fps) / 1024.0
        self.lbl_throughput.config(
            text=f"Link: {self.sender.interval_ms} ms • {fps:.1f} frames/s • raw {raw_kib:.2f} KiB/s • payload ≤ {payload_kib:.2f} KiB/s"
        )

    def _update_status_ui(self):
        if self.renderer_status == "ERROR":
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
        elif self.sender.transfer_state == "SENDING":
            self.lbl_status.config(text="SENDING V7", foreground="#89dceb")
        elif self.sender.transfer_state in ("READY", "STOPPED"):
            self.lbl_status.config(text="READY V7", foreground=self.status_ok_color)
        else:
            self.lbl_status.config(text="READY", foreground=self.status_ok_color)

    def _set_error(self, exc: Exception, title: str | None = None):
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.renderer_status = "ERROR"
        self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
        self._update_status_ui()
        traceback.print_exc()
        if title:
            messagebox.showerror(title, self.last_error)

    def copy_diagnostics(self):
        marker = self.selected_size_var.get()
        diag = (
            "SuperQR V7 Diagnostics\n"
            "======================\n"
            f"Protocol: V7 baseline\n"
            f"Carrier: frozen V6 reference carrier\n"
            f"Grid: {GRID_SIZE}x{GRID_SIZE}\n"
            f"Palette: v6_reference_4 (2 bits/cell)\n"
            f"Frame bytes: 400\n"
            f"Transport payload bytes/frame: {PAYLOAD_SIZE}\n"
            f"Contract SHA-256: {self.contract_hash}\n"
            f"Display: {self.selected_display_str.get()}\n"
            f"Marker: {marker}px ({marker / CANONICAL_SIZE * 100:.1f}%)\n"
            f"Window mode: {self.window_mode_var.get()}\n"
            f"Transfer state: {self.sender.transfer_state}\n"
            f"File: {self.sender.filename or '-'}\n"
            f"MIME: {self.sender.mime_type if self.sender.filename else '-'}\n"
            f"File size: {self.sender.file_size}\n"
            f"File CRC32: {self.sender.file_crc32:08X}\n"
            f"Session: {self.sender.session_id or '-'}\n"
            f"Frame: {self.sender.current_frame_idx + 1 if self.sender.total_frames else '-'} / {self.sender.total_frames or '-'}\n"
            f"Interval: {self.sender.interval_ms} ms\n"
            f"Last error: {self.last_error}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(diag)
        messagebox.showinfo("Diagnostics", "Copied to clipboard.")

    def run(self):
        while True:
            try:
                self.root.update()
            except tk.TclError:
                break

            if self.sender.transfer_state == "SENDING" and self.sender.total_frames:
                now = time.monotonic()
                if now - self.sender_last_tick >= self.sender.interval_ms / 1000.0:
                    self.sender_last_tick = now
                    self.sender.advance_frame()
                    try:
                        self._render_current_transfer_frame()
                        self._update_sender_ui()
                    except Exception as exc:
                        self.sender.stop_transfer()
                        self._set_error(exc)

            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    self.root.destroy()
                    pygame.quit()
                    return


def main():
    contract, contract_hash = load_contract()
    ControlApp(contract, contract_hash).run()


if __name__ == "__main__":
    main()
