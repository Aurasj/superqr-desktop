# superqr-desktop

Standalone SuperQR desktop application.

Python package root:
`src/superqr_desktop`

Shared protocol semantics come from `superqr-protocol`.

The vendored `visual_contract.json` is a synchronized snapshot of the canonical protocol contract, not an independent source of truth.

Do not silently modify shared protocol semantics to make Desktop behavior convenient.

Keep V6 rendering/transmission code modular.

## Verification

Prefer the smallest relevant pytest test first.

Full pytest is acceptable when useful because the suite is small.

Do not build/package installers unless explicitly requested.

After changes, review the final diff and report any verification still requiring the user.