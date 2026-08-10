"""Interactive-runtime smoke for the PC Camera PHY Receiver.

This is intentionally not part of CI because it requires a physical camera.
It proves that Tk remains responsive through asynchronous probing, camera
startup, analyzed-frame preview delivery, Stop, and shutdown.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import time
import tkinter as tk

from superqr_desktop.v7_capacity_lab.camera_receiver_ui import CameraReceiverWindow


def main() -> None:
    root = tk.Tk()
    window = CameraReceiverWindow(root)
    started = time.monotonic()
    start_requested = False
    result = None

    def poll() -> None:
        nonlocal start_requested, result
        elapsed = time.monotonic() - started
        if not start_requested and window.state_var.get() == "CAMERA READY":
            start_requested = True
            window.start()
        snapshot = window.worker.snapshot() if window.worker else None
        if snapshot and snapshot.analyzed_frames >= 10:
            result = snapshot
            window.stop()
            root.after(100, root.destroy)
            return
        if elapsed >= 35:
            window.close()
            raise RuntimeError("camera UI did not deliver ten analyzed frames within 35 seconds")
        root.after(50, poll)

    root.after(50, poll)
    root.mainloop()
    if result is None:
        raise RuntimeError("camera UI closed without a receiver snapshot")
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
