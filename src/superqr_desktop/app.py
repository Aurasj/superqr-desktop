import tkinter as tk
from tkinter import ttk
import pygame
from superqr_desktop.contract.loader import load_contract
from superqr_desktop.v6.display import DisplayController

class ControlApp:
    def __init__(self, contract: dict, contract_hash: str):
        self.contract = contract
        self.contract_hash = contract_hash
        
        self.root = tk.Tk()
        self.root.title("V6 Static Renderer Control")
        self.root.geometry("+50+50")
        
        self.display_index = tk.IntVar(value=0)
        self.is_fullscreen = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="deterministic_random")
        
        ttk.Label(self.root, text=f"Contract SHA-256:\n{self.contract_hash}", font=('Courier', 9)).pack(padx=10, pady=5)
        
        metrics_frame = ttk.LabelFrame(self.root, text="Metrics")
        metrics_frame.pack(padx=10, pady=5, fill="x")
        self.lbl_canvas = ttk.Label(metrics_frame, text="")
        self.lbl_canvas.pack(anchor="w", padx=5, pady=2)
        self.lbl_marker = ttk.Label(metrics_frame, text="")
        self.lbl_marker.pack(anchor="w", padx=5, pady=2)
        self.lbl_active = ttk.Label(metrics_frame, text="")
        self.lbl_active.pack(anchor="w", padx=5, pady=2)
        self.lbl_grid = ttk.Label(metrics_frame, text="")
        self.lbl_grid.pack(anchor="w", padx=5, pady=2)
        
        settings_frame = ttk.LabelFrame(self.root, text="Display Settings")
        settings_frame.pack(padx=10, pady=5, fill="x")
        
        ttk.Label(settings_frame, text="Display Index:").grid(row=0, column=0, padx=5, pady=2, sticky="e")
        ttk.Spinbox(settings_frame, from_=0, to=10, textvariable=self.display_index, width=5).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        
        ttk.Checkbutton(settings_frame, text="Fullscreen", variable=self.is_fullscreen).grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        ttk.Button(settings_frame, text="Apply Display Settings", command=self.apply_display).grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        
        mode_frame = ttk.LabelFrame(self.root, text="Validation Mode")
        mode_frame.pack(padx=10, pady=5, fill="x")
        
        modes = [
            ("All Black Grid", "black"),
            ("All White Grid", "white"),
            ("Four-Color Checkerboard", "checkerboard"),
            ("Deterministic Random Grid", "deterministic_random")
        ]
        for text, val in modes:
            ttk.Radiobutton(mode_frame, text=text, value=val, variable=self.mode_var, command=self.render_marker).pack(anchor="w")

        pygame.init()
        self.display_controller = DisplayController(self.contract)
        self.apply_display()
        
    def apply_display(self):
        disp = self.display_index.get()
        fs = self.is_fullscreen.get()
        metrics = self.display_controller.setup_display(disp, fs)
        
        canvas_w, canvas_h = self.display_controller.screen.get_size()
        marker_size = self.display_controller.marker_size
        
        self.lbl_canvas.config(text=f"Canvas Pixel Size: {canvas_w}x{canvas_h}")
        self.lbl_marker.config(text=f"Rendered Marker Size: {marker_size}x{marker_size}")
        self.lbl_active.config(text=f"Bordered Active-Area Size: {metrics.active_width}x{metrics.active_height}")
        self.lbl_grid.config(text=f"Data-Grid Pixel Size: {metrics.grid_width}x{metrics.grid_height}")
        
        self.render_marker()
        
    def render_marker(self):
        mode = self.mode_var.get()
        self.display_controller.render(mode)

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
