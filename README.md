# SuperQR Desktop

Desktop sender and physical-layer research tools for SuperQR offline screen-to-camera transfer.

`main` is the integrated branch. The user-facing application keeps the production file-transfer path separate from experimental PHY laboratories.

## Production transfer

The **TRANSFER** tab sends arbitrary files as a repeating V7 QR carousel. The current production profiles use QR Version 40 with either L or M error correction at 15, 20, or 30 FPS. The default mode is the conservative/best-tested V40-L 15 FPS profile.

The sender:

- packages file metadata and payload with the V7 transfer framing;
- reads large files without loading the whole file into RAM;
- prepares QR frames on a background producer thread;
- presents frames on a monotonic cadence rather than the Tk status-poll cadence;
- permutes later carousels while preserving frame IDs so a fixed camera/display phase does not repeatedly lose the same frame;
- caches a complete prepared QR carousel only when it fits a strict 64 MiB memory budget; larger transfers remain bounded streaming.

The Android receiver decides when it has all unique frames, verifies the reconstructed file CRC, and saves the result.

## PHY laboratories

The **LAB** tab and dedicated CLI tools are experimental measurement surfaces. They do **not** silently change the production transfer wire format.

The repository contains preserved and active research for grid carriers, QR controls, ChromaQR, advanced/multi-lane candidates, Chroma4/ShapeGrid, and ColorGrid8. Treat theoretical or estimated LAB rates as research results until repeatable physical testing validates them.

ColorGrid8 has its own isolated sender:

```powershell
superqr-colorgrid8-lab --grid 128x96 --fps 15 --frames 0 --display 0
```

The denser target/stress profiles can then be selected explicitly, for example:

```powershell
superqr-colorgrid8-lab --grid 168x144 --fps 30 --frames 0 --display 0
```

## Fresh clone — Windows

Recommended: **Python 3.11** and Git for Windows.

```powershell
git clone https://github.com/Aurasj/superqr-desktop.git
cd superqr-desktop
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Run the desktop app without activating the environment:

```powershell
.\.venv\Scripts\superqr-desktop.exe
```

or activate it first:

```powershell
.\.venv\Scripts\Activate.ps1
superqr-desktop
```

Do not copy an old `.venv`; recreate it for a fresh checkout.

## Basic end-to-end use

1. Start SuperQR Android on **RECEIVE**.
2. In SuperQR Desktop, select the output display.
3. Keep the default V40-L 15 FPS mode for the first test.
4. Select a file.
5. Press **START TRANSFER** and point the phone at the displayed QR stream.
6. Let Android reach **File received ✓**, then open the saved file and compare it with the source.

After the baseline works, test 20/30 FPS and the V40-M modes separately.

## Additional LAB tools

```powershell
superqr-phy-camera --probe
superqr-phy-camera --headless --duration 20 --output pc-receiver.jsonl
superqr-phy-lab --list
superqr-phy-lab --profile mono_64x50_matched --dwell 3 --frames 256
superqr-phy-lab --profile qr_v27_l_safe --frames 256
superqr-colorgrid8-lab --grid 128x96 --fps 15 --frames 0
```

Workstation GUI/display smoke tests:

```powershell
python scripts/phy_lab_ui_runtime_smoke.py --full-app
python scripts/phy_lab_ui_runtime_smoke.py --full-app --frames 256 --stop-after 5
python scripts/phy_camera_ui_runtime_smoke.py
```

The camera smoke requires a physical webcam.

## Architecture

```text
src/superqr_desktop/
  app.py
  ui/                 Tk application shell
  transfer/           production transfer controller + cadence scheduling
  presentation/       SDL output + production QR preparation/presentation
  campaign/           LAB campaign lifecycle/controller
  contract/           packaged shared contracts and vectors
  v7/                 V7 transport/package/sender + preserved modem work
  v7_capacity_lab/    experimental PHY, camera, replay, and ColorGrid8 tooling
```

The validated V6-era visual carrier geometry remains packaged where V7 LAB/reference components intentionally reuse it. That does not mean the application exposes a V6 production mode.

## Tests and packaging

```powershell
python -m pytest
python -m build
```

CI runs the test suite, builds wheel/sdist, installs the wheel into a clean virtual environment, and smoke-checks packaged contracts, production V7 behavior, LAB reference data, and application imports.

Canonical shared protocol artifacts live in `superqr-protocol`; mirrored JSON assets in this repository should remain byte-for-byte synchronized where practical.
