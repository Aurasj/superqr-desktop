# SuperQR Desktop

SuperQR Desktop is the V7 sender and Phase 1 physical-PHY test application for offline screen-to-camera transfer.

The active Desktop runtime is **V7 only**. The packaged `visual_contract.json` still carries the validated V6-era carrier geometry (border, anchors, pilots and tracking layout), because V7 intentionally reuses that proven optical geometry. The old V6 sender, transport, renderer and display implementation are no longer part of the active Desktop runtime.

## Fresh clone — Windows

Recommended prerequisite: **Python 3.11** and Git for Windows.

```powershell
git clone https://github.com/Aurasj/superqr-desktop.git
cd superqr-desktop
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Run without activating the environment:

```powershell
.\.venv\Scripts\superqr-desktop.exe
```

or activate first:

```powershell
.\.venv\Scripts\Activate.ps1
superqr-desktop
```

Do not copy an old `.venv`; recreate it for a fresh checkout.

## Current application

The main window has two modes.

### TRANSFER

This is the V7 file sender.

1. Select the output monitor, marker size and window/fullscreen mode.
2. Select a V7 optical profile and frame interval.
3. Select a file. This **prepares** the carousel and previews frame 0; it does not claim that transfer is already running.
4. Press **START** to begin optical presentation.
5. Press **STOP** to stop while keeping the prepared file available for restart or manual Prev/Next inspection.

Active transfer presentation stays in the main process and uses the same SDL display and V7 renderer as the preview path. Frame cadence has its own monotonic deadline scheduler and is not driven by the slower Tk status-poll loop, so the 25/33/42 ms test presets are not artificially limited to 20 fps.

The transfer panel separates configured/theoretical rate from measured presentation cadence. Runtime status reports actual completed presents, measured presentation FPS and late presents.

The current conservative physical baseline remains the 40×40 / 4-color profile at 100 ms. Faster and denser profiles are measurement candidates, not guaranteed goodput claims.

### PHASE 1 TEST

This is the physical PHY campaign sender used while selecting the V7 optical layer.

It supports the canonical grid candidates and QR controls, including the `TEST FRAME` path for quickly checking acquisition on a phone before starting a full campaign.

Campaign presentation uses a separate process so Tk UI work cannot disturb the measurement presenter. The main SDL display is released before the campaign owns it and reclaimed after campaign completion or stop.

The Phase 1 implementation remains under `v7_capacity_lab` for now because it is active measurement code, not dead legacy. It should only be renamed/reorganized after the physical campaign path is frozen.

## PC camera receiver

The Phase 1 camera receiver can be launched directly:

```powershell
superqr-phy-camera
```

Useful CLI paths remain available:

```powershell
superqr-phy-camera --probe
superqr-phy-camera --headless --duration 20 --output pc-receiver.jsonl
superqr-phy-lab --list
superqr-phy-lab --profile mono_64x50_matched --dwell 3 --frames 256
superqr-phy-lab --profile qr_v27_l_safe --frames 256
superqr-phy-lab --campaign all --frames 256 --marker-size 600 --fullscreen --output sender.json
```

The receiver exposes the analyzed camera frame, acquisition/homography state, QR/run-sync state and receiver-side performance/error measurements. It can also export receiver JSONL/diagnostic evidence for replay.

## Runtime smoke tests

For workstation checks that require a real GUI/display:

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
  ui/                 main Tk shell
  transfer/           V7 transfer controller + cadence scheduling
  presentation/       version-neutral SDL display + V7 frame presenter
  diagnostics/        measured sender presentation telemetry
  campaign/           Phase 1 campaign controller
  contract/           packaged optical/modem contracts and vectors
  v7/                 production V7 sender/renderer/transport + dormant Phase 2 modem
  v7_capacity_lab/    active Phase 1 PHY/camera/replay laboratory
```

Phase 2 modem code remains present but is not being extended as part of the current Phase 1 cleanup.

## Contract and reference data

The repository is self-contained for normal run/test/package workflows. A sibling `superqr-protocol` checkout is optional for development cross-validation.

`contract/visual_contract.json` intentionally retains `contract_version: "v6"`: it is the validated optical carrier geometry reused by V7, not evidence that the Desktop application still has a V6 product mode.

Phase 1 profiles and deterministic vectors are packaged from the canonical protocol artifacts. Running the laboratory does not change the production wire format.

## Tests

```powershell
python -m pytest
```

CI runs the tests, builds wheel/sdist, installs the wheel into a fresh virtual environment, then checks the packaged visual carrier contract, V7 reference data, deterministic vectors, application import and Phase 1 artifact availability.
