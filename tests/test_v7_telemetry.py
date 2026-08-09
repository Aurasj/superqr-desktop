from superqr_desktop.v7.telemetry import MEASUREMENT_SCHEMA_VERSION, PresentationTelemetry


def test_interval_rate_uses_intervals_not_event_count():
    t = PresentationTelemetry(window_size=16)
    t.reset(now_ns=1_000_000_000)
    t.record_present(0, 100, 1.0, 0.2, now_ns=1_000_000_000)
    t.record_present(1, 100, 1.2, 0.3, now_ns=1_100_000_000)
    snap = t.snapshot(now_ns=1_100_000_000)
    assert snap["measurement_schema_version"] == MEASUREMENT_SCHEMA_VERSION == 1
    assert snap["present_count"] == 2
    assert snap["present_measured_fps"] == 10.0
    assert snap["present_interval_ms_mean"] == 100.0
    assert snap["present_interval_ms_p95"] == 100.0


def test_late_present_threshold_is_more_than_25_percent_over_dwell():
    t = PresentationTelemetry(window_size=16)
    t.reset(now_ns=1_000_000_000)
    t.record_present(0, 100, 1.0, 0.2, now_ns=1_000_000_000)
    t.record_present(1, 100, 1.0, 0.2, now_ns=1_125_000_000)
    assert t.snapshot(now_ns=1_125_000_000)["late_present_count"] == 0
    t.record_present(2, 100, 1.0, 0.2, now_ns=1_251_000_000)
    assert t.snapshot(now_ns=1_251_000_000)["late_present_count"] == 1


def test_reset_starts_clean_measurement_run():
    t = PresentationTelemetry()
    old = t.run_id
    t.record_present(3, 100, 2.5, 0.4, now_ns=2_000_000_000)
    new = t.reset(now_ns=3_000_000_000)
    snap = t.snapshot(now_ns=3_000_000_000)
    assert new != old
    assert snap["present_count"] == 0
    assert snap["current_frame_id"] == -1
