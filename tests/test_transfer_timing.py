from superqr_desktop.transfer.timing import TransferCadenceClock


def test_25ms_deadline_is_not_limited_by_ui_poll_rate():
    clock = TransferCadenceClock()
    clock.start(10.0, 25)
    assert abs(clock.deadline - 10.025) < 1e-9
    assert clock.delay_ms(10.0) == 26 or clock.delay_ms(10.0) == 25
    assert not clock.due(10.024)
    assert clock.due(10.025)


def test_small_callback_jitter_preserves_deadline_cadence():
    clock = TransferCadenceClock()
    clock.start(1.0, 25)
    clock.mark_presented(1.026, 25)
    assert abs(clock.deadline - 1.05) < 1e-9


def test_long_stall_rebases_without_catch_up_burst():
    clock = TransferCadenceClock()
    clock.start(2.0, 25)
    clock.mark_presented(2.200, 25)
    assert abs(clock.deadline - 2.225) < 1e-9
    assert not clock.due(2.201)


def test_live_interval_change_reschedules_from_now():
    clock = TransferCadenceClock()
    clock.start(3.0, 100)
    clock.reschedule(3.020, 33)
    assert abs(clock.deadline - 3.053) < 1e-9


def test_stop_clears_deadline():
    clock = TransferCadenceClock()
    clock.start(4.0, 42)
    assert clock.running
    clock.stop()
    assert not clock.running
    assert clock.deadline is None
