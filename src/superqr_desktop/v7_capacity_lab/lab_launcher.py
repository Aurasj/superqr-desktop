"""V7 Capacity Lab pre-launch configuration window.

A minimal Tkinter UI that collects experiment settings before the
physical measurement loop begins. The Tkinter window is fully destroyed
before the Pygame event loop starts — no concurrent UI loops.

Usage:
    python -m superqr_desktop.v7_capacity_lab.lab_launcher

The CLI (lab_runner) continues to work independently:
    python -m superqr_desktop.v7_capacity_lab.lab_runner [options]
"""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# Display detection (lightweight — no window created)
# ---------------------------------------------------------------------------

GRID_CHOICES = [40, 48, 56, 64, 72, 80, 96]
PALETTE_CHOICES = ["v6_reference_4", "candidate_8_a"]
DWELL_CHOICES = [2, 3, 4]
LAYOUT_CHOICES = ["single", "2x2"]

DEFAULT_SEED = 42
DEFAULT_FRAMES = 100
DEFAULT_MARKER_SIZE = 1000


def _detect_displays() -> list[dict]:
    """Quick scan of available displays without creating a window.

    Uses a transient pygame.display init/quit cycle so no persistent
    pygame state remains before Tkinter starts.
    """
    try:
        import pygame
    except ImportError:
        return [{"index": 0, "label": "Display 1 (1920x1080)", "width": 1920, "height": 1080}]

    try:
        pygame.display.init()
        try:
            sizes = pygame.display.get_desktop_sizes()
            displays = []
            for idx, (w, h) in enumerate(sizes):
                displays.append({
                    "index": idx,
                    "label": f"Display {idx + 1} ({w}x{h})",
                    "width": w,
                    "height": h,
                })
            if displays:
                return displays
        except Exception:
            pass
        finally:
            pygame.display.quit()
    except Exception:
        pass

    return [{"index": 0, "label": "Display 1 (1920x1080)", "width": 1920, "height": 1080}]


# ---------------------------------------------------------------------------
# Configuration window
# ---------------------------------------------------------------------------

