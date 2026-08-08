# SuperQR Desktop (V6)

Standalone Python desktop application for rendering V6 SuperQR optical markers on screen for optical transmission testing.

## Features
- **V6 Static Optical Marker Renderer**: Renders outer border, 4 corner identity anchors, 4 calibration pilots, tracking blocks, sync cells, and 20x20 data grid.
- **Validation Modes**:
  - All-Black Grid
  - All-White Grid
  - Four-Color Checkerboard
  - Deterministic Random Grid (Xorshift32 seed 42)
- **Display Selection**: Fullscreen / Windowed display targeting on multiple monitors.

## Installation & Running

```bash
pip install -e .
python -m superqr_desktop.app
```

## V6 Sender (FROZEN)

The V6 sender behavior is frozen. No new pacing presets, adaptive timing, or coding-architecture changes will be accepted in V6. Future adaptive pacing and new coding architectures belong to V7.

### Frame pacing presets

| Preset (ms) | Notes |
|---|---|
| **100** | Conservative default — reliable baseline across varied hardware. |
| 200 / 500 | Slower presets for debugging or constrained receivers. |
| 75 | Slightly slower than 67 but robust on the current dev-phone/display setup. |
| 67 | Best observed throughput on the current dev-phone/display setup. |
| 50 | Produced a larger completion tail; not recommended as a default. |

The 67 ms and 75 ms presets exist because they performed well on the specific development phone and display used for benchmarking. These are **setup-specific observations**, not universal timing requirements. Actual optimal pacing depends on:

- Display refresh rate and frame-buffer scan-out
- Camera sensor cadence and exposure duration
- Rolling-shutter artifacts
- Receiver-side decode pipeline latency

### Sender loop

The sender cycles logical frames indefinitely while in the SENDING state (`current_frame_idx = (idx + 1) % total_frames`). V6 requires every logical frame to be displayed at least once, so the sender loops rather than stopping after one pass.

### Timing

- Frame advance is driven by `time.monotonic()` in the application loop.
- Each rendered frame persists on screen until the next logical advance.
- `pygame.display.flip()` is called once per logical frame advance — no mid-frame flips.

## Running Tests

```bash
pytest
```
