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

## Running Tests

```bash
pytest
```
