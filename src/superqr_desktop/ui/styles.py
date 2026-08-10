"""Shared dark theme and ttk style configuration."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Color scheme
BG = "#11131a"
PANEL = "#191d28"
PANEL2 = "#222838"
BORDER = "#30384c"
TEXT = "#edf2ff"
MUTED = "#99a4bd"
ACCENT = "#7cb7ff"
GOOD = "#7ee787"
WARN = "#f2cc60"
BAD = "#ff7b72"


def setup_styles(root: tk.Tk) -> ttk.Style:
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 9))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 17, "bold"))
    style.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
    style.configure("TButton", background=PANEL2, foreground=TEXT, bordercolor=BORDER,
                    font=("Segoe UI", 9, "bold"), padding=7)
    style.map("TButton", background=[("active", "#30384c"), ("pressed", "#3b455d")])
    style.configure("Accent.TButton", background="#245b8f", foreground="white",
                    font=("Segoe UI", 10, "bold"), padding=9)
    style.map("Accent.TButton", background=[("active", "#2f74b5")])
    style.configure("Mode.TButton", font=("Segoe UI", 10, "bold"), padding=10)
    style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=TEXT)
    style.configure("TRadiobutton", background=PANEL, foreground=TEXT)
    style.configure("TCheckbutton", background=BG, foreground=TEXT)
    return style


def card(parent, title: str) -> ttk.Frame:
    outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
    outer.pack(fill="x", pady=5)
    ttk.Label(outer, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
    return outer
