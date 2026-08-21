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

ColorGrid8 high-speed file transfer can be launched from the main LAB area or directly:

    superqr-colorgrid8-lab --grid 336x288 --fps 60 --frames 0 --file C:\path\to\file.bin --windowed

`--frames 0` repeats continuously. The sender uses an 8-data + 1-XOR-parity carousel and bounded prefetching. It reports measured presentation FPS and render cost; printed channel budgets are estimates, not completed-file goodput. Use windowed mode for the fixed-phone setup.

The original v1 deterministic diagnostic carrier remains available from the same command by omitting `--file` and selecting a v1 grid/FPS.

## Verification

    python -m pytest
    python -m compileall -q src
    python -m build

Canonical production and ColorGrid8 artifacts can be refreshed from a sibling protocol checkout:

    python scripts\sync_protocol_artifacts.py ..\superqr-protocol

The supported source layout is deliberately small: production UI/transfer/receive code under `src/superqr_desktop`, production V40 under `v7`, and ColorGrid8 under `lab`.
