# SuperQR Desktop

SuperQR Desktop is the sender for offline screen-to-camera file transfer.

The product UI is **V7 only**. The physically validated V6 visual carrier remains packaged as the acquisition/debug foundation, but there is no separate V6/V7 application mode.

## Fresh clone — Windows

Recommended prerequisite: **Python 3.11** and Git for Windows.

```powershell
git clone https://github.com/Aurasj/superqr-desktop.git
cd superqr-desktop
```

Create a **new virtual environment** for this checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Verify the fresh clone:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run SuperQR Desktop without activating the environment:

```powershell
.\.venv\Scripts\superqr-desktop.exe
```

Or activate it first:

```powershell
.\.venv\Scripts\Activate.ps1
superqr-desktop
```

If PowerShell blocks activation, activation is optional; use the direct `.venv\Scripts\...` commands above.

**Do not copy an old `.venv`.** It is local/generated state, is ignored by Git, and should be recreated after a fresh clone.

This repository is self-contained for normal run/test/package workflows. It includes the packaged V6 contract and V7 Capacity Lab reference data; a sibling `superqr-protocol` checkout is optional for development cross-validation only.

## Current V7 baseline

- adaptive optical profiles (40/48/56/64+ grids, 4- and experimental 8-color palettes);
- current reliable measurement default: **40×40 / 4 colors / 100 ms**;
- V6-proven outer carrier, anchors, pilots and geometry;
- profile ID announced optically so Android AUTO can follow the sender;
- streaming file slicing instead of precomputing the full optical carousel;
- CRC32-protected current pre-FEC transport;
- V7.0 sender presentation telemetry with measured cadence and JSON export.

Higher-density and 8-color profiles are experiments, not universal speed claims.

## Run

With the virtual environment active:

```powershell
superqr-desktop
```

or:

```powershell
python -m superqr_desktop.app
```

Selecting a file starts the current transfer carousel immediately. `START / RESTART` restarts it explicitly.

## V7 Phase 1 PHY laboratory

The laboratory transmitter is separate from the production V7 sender:

```powershell
superqr-phy-lab --list
superqr-phy-lab --profile mono_64x50_matched --dwell 3 --frames 256
superqr-phy-lab --profile qr_v27_l_safe --frames 256
```

Profiles and deterministic vectors come from the canonical
`superqr-protocol/test-vectors/v7-phy-selection/phase1_manifest.json`. Running
the lab does not select or change the production V7 wire format.

## Measurement terminology

The LIVE panel deliberately separates:

- configured/nominal logical FPS;
- measured presentation-completion FPS;
- theoretical raw/payload ceilings.

Theoretical rate is **not** actual file goodput. Receiver-side camera FPS, analysis FPS, useful decoded FPS and completed-file goodput are separate measurements defined by the protocol V7.0 measurement contract.

Use **Export metrics JSON** to save the Desktop side of a benchmark run.

## Advanced carrier debug

The Advanced section renders V6 carrier diagnostic patterns only. It is not a second protocol/product mode.

## V6 status

V6 remains frozen in protocol history as the validated compatibility/reference release. New transport, FEC, timing, compression and adaptive-PHY work belongs to V7 and later.

## Tests

```powershell
python -m pytest
```

CI checks out this repository from scratch, installs it, runs the test suite, builds wheel/sdist, creates a fresh virtual environment, installs the packaged wheel and verifies packaged V6/V7 resources without a sibling `superqr-protocol` checkout.
