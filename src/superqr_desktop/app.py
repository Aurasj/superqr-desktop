import tkinter as tk
from tkinter import ttk, messagebox
import pygame
import sys
import traceback
from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.display import DisplayController, CANONICAL_SIZE

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

        self.root = tk.Tk()
        self.root.title("SuperQR V6 Control Panel")
        self.root.geometry("460x680")
        self.root.minsize(440, 620)

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

    def _get_selected_display_index(self) -> int:
        sel_label = self.selected_display_str.get()
        match = next((d for d in self.detected_displays if d["label"] == sel_label), None)
        return match["index"] if match else 0

    def copy_diagnostics(self):
        disp_idx = self._get_selected_display_index()
        target_sz = self.selected_size_var.get()
        scale_pct = (target_sz / CANONICAL_SIZE) * 100.0
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
            self.lbl_status.config(text="READY", foreground=self.status_ok_color)
            self.lbl_last_err.config(text="Last Error: None")
            self.render_marker()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.renderer_status = "ERROR"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            traceback.print_exc()

    def render_marker(self):
        try:
            mode = self.mode_var.get()
            self.lbl_mode_diag.config(text=f"Current Pattern: {mode}")
            self.display_controller.render(mode)
            if self.renderer_status != "ERROR":
                self.lbl_status.config(text="READY", foreground=self.status_ok_color)
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