class LabLauncher:
    """Tkinter pre-launch configuration window.

    Destroyed before the Pygame lab starts — never runs concurrently.
    """

    def __init__(self):
        self.displays = _detect_displays()

        self.root = tk.Tk()
        self.root.title("SuperQR V7 Capacity Lab — Configuration")
        self.root.resizable(False, False)

        # Style
        self.bg = "#1e1e2e"
        self.fg = "#cdd6f4"
        self.accent = "#89b4fa"
        self.entry_bg = "#313244"

        self.root.configure(bg=self.bg)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=self.bg, foreground=self.fg, font=("Segoe UI", 10))
        style.configure("TLabel", background=self.bg, foreground=self.fg)
        style.configure("TFrame", background=self.bg)
        style.configure("TLabelframe", background=self.bg, foreground=self.accent,
                        bordercolor="#45475a", relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=self.bg, foreground=self.accent,
                        font=("Segoe UI", 10, "bold"))
        style.configure("TCombobox", fieldbackground=self.entry_bg, background=self.entry_bg,
                        foreground=self.fg, selectbackground="#45475a")
        style.configure("TButton", background="#45475a", foreground=self.fg,
                        font=("Segoe UI", 11, "bold"), borderwidth=0)
        style.map("TButton", background=[("active", "#585b70"), ("pressed", "#6c7086")])
        style.configure("Start.TButton", background="#89b4fa", foreground="#1e1e2e",
                        font=("Segoe UI", 12, "bold"))
        style.map("Start.TButton", background=[("active", "#b4d0fb"), ("pressed", "#74a8f7")])
        style.configure("TCheckbutton", background=self.bg, foreground=self.fg)

        # Variables
        self._grid_var = tk.StringVar(value=str(GRID_CHOICES[0]))
        self._palette_var = tk.StringVar(value=PALETTE_CHOICES[0])
        self._dwell_var = tk.StringVar(value=str(DWELL_CHOICES[0]))
        self._seed_var = tk.StringVar(value=str(DEFAULT_SEED))
        self._layout_var = tk.StringVar(value=LAYOUT_CHOICES[0])
        self._frames_var = tk.StringVar(value=str(DEFAULT_FRAMES))
        self._marker_var = tk.StringVar(value=str(DEFAULT_MARKER_SIZE))
        self._display_var = tk.StringVar()

        display_labels = [d["label"] for d in self.displays]
        if display_labels:
            self._display_var.set(display_labels[0])

        self._calib_var = tk.BooleanVar(value=True)
        self._fullscreen_var = tk.BooleanVar(value=False)
        self._hud_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

        # Center on screen
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        # Header
        header = tk.Label(main, text="SuperQR V7 Capacity Lab",
                          font=("Segoe UI", 14, "bold"),
                          bg=self.bg, fg=self.accent)
        header.pack(anchor="w", pady=(0, 2))
        sub = tk.Label(main, text="Pre-Launch Experiment Configuration",
                       font=("Segoe UI", 9), bg=self.bg, fg="#a6adc8")
        sub.pack(anchor="w", pady=(0, 12))

        # Grid / Palette / Dwell row
        row1 = ttk.Frame(main)
        row1.pack(fill="x", pady=3)
        self._labeled_combo(row1, "Grid", GRID_CHOICES, self._grid_var).pack(
            side="left", padx=(0, 12))
        self._labeled_combo(row1, "Palette", PALETTE_CHOICES, self._palette_var).pack(
            side="left", padx=(0, 12))
        self._labeled_combo(row1, "Dwell", DWELL_CHOICES, self._dwell_var).pack(
            side="left")

        # Seed / Layout row
        row2 = ttk.Frame(main)
        row2.pack(fill="x", pady=3)
        self._labeled_entry(row2, "Seed", self._seed_var).pack(
            side="left", padx=(0, 12))
        self._labeled_combo(row2, "Layout", LAYOUT_CHOICES, self._layout_var).pack(
            side="left", padx=(0, 12))
        self._labeled_entry(row2, "Frames", self._frames_var, width=6).pack(
            side="left")

        # Marker / Display row
        row3 = ttk.Frame(main)
        row3.pack(fill="x", pady=3)
        self._labeled_entry(row3, "Marker (px)", self._marker_var, width=6).pack(
            side="left", padx=(0, 12))
        display_labels = [d["label"] for d in self.displays]
        self._labeled_combo(row3, "Display", display_labels, self._display_var).pack(
            side="left")

        # Checkboxes
        chk_frame = ttk.Frame(main)
        chk_frame.pack(fill="x", pady=(10, 4))
        ttk.Checkbutton(chk_frame, text="Calibration frames", variable=self._calib_var).pack(
            side="left", padx=(0, 16))
        ttk.Checkbutton(chk_frame, text="Fullscreen", variable=self._fullscreen_var).pack(
            side="left", padx=(0, 16))
        ttk.Checkbutton(chk_frame, text="HUD", variable=self._hud_var).pack(
            side="left")

        # Validation message area
        self._msg_var = tk.StringVar()
        self._msg_label = tk.Label(
            main, textvariable=self._msg_var,
            font=("Segoe UI", 9), bg=self.bg, fg="#f38ba8",
            wraplength=400, justify="left",
        )
        self._msg_label.pack(fill="x", pady=(10, 4))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(6, 0))

        start_btn = ttk.Button(btn_frame, text="START LAB", style="Start.TButton",
                               command=self._on_start_lab)
        start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        exit_btn = ttk.Button(btn_frame, text="EXIT", command=self._on_exit)
        exit_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _labeled_combo(self, parent, label: str, values: list, variable: tk.StringVar):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=label).pack(anchor="w")
        cb = ttk.Combobox(frame, textvariable=variable, values=values,
                          state="readonly", width=16)
        cb.pack()
        return frame

    def _labeled_entry(self, parent, label: str, variable: tk.StringVar, width: int = 8):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=label).pack(anchor="w")
        entry = tk.Entry(frame, textvariable=variable, width=width,
                         bg=self.entry_bg, fg=self.fg,
                         insertbackground=self.fg, relief="flat")
        entry.pack(pady=1)
        return frame

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _get_display_index(self) -> int:
        sel = self._display_var.get()
        for d in self.displays:
            if d["label"] == sel:
                return d["index"]
        return 0

    def _validate(self) -> list[str]:
        """Validate all settings. Returns list of error messages (empty = valid)."""
        errors = []

        try:
            grid = int(self._grid_var.get())
            if grid not in GRID_CHOICES:
                errors.append(f"Grid must be one of {GRID_CHOICES}, got {grid}")
        except ValueError:
            errors.append("Grid must be an integer")

        try:
            seed = int(self._seed_var.get())
            if seed == 0:
                errors.append("Seed must be non-zero")
        except ValueError:
            errors.append("Seed must be an integer")

        try:
            frames = int(self._frames_var.get())
            if frames < 1:
                errors.append("Frames must be at least 1")
        except ValueError:
            errors.append("Frames must be an integer")

        try:
            marker = int(self._marker_var.get())
            if marker < 100:
                errors.append("Marker size must be at least 100 px")
        except ValueError:
            errors.append("Marker size must be an integer")

        return errors

    def _build_args(self) -> argparse.Namespace:
        """Construct an argparse.Namespace from GUI selections."""
        return argparse.Namespace(
            grid=int(self._grid_var.get()),
            palette=self._palette_var.get(),
            dwell=int(self._dwell_var.get()),
            seed=int(self._seed_var.get()),
            layout=self._layout_var.get(),
            frames=int(self._frames_var.get()),
            marker_size=int(self._marker_var.get()),
            display=self._get_display_index(),
            fullscreen=self._fullscreen_var.get(),
            no_calibration=not self._calib_var.get(),
            hud=self._hud_var.get(),
        )

    def _on_start_lab(self) -> None:
        """Validate, destroy Tkinter, and launch the Pygame lab."""
        errors = self._validate()
        if errors:
            self._msg_var.set("\n".join(errors))
            return

        self._msg_var.set("")
        args = self._build_args()

        # Destroy Tkinter before any Pygame event loop starts
        self.root.destroy()

        # Now safe to start the single-threaded Pygame measurement loop
        from superqr_desktop.v7_capacity_lab.lab_runner import run_lab
        run_lab(args)

    def _on_exit(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        """Show the configuration window."""
        self.root.mainloop()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main() -> None:
    launcher = LabLauncher()
    launcher.run()


if __name__ == "__main__":
    main()
