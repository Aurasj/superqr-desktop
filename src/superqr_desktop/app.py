from __future__ import annotations

import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.display import CANONICAL_SIZE, DisplayController
from superqr_desktop.v7.profiles import DEFAULT_PROFILE, PROFILES, BY_LABEL
from superqr_desktop.v7.renderer import V7TransferRenderer
from superqr_desktop.v7.sender import V7SenderSession

SIZE_PRESETS = [1000, 900, 800, 700, 600, 500, 400]
DEBUG_PATTERNS = [
    ("Random", "deterministic_random"),
    ("Checker", "checkerboard"),
    ("Black", "black"),
    ("White", "white"),
]


class ControlApp:
    """Single clean SuperQR desktop sender.

    V7 is the product protocol. Optical density/palette are selectable profiles;
    the profile id is rendered into the carrier so Android can follow AUTO.
    """

    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash
        self.last_error = "None"
        self.renderer_status = "READY"

        pygame.init()
        self.display_controller = DisplayController(contract)
        self.detected_displays = self.display_controller.detect_displays()
        self.sender = V7SenderSession()
        self.sender.profile = DEFAULT_PROFILE
        self.sender_last_tick = 0.0
        self.v7_renderer: V7TransferRenderer | None = None

        self.root = tk.Tk()
        self.root.title("SuperQR")
        self.root.geometry("570x760")
        self.root.minsize(540, 700)
        self.root.configure(bg="#11131a")

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.bg = "#11131a"
        self.panel = "#191d28"
        self.panel2 = "#222838"
        self.border = "#30384c"
        self.text = "#edf2ff"
        self.muted = "#99a4bd"
        self.accent = "#7cb7ff"
        self.good = "#7ee787"
        self.warn = "#f2cc60"
        self.bad = "#ff7b72"
        self.style.configure(".", background=self.bg, foreground=self.text, font=("Segoe UI", 9))
        self.style.configure("TFrame", background=self.bg)
        self.style.configure("Card.TFrame", background=self.panel)
        self.style.configure("TLabel", background=self.bg, foreground=self.text)
        self.style.configure("Card.TLabel", background=self.panel, foreground=self.text)
        self.style.configure("Muted.TLabel", background=self.panel, foreground=self.muted)
        self.style.configure("Title.TLabel", background=self.bg, foreground=self.text, font=("Segoe UI", 17, "bold"))
        self.style.configure("Section.TLabel", background=self.panel, foreground=self.accent, font=("Segoe UI", 10, "bold"))
        self.style.configure("TButton", background=self.panel2, foreground=self.text, bordercolor=self.border, font=("Segoe UI", 9, "bold"), padding=7)
        self.style.map("TButton", background=[("active", "#30384c"), ("pressed", "#3b455d")])
        self.style.configure("Accent.TButton", background="#245b8f", foreground="white", font=("Segoe UI", 10, "bold"), padding=9)
        self.style.map("Accent.TButton", background=[("active", "#2f74b5")])
        self.style.configure("TCombobox", fieldbackground=self.panel2, background=self.panel2, foreground=self.text)
        self.style.configure("TRadiobutton", background=self.panel, foreground=self.text)
        self.style.configure("TCheckbutton", background=self.bg, foreground=self.text)

        labels = [d["label"] for d in self.detected_displays]
        self.selected_display_str = tk.StringVar(value=labels[0] if labels else "Display 1")
        self.selected_size_var = tk.IntVar(value=800)
        self.window_mode_var = tk.StringVar(value="windowed")
        self.profile_var = tk.StringVar(value=DEFAULT_PROFILE.label)
        self.show_debug_var = tk.BooleanVar(value=False)
        self.debug_pattern_var = tk.StringVar(value="deterministic_random")

        self._build_ui()
        self.apply_display()

    def _card(self, parent, title: str):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
        outer.pack(fill="x", pady=5)
        ttk.Label(outer, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        return outer

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="SuperQR", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Adaptive offline screen → camera transfer", foreground=self.muted).pack(anchor="w", pady=(0, 8))

        display = self._card(main, "DISPLAY")
        row = ttk.Frame(display, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Monitor", style="Card.TLabel").pack(side="left")
        self.disp_combo = ttk.Combobox(row, textvariable=self.selected_display_str, values=[d["label"] for d in self.detected_displays], state="readonly", width=26)
        self.disp_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.size_combo = ttk.Combobox(row, values=[f"{v} px" for v in SIZE_PRESETS], state="readonly", width=9)
        self.size_combo.set("800 px")
        self.size_combo.pack(side="left")
        self.size_combo.bind("<<ComboboxSelected>>", self._on_size_selected)

        row = ttk.Frame(display, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Radiobutton(row, text="Windowed", value="windowed", variable=self.window_mode_var).pack(side="left")
        ttk.Radiobutton(row, text="Fullscreen", value="fullscreen", variable=self.window_mode_var).pack(side="left", padx=(14, 0))
        ttk.Button(row, text="Apply", command=self.apply_display).pack(side="right")

        optical = self._card(main, "OPTICAL PROFILE")
        row = ttk.Frame(optical, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Profile", style="Card.TLabel").pack(side="left")
        self.profile_combo = ttk.Combobox(row, textvariable=self.profile_var, values=[p.label for p in PROFILES], state="readonly", width=34)
        self.profile_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        row = ttk.Frame(optical, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Frame interval", style="Card.TLabel").pack(side="left")
        self.interval_combo = ttk.Combobox(row, values=[f"{v} ms" for v in V7SenderSession.INTERVAL_PRESETS], state="readonly", width=9)
        self.interval_combo.set("67 ms")
        self.interval_combo.pack(side="left", padx=8)
        self.interval_combo.bind("<<ComboboxSelected>>", self._on_interval_selected)
        self.lbl_profile_detail = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_profile_detail.pack(side="left", padx=8)

        transfer = self._card(main, "TRANSFER")
        row = ttk.Frame(transfer, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Select file", command=self.select_file).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.btn_start = ttk.Button(row, text="START", style="Accent.TButton", command=self.start_transfer)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(row, text="Stop", command=self.stop_transfer).pack(side="left", fill="x", expand=True, padx=(5, 0))

        self.lbl_sender_file = ttk.Label(transfer, text="No file selected", style="Card.TLabel")
        self.lbl_sender_file.pack(anchor="w", pady=(9, 2))
        self.lbl_sender_meta = ttk.Label(transfer, text="", style="Muted.TLabel")
        self.lbl_sender_meta.pack(anchor="w")
        self.lbl_progress = ttk.Label(transfer, text="", style="Muted.TLabel")
        self.lbl_progress.pack(anchor="w", pady=(2, 0))

        nav = ttk.Frame(transfer, style="Card.TFrame")
        nav.pack(fill="x", pady=(8, 0))
        self.btn_prev = ttk.Button(nav, text="◀ Prev", command=self.prev_frame)
        self.btn_prev.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_show = ttk.Button(nav, text="Show frame", command=self.show_frame)
        self.btn_show.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_next = ttk.Button(nav, text="Next ▶", command=self.next_frame)
        self.btn_next.pack(side="left", expand=True, fill="x", padx=(4, 0))

        live = self._card(main, "LIVE")
        row = ttk.Frame(live, style="Card.TFrame")
        row.pack(fill="x")
        self.lbl_status = ttk.Label(row, text="READY", style="Card.TLabel", font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(side="left")
        self.lbl_link = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_link.pack(side="right")
        self.lbl_display = ttk.Label(live, text="Display: -", style="Muted.TLabel")
        self.lbl_display.pack(anchor="w", pady=(5, 0))
        self.lbl_last_err = ttk.Label(live, text="Last error: none", style="Muted.TLabel")
        self.lbl_last_err.pack(anchor="w", pady=(2, 0))
        ttk.Button(live, text="Copy diagnostics", command=self.copy_diagnostics).pack(fill="x", pady=(8, 0))

        ttk.Checkbutton(main, text="Advanced / V6 carrier debug", variable=self.show_debug_var, command=self._toggle_debug).pack(anchor="w", pady=(6, 0))
        self.debug_frame = ttk.Frame(main, style="Card.TFrame", padding=10)
        debug_row = ttk.Frame(self.debug_frame, style="Card.TFrame")
        debug_row.pack(fill="x")
        for label, value in DEBUG_PATTERNS:
            ttk.Radiobutton(debug_row, text=label, value=value, variable=self.debug_pattern_var, command=self.render_debug_pattern).pack(side="left", padx=(0, 10))
        ttk.Label(self.debug_frame, text="Geometry diagnostic only; transfer stays V7.", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        self._update_sender_ui()

    def _toggle_debug(self):
        if self.show_debug_var.get():
            self.debug_frame.pack(fill="x", pady=5)
        else:
            self.debug_frame.pack_forget()

    def _selected_display_index(self) -> int:
        label = self.selected_display_str.get()
        found = next((d for d in self.detected_displays if d["label"] == label), None)
        return found["index"] if found else 0

    def _on_size_selected(self, _event=None):
        try:
            self.selected_size_var.set(int(self.size_combo.get().replace(" px", "")))
        except ValueError:
            pass

    def _on_profile_selected(self, _event=None):
        try:
            self.sender.stop_transfer()
            self.sender.set_profile(BY_LABEL[self.profile_var.get()])
            self.v7_renderer = None
            if self.sender.total_frames:
                self._render_current_transfer_frame()
            self._update_sender_ui()
        except Exception as exc:
            self._set_error(exc)

    def _on_interval_selected(self, _event=None):
        try:
            self.sender.set_interval(int(self.interval_combo.get().replace(" ms", "")))
            self._update_sender_ui()
        except ValueError:
            pass

    def _ensure_renderer(self):
        marker = self.display_controller.marker_size
        if self.v7_renderer is None or self.v7_renderer.marker_size != marker or self.v7_renderer.profile != self.sender.profile:
            self.v7_renderer = V7TransferRenderer(marker, self.sender.profile)

    def apply_display(self):
        try:
            marker = self.selected_size_var.get()
            metrics = self.display_controller.setup_display(self._selected_display_index(), self.window_mode_var.get() == "fullscreen", marker)
            self.v7_renderer = V7TransferRenderer(self.display_controller.marker_size, self.sender.profile)
            canvas = self.display_controller.screen.get_size()
            self.lbl_display.config(text=f"Display {canvas[0]}×{canvas[1]} • marker {self.display_controller.marker_size}px • carrier active {metrics.active_width}×{metrics.active_height}")
            self.renderer_status = "READY"
            if self.sender.total_frames:
                self._render_current_transfer_frame()
            else:
                self.display_controller.render("deterministic_random")
            self._update_status_ui()
        except Exception as exc:
            self._set_error(exc)

    def select_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        try:
            self.sender.prepare_transfer(path)
            self._render_current_transfer_frame()
            self._update_sender_ui()
        except Exception as exc:
            self._set_error(exc, "Could not prepare transfer")

    def start_transfer(self):
        if not self.sender.total_frames:
            messagebox.showwarning("SuperQR", "Select a file first.")
            return
        if self.sender.start_transfer():
            self.sender_last_tick = time.monotonic()
            self._render_current_transfer_frame()
            self._update_sender_ui()

    def stop_transfer(self):
        self.sender.stop_transfer()
        self._update_sender_ui()

    def prev_frame(self):
        if self.sender.transfer_state != "SENDING" and self.sender.total_frames:
            self.sender.prev_frame(); self._render_current_transfer_frame(); self._update_sender_ui()

    def next_frame(self):
        if self.sender.transfer_state != "SENDING" and self.sender.total_frames:
            self.sender.next_frame(); self._render_current_transfer_frame(); self._update_sender_ui()

    def show_frame(self):
        if self.sender.total_frames:
            self._render_current_transfer_frame()

    def _render_current_transfer_frame(self):
        self._ensure_renderer()
        symbols = self.sender.get_frame_symbols()
        self.v7_renderer.prepare_symbols(symbols)
        surface = self.v7_renderer.cached_frame_display
        screen = self.display_controller.screen
        if surface is None or screen is None:
            return
        cw, ch = screen.get_size()
        marker = self.display_controller.marker_size
        screen.fill((8, 10, 14))
        screen.blit(surface, ((cw - marker) // 2, (ch - marker) // 2))
        pygame.display.flip()

    def render_debug_pattern(self):
        self.sender.stop_transfer()
        try:
            self.display_controller.render(self.debug_pattern_var.get())
            self._update_sender_ui()
        except Exception as exc:
            self._set_error(exc)

    def _update_sender_ui(self):
        p = self.sender.profile
        self.profile_var.set(p.label)
        self.lbl_profile_detail.config(text=f"{p.frame_size} B/frame • cell {p.cell_width:.1f}×{p.cell_height:.1f}px @ 1000")
        fps = 1000.0 / self.sender.interval_ms
        self.lbl_link.config(text=f"{fps:.1f} fps • payload ≤ {p.payload_kib_s(self.sender.interval_ms):.2f} KiB/s")
        if self.sender.filename:
            self.lbl_sender_file.config(text=f"{self.sender.filename}  •  {self.sender.mime_type}")
            self.lbl_sender_meta.config(text=f"{self.sender.file_size:,} B • package {self.sender.package_size:,} B • CRC32 {self.sender.file_crc32:08X}")
            self.lbl_progress.config(text=f"Session {self.sender.session_id} • frame {self.sender.current_frame_idx + 1}/{self.sender.total_frames} • {p.key}")
        else:
            self.lbl_sender_file.config(text="No file selected")
            self.lbl_sender_meta.config(text=f"AUTO receiver profile id {p.id} • {p.grid}×{p.grid} • {p.color_count} colors")
            self.lbl_progress.config(text="")
        can_nav = self.sender.total_frames > 0 and self.sender.transfer_state in ("READY", "STOPPED")
        state = "normal" if can_nav else "disabled"
        self.btn_prev.config(state=state); self.btn_show.config(state=state); self.btn_next.config(state=state)
        self._update_status_ui()

    def _update_status_ui(self):
        if self.renderer_status == "ERROR":
            self.lbl_status.config(text="ERROR", foreground=self.bad)
        elif self.sender.transfer_state == "SENDING":
            self.lbl_status.config(text="SENDING", foreground=self.accent)
        else:
            self.lbl_status.config(text="READY", foreground=self.good)

    def _set_error(self, exc: Exception, title: str | None = None):
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.renderer_status = "ERROR"
        self.lbl_last_err.config(text=f"Last error: {self.last_error}")
        self._update_status_ui()
        traceback.print_exc()
        if title:
            messagebox.showerror(title, self.last_error)

    def copy_diagnostics(self):
        p = self.sender.profile
        diag = (
            "SuperQR V7 diagnostics\n"
            "=======================\n"
            f"Profile: {p.key} (id {p.id})\n"
            f"Grid: {p.grid}x{p.grid}\n"
            f"Palette: {p.palette_name} ({p.color_count} colors, {p.bits_per_cell} bits/cell)\n"
            f"Payload bbox: 100,190 -> 900,810\n"
            f"Frame: {p.frame_size} bytes; payload: {p.payload_size} bytes\n"
            f"Cell canonical: {p.cell_width:.2f} x {p.cell_height:.2f}\n"
            f"Interval: {self.sender.interval_ms} ms\n"
            f"Raw: {p.raw_kib_s(self.sender.interval_ms):.2f} KiB/s\n"
            f"Payload max: {p.payload_kib_s(self.sender.interval_ms):.2f} KiB/s\n"
            f"Display: {self.selected_display_str.get()}\n"
            f"Marker: {self.selected_size_var.get()} px\n"
            f"File: {self.sender.filename or '-'}\n"
            f"Session: {self.sender.session_id or '-'}\n"
            f"Last error: {self.last_error}\n"
        )
        self.root.clipboard_clear(); self.root.clipboard_append(diag)
        messagebox.showinfo("SuperQR", "Diagnostics copied.")

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
                        self._render_current_transfer_frame(); self._update_sender_ui()
                    except Exception as exc:
                        self.sender.stop_transfer(); self._set_error(exc)
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    self.root.destroy(); pygame.quit(); return


def main():
    contract, contract_hash = load_contract()
    ControlApp(contract, contract_hash).run()


if __name__ == "__main__":
    main()
