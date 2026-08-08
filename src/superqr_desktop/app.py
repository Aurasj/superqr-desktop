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

GRID_CHOICES = [40, 48, 56, 64, 72, 80, 96]
PALETTE_CHOICES = ["v6_reference_4", "candidate_8_a"]
DWELL_CHOICES = [2, 3, 4]
LAYOUT_CHOICES = ["single", "2x2"]
DEFAULT_SEED = 42
DEFAULT_FRAMES = 100


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

        # ── V7 state ────────────────────────────────────────────────
        self._v7_renderer = None
        self._v7_profile = None
        self._v7_sequence = None
        self._v7_total_frames = 0
        self._v7_frame_idx = 0
        self._v7_state = "IDLE"       # IDLE | READY | RUNNING | STOPPED
        self._v7_last_tick = 0.0
        self._v7_presents_in_dwell = 0
        self._v7_dwell_epochs = 2
        self._v7_dwell_interval_sec = 0.0
        self._v7_validation_passed = False

        self.root = tk.Tk()
        self.root.title("SuperQR Control Panel")
        self.root.geometry("480x860")
        self.root.minsize(460, 780)

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
        self.engine_var = tk.StringVar(value="V6 Stable")

        # V7 widget variables
        self._v7_grid_var = tk.StringVar(value=str(GRID_CHOICES[0]))
        self._v7_palette_var = tk.StringVar(value=PALETTE_CHOICES[0])
        self._v7_dwell_var = tk.StringVar(value=str(DWELL_CHOICES[0]))
        self._v7_seed_var = tk.StringVar(value=str(DEFAULT_SEED))
        self._v7_layout_var = tk.StringVar(value=LAYOUT_CHOICES[0])
        self._v7_frames_var = tk.StringVar(value=str(DEFAULT_FRAMES))
        self._v7_calib_var = tk.BooleanVar(value=True)

        self._build_ui()
        self.apply_display()

    # ═════════════════════════════════════════════════════════════════
    # UI construction
    # ═════════════════════════════════════════════════════════════════

    def _build_ui(self):
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill="both", expand=True)

        # ── Header ────────────────────────────────────────────────
        header_frame = tk.Frame(main_container, bg=self.bg_color)
        header_frame.pack(fill="x", pady=(0, 10))

        title_lbl = ttk.Label(header_frame, text="SuperQR Control Panel", style="Header.TLabel")
        title_lbl.pack(anchor="w")

        short_hash = f"{self.contract_hash[:8]}...{self.contract_hash[-8:]}"
        hash_lbl = ttk.Label(header_frame, text=f"Contract: Verified ({short_hash})", style="SubHeader.TLabel")
        hash_lbl.pack(anchor="w")

        # ── Engine selector ───────────────────────────────────────
        engine_frame = ttk.LabelFrame(main_container, text=" Engine / Protocol ", padding=10)
        engine_frame.pack(fill="x", pady=4)

        eng_row = ttk.Frame(engine_frame)
        eng_row.pack(fill="x")
        ttk.Label(eng_row, text="Mode:").pack(side="left")
        ttk.Radiobutton(eng_row, text="V6 Stable", value="V6 Stable",
                        variable=self.engine_var, command=self._on_engine_changed).pack(side="left", padx=10)
        ttk.Radiobutton(eng_row, text="V7 Development", value="V7 Development",
                        variable=self.engine_var, command=self._on_engine_changed).pack(side="left", padx=5)

        # ── Display & Scaling Selection (shared) ──────────────────
        display_frame = ttk.LabelFrame(main_container, text=" Display & Marker Output Scaling ", padding=10)
        display_frame.pack(fill="x", pady=4)

        # Anchor reference for section insertion order
        self._section_anchor = display_frame

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

        # ── V6 Section ────────────────────────────────────────────
        self._v6_section = ttk.Frame(main_container)
        self._v6_section.pack(fill="x")

        # V6 Pattern Selection
        pattern_frame = ttk.LabelFrame(self._v6_section, text=" Pattern Selection ", padding=10)
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

        # V6 File Sender
        sender_frame = ttk.LabelFrame(self._v6_section, text=" File Sender Carousel ", padding=10)
        sender_frame.pack(fill="x", pady=4)

        btn_row = ttk.Frame(sender_frame)
        btn_row.pack(fill="x", pady=2)

        btn_select_file = ttk.Button(btn_row, text="Select File", command=self.select_file)
        btn_select_file.pack(side="left", padx=(0, 4), expand=True, fill="x")

        btn_start = ttk.Button(btn_row, text="Start Transfer", command=self.start_transfer)
        btn_start.pack(side="left", padx=4, expand=True, fill="x")

        btn_stop = ttk.Button(btn_row, text="Stop Transfer", command=self.stop_transfer)
        btn_stop.pack(side="left", padx=(4, 0), expand=True, fill="x")

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

        self.interval_combo = ttk.Combobox(interval_row, values=["50 ms", "67 ms", "75 ms", "100 ms", "200 ms", "500 ms"], state="readonly", width=10)
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

        # ── V7 Section ────────────────────────────────────────────
        self._v7_section = ttk.Frame(main_container)

        v7_lab_frame = ttk.LabelFrame(self._v7_section, text=" V7 Capacity Lab ", padding=10)
        v7_lab_frame.pack(fill="x", pady=4)

        # Row 1: Grid / Palette / Dwell
        r1 = ttk.Frame(v7_lab_frame)
        r1.pack(fill="x", pady=2)
        self._v7_combo(r1, "Grid", GRID_CHOICES, self._v7_grid_var).pack(side="left", padx=(0, 8))
        self._v7_combo(r1, "Palette", PALETTE_CHOICES, self._v7_palette_var).pack(side="left", padx=(0, 8))
        self._v7_combo(r1, "Dwell", DWELL_CHOICES, self._v7_dwell_var).pack(side="left")

        # Row 2: Layout / Frames / Seed
        r2 = ttk.Frame(v7_lab_frame)
        r2.pack(fill="x", pady=2)
        self._v7_combo(r2, "Layout", LAYOUT_CHOICES, self._v7_layout_var).pack(side="left", padx=(0, 8))
        self._v7_entry(r2, "Frames", self._v7_frames_var, 6).pack(side="left", padx=(0, 8))
        seed_frame = self._v7_entry(r2, "Seed", self._v7_seed_var, 6)
        seed_frame.pack(side="left")
        # Disable seed editing — canonical reference only
        for child in seed_frame.winfo_children():
            if isinstance(child, tk.Entry):
                child.config(state="disabled")

        # Row 3: Calibration + action buttons
        r3 = ttk.Frame(v7_lab_frame)
        r3.pack(fill="x", pady=(6, 2))
        ttk.Checkbutton(r3, text="Calibration frames", variable=self._v7_calib_var).pack(side="left")

        btn_frame = ttk.Frame(v7_lab_frame)
        btn_frame.pack(fill="x", pady=(4, 2))

        btn_v7_prepare = ttk.Button(btn_frame, text="Prepare / Validate", command=self._v7_prepare)
        btn_v7_prepare.pack(side="left", padx=(0, 4), expand=True, fill="x")

        self.btn_v7_start = ttk.Button(btn_frame, text="Start", command=self._v7_start, state="disabled")
        self.btn_v7_start.pack(side="left", padx=4, expand=True, fill="x")

        self.btn_v7_stop = ttk.Button(btn_frame, text="Stop", command=self._v7_stop, state="disabled")
        self.btn_v7_stop.pack(side="left", padx=4, expand=True, fill="x")

        btn_nav = ttk.Frame(v7_lab_frame)
        btn_nav.pack(fill="x", pady=(2, 2))

        self.btn_v7_prev = ttk.Button(btn_nav, text="Prev Frame", command=self._v7_prev, state="disabled")
        self.btn_v7_prev.pack(side="left", padx=(0, 4), expand=True, fill="x")

        self.btn_v7_next = ttk.Button(btn_nav, text="Next Frame", command=self._v7_next, state="disabled")
        self.btn_v7_next.pack(side="left", padx=4, expand=True, fill="x")

        self.btn_v7_reset = ttk.Button(btn_nav, text="Reset (Frame 0)", command=self._v7_reset, state="disabled")
        self.btn_v7_reset.pack(side="left", padx=(4, 0), expand=True, fill="x")

        # V7 status labels
        v7_info = ttk.Frame(v7_lab_frame)
        v7_info.pack(fill="x", pady=(6, 2))
        self.lbl_v7_state = ttk.Label(v7_info, text="Experiment: IDLE", font=("Segoe UI", 9, "bold"))
        self.lbl_v7_state.pack(anchor="w", pady=1)
        self.lbl_v7_validation = ttk.Label(v7_info, text="Validation: -")
        self.lbl_v7_validation.pack(anchor="w", pady=1)
        self.lbl_v7_frame = ttk.Label(v7_info, text="Frame: -")
        self.lbl_v7_frame.pack(anchor="w", pady=1)
        self.lbl_v7_timing = ttk.Label(v7_info, text="Timing: -")
        self.lbl_v7_timing.pack(anchor="w", pady=1)

        # ── Compact Marker Info Frame (shared) ────────────────────
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

        # ── Diagnostics & Status Frame (shared) ───────────────────
        diag_frame = ttk.LabelFrame(main_container, text=" Diagnostics & Status ", padding=10)
        diag_frame.pack(fill="both", expand=True, pady=4)

        status_row = ttk.Frame(diag_frame)
        status_row.pack(fill="x", pady=1)
        ttk.Label(status_row, text="Status: ").pack(side="left")
        self.lbl_status = ttk.Label(status_row, text="READY", foreground=self.status_ok_color, font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side="left")

        self.lbl_scaling_diag = ttk.Label(diag_frame, text="Canonical: 1000px | Displayed: 1000px | Scale: 100.0%")
        self.lbl_scaling_diag.pack(anchor="w", pady=1)

        self.lbl_mode_diag = ttk.Label(diag_frame, text="Engine: V6 Stable")
        self.lbl_mode_diag.pack(anchor="w", pady=1)

        self.lbl_contract_diag = ttk.Label(diag_frame, text="Contract: SHA-256 Hash Matched")
        self.lbl_contract_diag.pack(anchor="w", pady=1)

        self.lbl_last_err = ttk.Label(diag_frame, text="Last Error: None", font=("Segoe UI", 8))
        self.lbl_last_err.pack(anchor="w", pady=1)

        btn_copy = ttk.Button(diag_frame, text="Copy Diagnostics", command=self.copy_diagnostics)
        btn_copy.pack(fill="x", pady=(8, 2))

        # Initial visibility
        self._v6_section.pack(fill="x")
        # V7 section is packed after V6 section in the container

    # ═════════════════════════════════════════════════════════════════
    # Helper UI builders
    # ═════════════════════════════════════════════════════════════════

    def _v7_combo(self, parent, label: str, values: list, variable: tk.StringVar):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=label).pack(anchor="w")
        cb = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=12)
        cb.pack()
        return frame

    def _v7_entry(self, parent, label: str, variable: tk.StringVar, width: int = 8):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=label).pack(anchor="w")
        entry = tk.Entry(frame, textvariable=variable, width=width,
                         bg="#313244", fg=self.text_primary,
                         insertbackground=self.text_primary, relief="flat")
        entry.pack(pady=1)
        return frame

    # ═════════════════════════════════════════════════════════════════
    # Engine mode switching
    # ═════════════════════════════════════════════════════════════════

    def _on_engine_changed(self):
        engine = self.engine_var.get()
        self.lbl_mode_diag.config(text=f"Engine: {engine}")

        if engine == "V6 Stable":
            self._v7_stop_internal()
            self._v7_section.pack_forget()
            self._v6_section.pack(after=self._section_anchor, fill="x")
            self._update_status_ui()
        else:
            if self.sender.transfer_state == "SENDING":
                self.sender.stop_transfer()
                self._update_sender_ui()
            self._v6_section.pack_forget()
            self._v7_section.pack(after=self._section_anchor, fill="x")
            self._update_v7_ui()

    # ═════════════════════════════════════════════════════════════════
    # V6 handlers (unchanged)
    # ═════════════════════════════════════════════════════════════════

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
        if self.engine_var.get() == "V7 Development":
            if self._v7_state == "RUNNING":
                self.lbl_status.config(text="V7 RUNNING", foreground="#89dceb")
            elif self._v7_state == "READY":
                self.lbl_status.config(text="V7 READY", foreground=self.status_ok_color)
            elif self._v7_state == "STOPPED":
                self.lbl_status.config(text="V7 STOPPED", foreground=self.text_secondary)
            else:
                self.lbl_status.config(text="READY", foreground=self.status_ok_color)
        else:
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
        self.sender_last_tick = 0
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

    # ═════════════════════════════════════════════════════════════════
    # V7 handlers
    # ═════════════════════════════════════════════════════════════════

    def _v7_prepare(self):
        """Build profile, cross-validate, prepare frame sequence and first frame."""
        try:
            from superqr_desktop.v7_capacity_lab.protocol_bridge import (
                get_protocol_profiles, get_protocol_model,
            )
            from superqr_desktop.v7_capacity_lab.cross_validate import (
                validate_or_fail, CrossValidationError,
            )
            from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer

            profiles_mod = get_protocol_profiles()
            model_mod = get_protocol_model()
            CalibrationConfig = model_mod.CalibrationConfig

            grid = int(self._v7_grid_var.get())
            palette_name = self._v7_palette_var.get()
            dwell = int(self._v7_dwell_var.get())
            seed = int(self._v7_seed_var.get())
            layout = self._v7_layout_var.get()
            frames = int(self._v7_frames_var.get())
            calib_enabled = self._v7_calib_var.get()

            calib = CalibrationConfig(
                solid_frames=calib_enabled,
                preamble_frames=0,
                reference_cell_density=0,
            )

            self._v7_profile = profiles_mod.build_profile(
                name=f"lab_{grid}x{grid}_{palette_name}_seed{seed}",
                grid_size=grid,
                palette_name=palette_name,
                layout_name=layout,
                seed=seed,
                dwell_epochs=dwell,
                calibration=calib,
            )

            # Cross-validate
            self.lbl_v7_validation.config(text="Validation: running...")
            self.root.update()
            validate_or_fail(self._v7_profile)
            self._v7_validation_passed = True
            self.lbl_v7_validation.config(
                text=f"Validation: PASSED (canonical reference matched)",
                foreground=self.status_ok_color,
            )

            # Build sequence
            self._v7_sequence = profiles_mod.build_frame_sequence(self._v7_profile, frames)
            self._v7_total_frames = len(self._v7_sequence.frames)
            self._v7_frame_idx = 0
            self._v7_dwell_epochs = dwell

            # Compute dwell interval for timer-based pacing
            self._v7_dwell_interval_sec = (dwell / 60.0)

            # Create renderer
            marker_size = self.selected_size_var.get()
            self._v7_renderer = LabRenderer(marker_size=marker_size)

            # Prepare first frame
            frame = self._v7_sequence.frames[self._v7_frame_idx]
            self._v7_renderer.prepare_logical_frame(frame.symbol_matrix)
            self._v7_presents_in_dwell = 0

            # Show first frame in the display
            self._v7_present_current()

            self._v7_state = "READY"
            self.last_error = "None"
            self.lbl_last_err.config(text="Last Error: None")
            self._update_v7_ui()
            self._update_status_ui()

        except CrossValidationError as e:
            self._v7_validation_passed = False
            self._v7_state = "IDLE"
            self.lbl_v7_validation.config(
                text=f"Validation: FAILED — {e}",
                foreground=self.status_err_color,
            )
            self.lbl_last_err.config(text=f"Cross-validation error: {e}")
            self._update_v7_ui()
            self._update_status_ui()
            messagebox.showerror("Cross-Validation Failed", str(e))
        except Exception as e:
            self._v7_validation_passed = False
            self._v7_state = "IDLE"
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            self.lbl_v7_validation.config(text="Validation: ERROR")
            self._update_v7_ui()
            traceback.print_exc()
            messagebox.showerror("V7 Preparation Error", f"Failed to prepare V7 experiment:\n{self.last_error}")

    def _v7_present_current(self):
        """Present the cached V7 frame to the display."""
        if self._v7_renderer is None or self._v7_renderer.cached_frame_display is None:
            return
        if self.display_controller.screen is None:
            return

        frame_surface = self._v7_renderer.cached_frame_display
        screen = self.display_controller.screen
        canvas_w, canvas_h = screen.get_size()
        marker_size = self.display_controller.marker_size
        cx = (canvas_w - marker_size) // 2
        cy = (canvas_h - marker_size) // 2

        screen.fill((0, 0, 0))
        screen.blit(frame_surface, (cx, cy))
        pygame.display.flip()

    def _v7_start(self):
        if self._v7_state not in ("READY", "STOPPED"):
            return
        self._v7_state = "RUNNING"
        self._v7_last_tick = 0
        self._v7_presents_in_dwell = 0
        self._update_v7_ui()
        self._update_status_ui()

    def _v7_stop(self):
        self._v7_stop_internal()
        self._update_v7_ui()
        self._update_status_ui()

    def _v7_stop_internal(self):
        if self._v7_state == "RUNNING":
            self._v7_state = "STOPPED"

    def _v7_prev(self):
        if self._v7_state == "RUNNING" or self._v7_sequence is None:
            return
        self._v7_frame_idx = (self._v7_frame_idx - 1) % self._v7_total_frames
        self._v7_show_frame_at_idx()

    def _v7_next(self):
        if self._v7_state == "RUNNING" or self._v7_sequence is None:
            return
        self._v7_frame_idx = (self._v7_frame_idx + 1) % self._v7_total_frames
        self._v7_show_frame_at_idx()

    def _v7_reset(self):
        if self._v7_state == "RUNNING" or self._v7_sequence is None:
            return
        self._v7_frame_idx = 0
        self._v7_show_frame_at_idx()

    def _v7_show_frame_at_idx(self):
        """Prepare and present the frame at the current index."""
        if self._v7_renderer is None or self._v7_sequence is None:
            return
        frame = self._v7_sequence.frames[self._v7_frame_idx]
        self._v7_renderer.prepare_logical_frame(frame.symbol_matrix)
        self._v7_presents_in_dwell = 0
        self._v7_present_current()
        self._update_v7_ui()

    def _v7_advance_frame(self):
        """Move to next logical frame, wrapping around."""
        if self._v7_sequence is None:
            return
        self._v7_frame_idx = (self._v7_frame_idx + 1) % self._v7_total_frames
        frame = self._v7_sequence.frames[self._v7_frame_idx]
        self._v7_renderer.prepare_logical_frame(frame.symbol_matrix)
        self._v7_presents_in_dwell = 0

    def _update_v7_ui(self):
        state = self._v7_state
        has_seq = self._v7_sequence is not None

        self.lbl_v7_state.config(text=f"Experiment: {state}")

        if has_seq:
            max_idx = max(0, self._v7_total_frames - 1)
            self.lbl_v7_frame.config(
                text=f"Frame: {self._v7_frame_idx} / {max_idx} "
                     f"(dwell={self._v7_dwell_epochs} epochs, "
                     f"~{self._v7_dwell_interval_sec*1000:.0f} ms)")
        else:
            self.lbl_v7_frame.config(text="Frame: -")

        if self._v7_renderer is not None:
            t = self._v7_renderer.timings
            self.lbl_v7_timing.config(
                text=f"Prepare: {t.total_prepare_us}us "
                     f"(rgb={t.symbol_matrix_to_rgb_us}us "
                     f"surf={t.surface_creation_us}us "
                     f"scale={t.payload_scale_us}us "
                     f"compose={t.compose_us}us)")
        else:
            self.lbl_v7_timing.config(text="Timing: -")

        can_nav = has_seq and state in ("READY", "STOPPED")
        nav_state = "normal" if can_nav else "disabled"
        self.btn_v7_prev.config(state=nav_state)
        self.btn_v7_next.config(state=nav_state)
        self.btn_v7_reset.config(state=nav_state)

        can_start = state in ("READY", "STOPPED")
        self.btn_v7_start.config(state="normal" if can_start else "disabled")
        can_stop = state == "RUNNING"
        self.btn_v7_stop.config(state="normal" if can_stop else "disabled")

    # ═════════════════════════════════════════════════════════════════
    # Display (shared)
    # ═════════════════════════════════════════════════════════════════

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

            engine = self.engine_var.get()
            if engine == "V7 Development" and self._v7_renderer is not None:
                # Recreate renderer at new size
                self._v7_renderer = type(self).__new__(type(self))
                from superqr_desktop.v7_capacity_lab.lab_renderer import LabRenderer
                self._v7_renderer = LabRenderer(marker_size=marker_size)
                if self._v7_sequence is not None:
                    frame = self._v7_sequence.frames[self._v7_frame_idx]
                    self._v7_renderer.prepare_logical_frame(frame.symbol_matrix)
                    self._v7_present_current()
            elif self.sender.transfer_state == "SENDING" and self.sender.frames:
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
            self.lbl_mode_diag.config(text=f"Engine: V6 Stable | Pattern: {mode}")
            self.display_controller.render(mode)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self.renderer_status = "ERROR"
            self.lbl_status.config(text="ERROR", foreground=self.status_err_color)
            self.lbl_last_err.config(text=f"Last Error: {self.last_error}")
            traceback.print_exc()

    def copy_diagnostics(self):
        disp_idx = self._get_selected_display_index()
        target_sz = self.selected_size_var.get()
        scale_pct = (target_sz / CANONICAL_SIZE) * 100.0
        engine = self.engine_var.get()

        filename_str = self.sender.filename if self.sender.filename else "-"
        file_size_str = f"{self.sender.file_size} bytes" if self.sender.file_size else "-"
        package_size_str = f"{self.sender.package_size} bytes" if self.sender.package_size else "-"
        session_id_str = str(self.sender.session_id) if self.sender.session_id is not None else "-"
        current_frame_str = str(self.sender.current_frame_idx) if self.sender.total_frames > 0 else "-"
        total_frames_str = str(self.sender.total_frames) if self.sender.total_frames > 0 else "-"
        interval_str = f"{self.sender.interval_ms} ms"

        diag_info = (
            f"SuperQR Control Panel Diagnostics\n"
            f"=================================\n"
            f"Engine: {engine}\n"
            f"Contract SHA-256: {self.contract_hash}\n"
            f"Contract Verification: MATCHED\n"
            f"Renderer Status: {self.renderer_status}\n"
            f"Canonical Size: {CANONICAL_SIZE}x{CANONICAL_SIZE} px\n"
            f"Displayed Size: {target_sz}x{target_sz} px\n"
            f"Scale Percentage: {scale_pct:.1f}%\n"
            f"Target Display: {self.selected_display_str.get()} (Index {disp_idx})\n"
            f"Window Mode: {self.window_mode_var.get()}\n"
        )

        if engine == "V6 Stable":
            diag_info += (
                f"Pattern Mode: {self.mode_var.get()}\n"
                f"Transfer State: {self.sender.transfer_state}\n"
                f"Filename: {filename_str}\n"
                f"File Size: {file_size_str}\n"
                f"Package Size: {package_size_str}\n"
                f"Session ID: {session_id_str}\n"
                f"Current Frame ID: {current_frame_str}\n"
                f"Total Frames: {total_frames_str}\n"
                f"Frame Interval: {interval_str}\n"
            )
        else:
            v7_frame = f"{self._v7_frame_idx} / {max(0, self._v7_total_frames - 1)}" if self._v7_sequence else "-"
            diag_info += (
                f"V7 Grid: {self._v7_grid_var.get()}x{self._v7_grid_var.get()}\n"
                f"V7 Palette: {self._v7_palette_var.get()}\n"
                f"V7 Dwell: {self._v7_dwell_var.get()}\n"
                f"V7 Seed: {self._v7_seed_var.get()}\n"
                f"V7 Layout: {self._v7_layout_var.get()}\n"
                f"V7 Frames: {self._v7_frames_var.get()}\n"
                f"V7 Calibration: {'enabled' if self._v7_calib_var.get() else 'disabled'}\n"
                f"V7 Experiment: {self._v7_state}\n"
                f"V7 Validation: {'PASSED' if self._v7_validation_passed else '-'}\n"
                f"V7 Frame: {v7_frame}\n"
            )

        diag_info += (
            f"Last Error: {self.last_error}\n"
            f"{self.lbl_canvas.cget('text')}\n"
            f"{self.lbl_marker.cget('text')}\n"
            f"{self.lbl_active.cget('text')}\n"
            f"{self.lbl_grid.cget('text')}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(diag_info)
        messagebox.showinfo("Diagnostics Copied", "Diagnostic information copied to clipboard.")

    # ═════════════════════════════════════════════════════════════════
    # Main loop
    # ═════════════════════════════════════════════════════════════════

    def run(self):
        while True:
            try:
                self.root.update()
            except tk.TclError:
                break

            engine = self.engine_var.get()

            # ── V6 sender tick ──────────────────────────────────
            if engine == "V6 Stable" and self.sender.transfer_state == "SENDING" and self.sender.frames:
                now = time.monotonic()
                interval_sec = self.sender.interval_ms / 1000.0
                if now - self.sender_last_tick >= interval_sec:
                    self.sender_last_tick = now
                    current_idx = self.sender.advance_frame()
                    indexes = self.sender.frames[current_idx]
                    self.display_controller.render_indexes(indexes)
                    self._update_sender_ui()

            # ── V7 experiment tick ──────────────────────────────
            if engine == "V7 Development" and self._v7_state == "RUNNING" and self._v7_sequence is not None:
                now = time.monotonic()
                if now - self._v7_last_tick >= self._v7_dwell_interval_sec:
                    self._v7_last_tick = now
                    self._v7_advance_frame()
                    self._v7_present_current()
                    self._update_v7_ui()

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
