# SuperQR Desktop

Desktop sender and receiver for offline screen-to-camera file transfer.

> **Unfinished — development paused.** Production compatibility is retained;
> ColorGrid8/Macrochroma are research work, not a validated high-speed product.
> See [project status and known limitations](https://github.com/Aurasj/superqr-protocol/blob/main/docs/PROJECT_STATUS.md).

The application has four intentionally separate areas:

- **SEND** — production V40 QR file transfer with automatic safe mode, measured progress/speed, and repeated carousel recovery.
- **RECEIVE** — camera receive with byte verification and preview-before-save.
- **COLORGRID** — experimental file sender, with 240×216 or 336×288 at 30 FPS.
- **LAB / EXPERIMENTS** — configurable ColorGrid8 research carrier. Macrochroma code is also preserved as unfinished research.

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

    superqr-colorgrid8-lab --grid 240x216 --fps 30 --frames 0 --file C:\path\to\small.txt --windowed

`--frames 0` repeats continuously. The sender uses an 8-data + 1-XOR-parity carousel and bounded prefetching. It reports measured presentation FPS and render cost; printed channel budgets are estimates, not completed-file goodput. Use windowed mode for the fixed-phone setup.

The original v1 deterministic diagnostic carrier remains available from the same command by omitting `--file` and selecting a v1 grid/FPS.

Match the Android receiver profile: use **LAB → ColorGrid8 → 240×216 / 30 FPS**
for the example above. Android's dedicated **COLORGRID** screen is fixed at
336×288 / 30 FPS; select that grid on Desktop when using that screen.
Start with a small file. A detected frame or a theoretical channel rate is not
a verified file transfer. No 1–2 MB/s physical transfer is claimed.

`test_payloads/` contains optional local files and is not distributed. Use
**CHOOSE ANY FILE** in a fresh clone.

## Verification

    python -m pytest
    python -m compileall -q src
    python -m build

Optional tests require explicit setup: `SUPERQR_COLORGRID_DECODER` selects the
host C++ probe; `SUPERQR_COLORGRID_GPU_TESTS=1` enables Desktop GL shader tests
(PyOpenGL required); `SUPERQR_ANDROID_INTEROP=1` enables the sibling Android
complete-file interoperability test (JDK required). `SUPERQR_PERFORMANCE_TESTS=1`
enables the machine-dependent rendering budget. These are not physical camera tests.
Long-running exploratory scripts are preserved separately in [research/](research/README.md).

Canonical production and ColorGrid8 artifacts can be refreshed from a sibling protocol checkout:

    python scripts\sync_protocol_artifacts.py ..\superqr-protocol

The supported source layout is deliberately small: production UI/transfer/receive code under `src/superqr_desktop`, production V40 under `v7`, and ColorGrid8 under `lab`.
