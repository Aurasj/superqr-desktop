# SuperQR Desktop

Desktop sender for the SuperQR offline screen-to-camera data-transfer project.

The application reads a file, packages it into protocol frames and renders the optical sequence full-screen for an Android receiver to capture with its camera.

## Status

SuperQR is experimental and under active development. The current user-facing sender follows the V7 development line while reusing the V6 carrier as a stable acquisition/reference layer.

The reliable measurement baseline is currently 40×40 cells with a 4-color palette and 100 ms frame dwell. Denser profiles are available for testing but are not universal speed claims.

## Requirements

- Python 3.9+; Python 3.11 is recommended
- Windows is the primary tested desktop environment

## Setup

```powershell
git clone https://github.com/Aurasj/superqr-desktop.git
cd superqr-desktop
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the application:

```powershell
.\.venv\Scripts\superqr-desktop.exe
```

or, with the environment activated:

```powershell
python -m superqr_desktop.app
```

## What is implemented

- V7 adaptive optical profiles
- 4-color baseline with experimental higher-density profiles
- V6-based carrier, anchors and geometry
- optical profile identification for receiver auto-detection
- streaming file slicing
- CRC32-protected pre-FEC transport
- sender timing and presentation telemetry
- JSON metric export for physical benchmark runs

## Project structure

```text
src/superqr_desktop/
  app.py              Application entry point and UI
  contract/           Packaged protocol/visual contract
  v6/                 Frozen carrier/reference implementation
  v7/                 Current sender, renderer and transport
  v7_capacity_lab/    Experimental capacity/PHY tooling
scripts/               Contract synchronization tools
tests/                 Unit and packaging tests
```

The canonical shared protocol lives in `Aurasj/superqr-protocol`. Packaged contract files in this repository exist so the application can build and run independently.

## Measurements

Configured frame rate and theoretical payload capacity are not the same as real file throughput. Sender telemetry records actual presentation cadence; receiver-side camera, analysis and decoded payload rates are measured separately by the Android application.

## Contributing

See `CONTRIBUTING.md`.

## License

MIT License. See `LICENSE`.
