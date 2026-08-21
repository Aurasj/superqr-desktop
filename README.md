# SuperQR Desktop

Desktop sender and receiver for offline screen-to-camera file transfer.

The application has three intentionally separate areas:

- **SEND** — production V40 QR file transfer with automatic safe mode, measured progress/speed, and repeated carousel recovery.
- **RECEIVE** — camera receive with byte verification and preview-before-save.
- **LAB / EXPERIMENTS** — the retained ColorGrid8 research carrier only.

Production V40 is independent from LAB code and keeps the canonical wire contract packaged under superqr_desktop.contract.

## Setup on Windows

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    .\.venv\Scripts\python.exe -m pytest
    .\.venv\Scripts\superqr-desktop.exe

Do not copy a virtual environment between checkouts.

## ColorGrid8 LAB

ColorGrid8 can be launched from the main LAB area or directly:

    superqr-colorgrid8-lab --grid 168x144 --fps 30 --frames 256 --windowed

The sender reports measured presentation FPS and render cost. Capacity values printed by the LAB are estimates, not completed-file goodput. Use windowed mode for the fixed-phone setup.

## Verification

    python -m pytest
    python -m compileall -q src
    python -m build

Canonical production and ColorGrid8 artifacts can be refreshed from a sibling protocol checkout:

    python scripts\sync_protocol_artifacts.py ..\superqr-protocol

The supported source layout is deliberately small: production UI/transfer/receive code under `src/superqr_desktop`, production V40 under `v7`, and ColorGrid8 under `lab`.
