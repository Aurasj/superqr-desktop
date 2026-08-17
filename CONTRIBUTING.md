# Contributing

Contributions are welcome, especially focused fixes, reproducible measurements and improvements that keep Desktop behavior aligned with the shared protocol.

## Development

Set up the project as described in `README.md`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Keep application changes inside `superqr-desktop`. Shared frame formats, protocol constants and cross-platform behavior should be defined in `superqr-protocol` first.

## Pull requests

Keep changes focused and include:

- a short description of the problem;
- the approach used;
- tests or measurements performed;
- any hardware/display assumptions relevant to optical results.

Do not present theoretical capacity as measured transfer speed. Physical performance claims should include the sender display, receiver device and test conditions.
