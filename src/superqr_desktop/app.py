import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pygame
import sys
import os
import time
import traceback
from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.display import DisplayController, CANONICAL_SIZE
from superqr_desktop.v6.sender import V6SenderSession

SIZE_PRESETS = [1000, 800, 600, 500, 400, 300]

class ControlApp:
    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash
        self.last_error = "None"
        self.renderer_status = "READY"

        pygame.init()
        self.display_controller = DisplayController(self.contract)
        self.detected_displays = self.display_controller.detect_displays()
        self.sender = V6SenderSession()
        self.sender_last_tick = 0

        self.root = tk.Tk()
        self.root.title("SuperQR V6 Control Panel")
        self.root.geometry("480x760")
        self.root.minsize(460, 700)

        # Style configuration
        self.style = ttk.Style()
        self.style.theme_use('clam')

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
        self.style.configure("Header.TLabel", background=self.bg_color, foreground=self.text_primary, font=("Segoe UI", 12, "bold"))
        self.style.configure("SubHeader.TLabel", background=self.bg_color, foreground=self.text_secondary, font=("Segoe UI", 8))
        self.style.configure("TCombobox", fieldbackground="#313244", background="#313244", foreground=self.text_primary, selectbackground="#45475a")
        self.style.configure("TRadiobutton", background=self.panel_bg, foreground=self.text_primary, font=("Segoe UI", 9))
        self.style.configure("TCheckbutton", background=self.panel_bg, foreground=self.text_primary, font=("Segoe UI", 9))
        self.style.configure("TButton", background="#313244", foreground=self.text_primary, bordercolor=self.panel_border, font=("Segoe UI", 9, "bold"))
        self.style.map("TButton", background=[("active", "#45475a"), ("pressed", "#585b70")])

        self.selected_display_str = tk.StringVar()
        display_labels = [d["label"] for d in self.detected_displays]
        if display_labels:
            self.selected_display_str.set(display_labels[0])

        self.selected_size_var = tk.IntVar(value=1000)
        self.window_mode_var = tk.StringVar(value="windowed")
        self.mode_var = tk.StringVar(value="deterministic_random")

        self._build_ui()
        self.apply_display()

    def _build_ui(self):
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill="both", expand=True)

        # Header Section
        header_frame = tk.Frame(main_container, bg=self.bg_color)
        header_frame.pack(fill="x", pady=(0, 10))

        title_lbl = ttk.Label(header_frame, text="SuperQR V6 Control Panel", style="Header.TLabel")
        title_lbl.pack(anchor="w")

        short_hash = f"{self.contract_hash[:8]}...{self.contract_hash[-8:]}"
        hash_lbl = ttk.Label(header_frame, text=f"Contract: Verified ({short_hash})", style="SubHeader.TLabel")
        hash_lbl.pack(anchor="w")

        # Display & Scaling Selection Frame
        display_frame = ttk.LabelFrame(main_container, text=" Display & Marker Output Scaling ", padding=10)
        display_frame.pack(fill="x", pady=4)

        disp_row = ttk.Frame(display_frame)
        disp_row.pack(fill="x", pady=2)
        ttk.Label(disp_row, text="Target Display:").pack(side="left")

        display_labels = [d["label"] for d in self.detected_displays]
        self.disp_combo = ttk.Combobox(disp_row, textvariable=self.selected_display_str, values=display_labels, state="readonly", width=22)
        self.disp_combo.pack(side="left", padx=8, fill="x", expand=True)

        size_row = ttk.Frame(display_frame)
        size_row.pack(fill="x", pady=(6, 2))
        ttk.Label(size_row, text="Marker Output Size:").pack(side="left")
        size_preset_labels = [f"{s} px" for s in SIZE_PRESETS]
        self.size_combo = ttk.Combobox(size_row, values=size_preset_labels, state="readonly", width=12)
        self.size_combo.set("1000 px")
        self.size_combo.pack(side="left", padx=8)
        self.size_combo.bind("<<ComboboxSelected>>", self._on_size_selected)

        mode_row = ttk.Frame(display_frame)
        mode_row.pack(fill="x", pady=(6, 2))
        ttk.Label(mode_row, text="Window Mode:").pack(side="left")
        ttk.Radiobutton(mode_row, text="Windowed", value="windowed", variable=self.window_mode_var).pack(side="left", padx=10)
        ttk.Radiobutton(mode_row, text="Fullscreen", value="fullscreen", variable=self.window_mode_var).pack(side="left", padx=5)

        btn_apply = ttk.Button(display_frame, text="Apply Display & Scaling Settings", command=self.apply_display)
        btn_apply.pack(fill="x", pady=(8, 2))

        # 2x2 Grid Pattern Validation Frame
        pattern_frame = ttk.LabelFrame(main_container, text=" Pattern Selection ", padding=10)
        pattern_frame.pack(fill="x", pady=4)

        grid_2x2 = ttk.Frame(pattern_frame)
        grid_2x2.pack(fill="x")

        patterns = [
            ("Random Grid", "deterministic_random", 0, 0),
            ("Checkerboard", "checkerboard", 0, 1),
            ("All Black", "black", 1, 0),
            ("All White", "white", 1, 1),
        ]
        for text, val, r, c in patterns:
            rb = ttk.Radiobutton(grid_2x2, text=text, value=val, variable=self.mode_var, command=self.render_marker)
            rb.grid(row=r, column=c, sticky="w", padx=10, pady=3)

        grid_2x2.columnconfigure(0, weight=1)
        grid_2x2.columnconfigure(1, weight=1)

        # File Sender Frame
        sender_frame = ttk.LabelFrame(main_container, text=" File Sender Carousel ", padding=10)
        sender_frame.pack(fill="x", pady=4)

        btn_row = ttk.Frame(sender_frame)
        btn_row.pack(fill="x", pady=2)

        btn_select_file = ttk.Button(btn_row, text="Select File", command=self.select_file)
        btn_select_file.pack(side="left", padx=(0, 4), expand=True, fill="x")

        btn_start = ttk.Button(btn_row, text="Start Transfer", command=self.start_transfer)
        btn_start.pack(side="left", padx=4, expand=True, fill="x")

        btn_stop = ttk.Button(btn_row, text="Stop Transfer", command=self.stop_transfer)
        btn_stop.pack(side="left", padx=(4, 0), expand=True, fill="x")

        # Manual Frame Navigation Row
        nav_row = ttk.Frame(sender_frame)
        nav_row.pack(fill="x", pady=(4, 2))

        self.btn_prev_frame = ttk.Button(nav_row, text="Previous Frame", command=self.prev_frame)
        self.btn_prev_frame.pack(side="left", padx=(0, 4), expand=True, fill="x")

        self.btn_show_frame = ttk.Button(nav_row, text="Show Frame", command=self.show_frame)
        self.btn_show_frame.pack(side="left", padx=4, expand=True, fill="x")

        self.btn_next_frame = ttk.Button(nav_row, text="Next Frame", command=self.next_frame)
        self.btn_next_frame.pack(side="left", padx=(4, 0), expand=True, fill="x")

        interval_row = ttk.Frame(sender_frame)
        interval_row.pack(fill="x", pady=(6, 4))
        ttk.Label(interval_row, text="Frame Interval:").pack(side="left")

        self.interval_combo = ttk.Combobox(interval_row, values=["50 ms", "100 ms", "200 ms", "500 ms"], state="readonly", width=10)
        self.interval_combo.set("100 ms")
        self.interval_combo.pack(side="left", padx=8)
        self.interval_combo.bind("<<ComboboxSelected>>", self._on_interval_selected)

        sender_info = ttk.Frame(sender_frame)
        sender_info.pack(fill="x", pady=(4, 2))

        self.lbl_sender_state = ttk.Label(sender_info, text="Transfer State: IDLE", font=("Segoe UI", 9, "bold"))
        self.lbl_sender_state.grid(row=0, column=0, sticky="w", columnspan=2, pady=1)

        self.lbl_sender_file = ttk.Label(sender_info, text="File: -")
        self.lbl_sender_file.grid(row=1, column=0, sticky="w", columnspan=2, pady=1)

        self.lbl_sender_sizes = ttk.Label(sender_info, text="File: - | Pkg: -")
        self.lbl_sender_sizes.grid(row=2, column=0, sticky="w", pady=1)

        self.lbl_sender_session = ttk.Label(sender_info, text="Session ID: -")
        self.lbl_sender_session.grid(row=2, column=1, sticky="w", pady=1)

        self.lbl_sender_frame = ttk.Label(sender_info, text="Frame: -")
        self.lbl_sender_frame.grid(row=3, column=0, sticky="w", pady=1)

        self.lbl_sender_interval = ttk.Label(sender_info, text="Interval: 100 ms")
        self.lbl_sender_interval.grid(row=3, column=1, sticky="w", pady=1)

        sender_info.columnconfigure(0, weight=1)
        sender_info.columnconfigure(1, weight=1)

        # Compact Marker Info Frame
        metrics_frame = ttk.LabelFrame(main_container, text=" Compact Marker Info ", padding=10)
        metrics_frame.pack(fill="x", pady=4)

        info_sub = ttk.Frame(metrics_frame)
        info_sub.pack(fill="x")

        self.lbl_canvas = ttk.Label(info_sub, text="Canvas: -")
        self.lbl_canvas.grid(row=0, column=0, sticky="w", pady=1)
        self.lbl_marker = ttk.Label(info_sub, text="Marker: -")
        self.lbl_marker.grid(row=0, column=1, sticky="w", pady=1)
        self.lbl_active = ttk.Label(info_sub, text="Active: -")
        self.lbl_active.grid(row=1, column=0, sticky="w", pady=1)
        self.lbl_grid = ttk.Label(info_sub, text="Data Grid: -")
        self.lbl_grid.grid(row=1, column=1, sticky="w", pady=1)

        info_sub.columnconfigure(0, weight=1)
        info_sub.columnconfigure(1, weight=1)

        # Diagnostics & Status Frame
        diag_frame = ttk.LabelFrame(main_container, text=" Diagnostics & Status ", padding=10)
        diag_frame.pack(fill="both", expand=True, pady=4)

        status_row = ttk.Frame(diag_frame)
        status_row.pack(fill="x", pady=1)
        ttk.Label(status_row, text="Status: ").pack(side="left")
        self.lbl_status = ttk.Label(status_row, text="READY", foreground=self.status_ok_color, font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side="left")

        self.lbl_scaling_diag = ttk.Label(diag_frame, text="Canonical: 1000px | Displayed: 1000px | Scale: 100.0%")
        self.lbl_scaling_diag.pack(anchor="w", pady=1)

        self.lbl_mode_diag = ttk.Label(diag_frame, text="Current Pattern: deterministic_random")
        self.lbl_mode_diag.pack(anchor="w", pady=1)

        self.lbl_contract_diag = ttk.Label(diag_frame, text="Contract: SHA-256 Hash Matched")
        self.lbl_contract_diag.pack(anchor="w", pady=1)

        self.lbl_last_err = ttk.Label(diag_frame, text="Last Error: None", font=("Segoe UI", 8))
        self.lbl_last_err.pack(anchor="w", pady=1)

        btn_copy = ttk.Button(diag_frame, text="Copy Diagnostics", command=self.copy_diagnostics)
        btn_copy.pack(fill="x", pady=(8, 2))

    def _on_size_selected(self, event=None):
        val_str = self.size_combo.get().replace(" px", "").strip()
        try:
            val = int(val_str)
            if val in SIZE_PRESETS:
                self.selected_size_var.set(val)
        except ValueError:
            pass

    def _on_interval_selected(self, event=None):
        val_str = self.interval_combo.get().replace(" ms", "").strip()
        try:
            val = int(val_str)
            if val in V6SenderSession.INTERVAL_PRESETS:
                self.sender.set_interval(val)
                self._update_sender_ui()
        except ValueError:
            pass

    def _get_selected_display_index(self) -> int:
        sel_label = self.selected_display_str.get()
        match = next((d for d in self.detected_displays if d["label"] == sel_label), None)
        return match["index"] if match else 0

    def _update_sender_ui(self):
        self.lbl_sender_state.config(text=f"Transfer State: {self.sender.transfer_state}")
        if self.sender.filename:
            self.lbl_sender_file.config(text=f"File: {self.sender.filename}")
            self.lbl_sender_sizes.config(text=f"File: {self.sender.file_size} B | Pkg: {self.sender.package_size} B")
            self.lbl_sender_session.config(text=f"Session ID: {self.sender.session_id}")
            max_idx = max(0, self.sender.total_frames - 1)
            self.lbl_sender_frame.config(text=f"Frame: {self.sender.current_frame_idx} / {max_idx}")
        else:
            self.lbl_sender_file.config(text="File: -")
            self.lbl_sender_sizes.config(text="File: - | Pkg: -")
            self.lbl_sender_session.config(text="Session ID: -")
            self.lbl_sender_frame.config(text="Frame: -")

        self.lbl_sender_interval.config(text=f"Interval: {self.sender.interval_ms} ms")

        can_nav = bool(self.sender.frames and self.sender.transfer_state in ("READY", "STOPPED"))
        nav_state = "normal" if can_nav else "disabled"
        self.btn_prev_frame.config(state=nav_state)
        self.btn_show_frame.config(state=nav_state)
        self.btn_next_frame.config(state=nav_state)

    def _update_status_ui(self):
        if self.sender.transfer_state == "SENDING":
            self.lbl_status.config(text="SENDING", foreground="#89dceb")
        elif self.sender.transfer_state == "READY":
            self.lbl_status.config(text="READY", foreground=self.status_ok_color)
        elif self.sender.transfer_state == "STOPPED":
            self.lbl_status.config(text="STOPPED", foreground=self.text_secondary)
        elif self.renderer_status == "ERROR":
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
        else:
            self.lbl_status.config(text="READY", foreground=self.status_ok_color)

    def select_file(self):
        file_path = filedialog.askopenfilename()
        if not file_path:
            return

        try:
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                file_data = f.read()

            self.sender.prepare_transfer(filename, file_data)
            self.last_error = "None"
            self.lbl_last_err.config(text="Last Error: None")
            self._update_sender_ui()
            self._update_status_ui()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            messagebox.showerror("Transfer Preparation Error", f"Failed to prepare file transfer:\n{self.last_error}")
            traceback.print_exc()

    def start_transfer(self):
        if not self.sender.frames or self.sender.transfer_state not in ("READY", "STOPPED"):
            if not self.sender.frames:
                messagebox.showwarning("No Transfer Prepared", "Please select a valid file first.")
            return

        self.sender.start_transfer()
        self.sender_last_tick = 0  # Trigger frame 0 immediately
        self._update_sender_ui()
        self._update_status_ui()

    def stop_transfer(self):
        self.sender.stop_transfer()
        self._update_sender_ui()
        self._update_status_ui()

    def prev_frame(self):
        if self.sender.transfer_state == "SENDING" or not self.sender.frames:
            return
        self.sender.prev_frame()
        self._update_sender_ui()
        indexes = self.sender.get_current_frame_indexes()
        if indexes:
            self.display_controller.render_indexes(indexes)

    def show_frame(self):
        if self.sender.transfer_state == "SENDING" or not self.sender.frames:
            return
        self._update_sender_ui()
        indexes = self.sender.get_current_frame_indexes()
        if indexes:
            self.display_controller.render_indexes(indexes)

    def next_frame(self):
        if self.sender.transfer_state == "SENDING" or not self.sender.frames:
            return
        self.sender.next_frame()
        self._update_sender_ui()
        indexes = self.sender.get_current_frame_indexes()
        if indexes:
            self.display_controller.render_indexes(indexes)

    def copy_diagnostics(self):
        disp_idx = self._get_selected_display_index()
        target_sz = self.selected_size_var.get()
        scale_pct = (target_sz / CANONICAL_SIZE) * 100.0

        filename_str = self.sender.filename if self.sender.filename else "-"
        file_size_str = f"{self.sender.file_size} bytes" if self.sender.file_size else "-"
        package_size_str = f"{self.sender.package_size} bytes" if self.sender.package_size else "-"
        session_id_str = str(self.sender.session_id) if self.sender.session_id is not None else "-"
        current_frame_str = str(self.sender.current_frame_idx) if self.sender.total_frames > 0 else "-"
        total_frames_str = str(self.sender.total_frames) if self.sender.total_frames > 0 else "-"
        interval_str = f"{self.sender.interval_ms} ms"

        diag_info = (
            f"SuperQR V6 Control Panel Diagnostics\n"
            f"====================================\n"
            f"Contract SHA-256: {self.contract_hash}\n"
            f"Contract Verification: MATCHED\n"
            f"Renderer Status: {self.renderer_status}\n"
            f"Canonical Size: {CANONICAL_SIZE}x{CANONICAL_SIZE} px\n"
            f"Displayed Size: {target_sz}x{target_sz} px\n"
            f"Scale Percentage: {scale_pct:.1f}%\n"
            f"Target Display: {self.selected_display_str.get()} (Index {disp_idx})\n"
            f"Window Mode: {self.window_mode_var.get()}\n"
            f"Pattern Mode: {self.mode_var.get()}\n"
            f"Transfer State: {self.sender.transfer_state}\n"
            f"Filename: {filename_str}\n"
            f"File Size: {file_size_str}\n"
            f"Package Size: {package_size_str}\n"
            f"Session ID: {session_id_str}\n"
            f"Current Frame ID: {current_frame_str}\n"
            f"Total Frames: {total_frames_str}\n"
            f"Frame Interval: {interval_str}\n"
            f"Last Error: {self.last_error}\n"
            f"{self.lbl_canvas.cget('text')}\n"
            f"{self.lbl_marker.cget('text')}\n"
            f"{self.lbl_active.cget('text')}\n"
            f"{self.lbl_grid.cget('text')}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(diag_info)
        messagebox.showinfo("Diagnostics Copied", "Diagnostic information copied to clipboard.")

    def apply_display(self):
        try:
            disp_idx = self._get_selected_display_index()
            is_fs = (self.window_mode_var.get() == "fullscreen")
            target_sz = self.selected_size_var.get()

            metrics = self.display_controller.setup_display(disp_idx, is_fs, target_sz)

            canvas_w, canvas_h = self.display_controller.screen.get_size()
            marker_size = self.display_controller.marker_size
            scale_pct = (marker_size / CANONICAL_SIZE) * 100.0

            self.lbl_canvas.config(text=f"Canvas: {canvas_w}x{canvas_h} px")
            self.lbl_marker.config(text=f"Marker: {marker_size}x{marker_size} px")
            self.lbl_active.config(text=f"Active: {metrics.active_width}x{metrics.active_height} px")
            self.lbl_grid.config(text=f"Data Grid: {metrics.grid_width}x{metrics.grid_height} px")
            self.lbl_scaling_diag.config(text=f"Canonical: {CANONICAL_SIZE}px | Displayed: {marker_size}px | Scale: {scale_pct:.1f}%")

            self.renderer_status = "READY"
            self._update_status_ui()
            self.lbl_last_err.config(text="Last Error: None")

            if self.sender.transfer_state == "SENDING" and self.sender.frames:
                indexes = self.sender.frames[self.sender.current_frame_idx]
                self.display_controller.render_indexes(indexes)
            elif self.sender.frames and self.sender.transfer_state in ("READY", "STOPPED"):
                indexes = self.sender.get_current_frame_indexes()
                if indexes:
                    self.display_controller.render_indexes(indexes)
            else:
                self.render_marker()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.renderer_status = "ERROR"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            traceback.print_exc()

    def render_marker(self):
        if self.sender.transfer_state == "SENDING":
            self.sender.set_static_pattern()
            self._update_sender_ui()
            self._update_status_ui()

        try:
            mode = self.mode_var.get()
            self.lbl_mode_diag.config(text=f"Current Pattern: {mode}")
            self.display_controller.render(mode)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.renderer_status = "ERROR"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            traceback.print_exc()

    def run(self):
        while True:
            try:
                self.root.update()
            except tk.TclError:
                break

            if self.sender.transfer_state == "SENDING" and self.sender.frames:
                now = time.monotonic()
                interval_sec = self.sender.interval_ms / 1000.0
                if now - self.sender_last_tick >= interval_sec:
                    self.sender_last_tick = now
                    current_idx = self.sender.advance_frame()
                    indexes = self.sender.frames[current_idx]
                    self.display_controller.render_indexes(indexes)
                    self._update_sender_ui()

            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    self.root.destroy()
                    pygame.quit()
                    return

def main():
    contract, h = load_contract()
    app = ControlApp(contract, h)
    app.run()

if __name__ == "__main__":
    main()
