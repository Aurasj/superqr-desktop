# SuperQR Desktop

SuperQR Desktop is the sender for offline screen-to-camera file transfer.

The product UI is **V7 only**. The physically validated V6 visual carrier remains packaged as the acquisition/debug foundation, but there is no separate V6/V7 application mode.

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

```bash
pip install -e .
superqr-desktop
```

or:

```bash
python -m superqr_desktop.app
```

Selecting a file starts the current transfer carousel immediately. `START / RESTART` restarts it explicitly.

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

```bash
pytest
```

CI also builds the wheel/sdist and verifies packaged V6/V7 resources without requiring a sibling `superqr-protocol` checkout.
