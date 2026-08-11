"""Regression tests for Phase 1 campaign dwell pacing."""

from superqr_desktop.v7_capacity_lab.lab_display import (
    DwellState,
    LabDisplayController,
    REFERENCE_REFRESH_HZ,
)


def _advances_in_one_second(display_refresh_hz: float, dwell_epochs: int) -> int:
    dwell = DwellState(
        dwell_epochs=dwell_epochs,
        present_refresh_hz=display_refresh_hz,
    )
    return sum(
        1 for _ in range(round(display_refresh_hz))
        if dwell.record_present()
    )


def test_dwell_three_is_twenty_logical_fps_on_common_refresh_rates():
    assert REFERENCE_REFRESH_HZ == 60.0
    for refresh_hz in (60.0, 120.0, 144.0, 165.0, 240.0):
        assert _advances_in_one_second(refresh_hz, dwell_epochs=3) == 20


def test_dwell_two_is_thirty_logical_fps_on_common_refresh_rates():
    for refresh_hz in (60.0, 120.0, 144.0, 165.0, 240.0):
        assert _advances_in_one_second(refresh_hz, dwell_epochs=2) == 30


def test_high_refresh_uses_fractional_reference_epochs_not_three_raw_presents():
    dwell = DwellState(dwell_epochs=3, present_refresh_hz=144.0)

    # Three 144 Hz presents are only 1.25 canonical 60 Hz epochs, so the
    # logical optical frame must still be held.
    assert not dwell.record_present()
    assert not dwell.record_present()
    assert not dwell.record_present()

    advances = 0
    for _ in range(141):
        if dwell.record_present():
            advances += 1
    assert advances == 20


def test_unverified_present_interval_does_not_override_refresh_report():
    display = LabDisplayController(dwell_epochs=3)
    display.dwell.present_refresh_hz = 60.0

    display._observe_present_interval(1000.0 / 165.0)

    assert display.dwell.present_refresh_hz == 60.0


def test_verified_present_interval_overrides_stale_refresh_report():
    display = LabDisplayController(dwell_epochs=3)
    display.dwell.present_refresh_hz = 60.0
    display.diag.vsync_verified = True
    display.diag.actual_vsync_enabled = True

    advances = 0
    actual_refresh_hz = 165.0
    for _ in range(165):
        display._observe_present_interval(1000.0 / actual_refresh_hz)
        if display.dwell.record_present():
            advances += 1

    assert advances == 20
