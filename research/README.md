# Optional research scripts

These are preserved exploratory Macrochroma/FEC investigations, not release
gates or evidence of physical file-transfer speed. Some run thousands of trials
or allocate 100 MiB test files and may take a long time. They are intentionally
outside pytest's default `tests/` directory.

Keep a sibling `superqr-protocol` checkout and run a script explicitly, for example:

```powershell
.\.venv\Scripts\python.exe research\cauchy_mds.py
.\.venv\Scripts\python.exe research\hardening.py
```

The full research campaign has not been certified as passing in this unfinished
snapshot. Regular tests, including the retained Macrochroma regression tests,
remain under `tests/` and run with `python -m pytest`.
