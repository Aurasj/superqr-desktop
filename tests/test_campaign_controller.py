from __future__ import annotations

from superqr_desktop.campaign.controller import CampaignController, CampaignLifecycle


class _FakeWorker:
    def __init__(self) -> None:
        self.request_stop_calls = 0
        self.stop_calls = 0

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def test_close_synchronously_stops_and_releases_active_worker() -> None:
    controller = CampaignController()
    worker = _FakeWorker()
    controller._worker = worker  # type: ignore[assignment]
    controller._lifecycle = CampaignLifecycle.RUNNING

    controller.close()

    assert worker.request_stop_calls == 1
    assert worker.stop_calls == 1
    assert controller._worker is None
    assert controller.lifecycle == CampaignLifecycle.IDLE

    # Application shutdown can call close defensively more than once.
    controller.close()
    assert worker.request_stop_calls == 1
    assert worker.stop_calls == 1
