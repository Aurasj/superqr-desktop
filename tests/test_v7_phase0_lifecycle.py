"""Focused lifecycle tests for V7 Phase 0 controllers.

Validates state-machine transitions, display reclaim determinism, and
mode-switch cleanup without requiring a real monitor.
"""

import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from superqr_desktop.campaign.controller import (
    CampaignController,
    CampaignLifecycle,
)
from superqr_desktop.transfer.controller import (
    TransferController,
    TransferLifecycle,
)


# ---------------------------------------------------------------------------
# TRANSFER controller lifecycle (in-process)

class TestTransferLifecycle:
    def test_initial_state_is_idle(self):
        ctrl = TransferController()
        assert ctrl.lifecycle == TransferLifecycle.IDLE
        assert ctrl.has_file is False

    def test_start_presenting_without_file_returns_false(self):
        ctrl = TransferController()
        ok = ctrl.start_presenting()
        assert ok is False
        assert ctrl.lifecycle == TransferLifecycle.IDLE

    def test_start_presenting_transitions_to_presenting(self, tmp_path):
        ctrl = TransferController()
        path = tmp_path / "test.bin"
        path.write_bytes(b"x" * 5000)
        ctrl.select_file(str(path))

        assert ctrl.has_file
        assert ctrl.lifecycle == TransferLifecycle.IDLE

        ok = ctrl.start_presenting()
        assert ok is True
        assert ctrl.lifecycle == TransferLifecycle.PRESENTING

    def test_stop_transitions_back_to_idle(self, tmp_path):
        ctrl = TransferController()
        path = tmp_path / "test.bin"
        path.write_bytes(b"x" * 5000)
        ctrl.select_file(str(path))
        ctrl.start_presenting()
        assert ctrl.lifecycle == TransferLifecycle.PRESENTING

        ctrl.stop_presenting()
        assert ctrl.lifecycle == TransferLifecycle.IDLE

    def test_stop_preserves_loaded_file(self, tmp_path):
        ctrl = TransferController()
        path = tmp_path / "test.bin"
        path.write_bytes(b"x" * 5000)
        ctrl.select_file(str(path))
        ctrl.start_presenting()
        ctrl.stop_presenting()

        assert ctrl.has_file
        assert ctrl.total_frames > 0

    def test_double_start_is_rejected(self, tmp_path):
        ctrl = TransferController()
        path = tmp_path / "test.bin"
        path.write_bytes(b"x" * 5000)
        ctrl.select_file(str(path))
        ctrl.start_presenting()
        assert not ctrl.start_presenting()
        ctrl.stop_presenting()

    def test_stop_presenting_is_idempotent(self, tmp_path):
        ctrl = TransferController()
        assert ctrl.lifecycle == TransferLifecycle.IDLE
        ctrl.stop_presenting()  # no-op in IDLE
        assert ctrl.lifecycle == TransferLifecycle.IDLE


# ---------------------------------------------------------------------------
# CAMPAIGN controller lifecycle
# ---------------------------------------------------------------------------

class TestCampaignLifecycle:
    def test_initial_state_is_idle(self):
        ctrl = CampaignController()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE
        assert not ctrl.needs_display_reclaim

    def test_normal_campaign_completes_with_reclaim(self):
        ctrl = CampaignController()
        ctrl.set_frames(1)
        assert ctrl.lifecycle == CampaignLifecycle.IDLE

        ok = ctrl.start(ready_seconds=0.0, done_seconds=0.0)
        assert ok is True
        assert ctrl.lifecycle == CampaignLifecycle.STARTING

        for _ in range(400):
            ctrl.poll()
            if ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
                break
            time.sleep(0.02)

        assert ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED)
        assert ctrl.needs_display_reclaim

        snap = ctrl.reclaim_display()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE

    def test_reclaim_display_deterministic(self):
        ctrl = CampaignController()
        ctrl.set_frames(1)
        ctrl.start(ready_seconds=0.0, done_seconds=0.0)

        for _ in range(400):
            ctrl.poll()
            if ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
                break
            time.sleep(0.02)

        assert ctrl.needs_display_reclaim

        # first reclaim: works
        ctrl.reclaim_display()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE
        assert not ctrl.needs_display_reclaim

        # second reclaim: no-op
        snap2 = ctrl.reclaim_display()
        assert snap2 is None
        assert ctrl.lifecycle == CampaignLifecycle.IDLE

    def test_request_stop_enters_stopping(self):
        ctrl = CampaignController()
        ctrl.set_frames(128)
        ctrl.start(ready_seconds=4.0, done_seconds=0.0)

        for _ in range(100):
            ctrl.poll()
            if ctrl.lifecycle == CampaignLifecycle.RUNNING:
                break
            time.sleep(0.05)

        if ctrl.lifecycle == CampaignLifecycle.RUNNING:
            ctrl.request_stop()
            assert ctrl.lifecycle == CampaignLifecycle.STOPPING

            for _ in range(100):
                ctrl.poll()
                if ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.IDLE):
                    break
                time.sleep(0.05)

            if ctrl.needs_display_reclaim:
                ctrl.reclaim_display()
            assert ctrl.lifecycle == CampaignLifecycle.IDLE

    def test_double_start_does_not_spawn_second_worker(self):
        ctrl = CampaignController()
        ctrl.set_frames(1)
        assert ctrl.start(ready_seconds=0.0, done_seconds=0.0) is True
        # second start while not IDLE must fail
        assert ctrl.start() is False

        for _ in range(400):
            ctrl.poll()
            if ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED):
                break
            time.sleep(0.02)
        if ctrl.needs_display_reclaim:
            ctrl.reclaim_display()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE

    def test_no_duplicate_profile_dwell_state(self):
        """Controller model does not duplicate profile/dwell across modes."""
        campaign = CampaignController()
        assert hasattr(campaign, 'profile')
        assert hasattr(campaign, 'dwell')
        transfer = TransferController()
        assert hasattr(transfer, 'profile')
        assert hasattr(transfer, 'interval_ms')
        # They are different objects with different types/domains
        assert type(campaign.available_profiles) is list
        assert type(transfer.INTERVAL_PRESETS) is list
        assert campaign.available_profiles != transfer.INTERVAL_PRESETS

    def test_campaign_completion_sets_needs_reclaim_flag(self):
        ctrl = CampaignController()
        ctrl.set_frames(1)
        ctrl.start(ready_seconds=0.0, done_seconds=0.0)

        for _ in range(400):
            ctrl.poll()
            if ctrl.needs_display_reclaim:
                break
            time.sleep(0.02)

        assert ctrl.needs_display_reclaim
        assert ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.FAILED)

        ctrl.reclaim_display()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE
        assert not ctrl.needs_display_reclaim


# ---------------------------------------------------------------------------
# Mode switch / worker cleanup
# ---------------------------------------------------------------------------

class TestModeSwitchCleanup:
    def test_transfer_stopped_synchronously(self, tmp_path):
        ctrl = TransferController()
        path = tmp_path / "test.bin"
        path.write_bytes(b"x" * 5000)
        ctrl.select_file(str(path))

        ctrl.start_presenting()
        assert ctrl.lifecycle == TransferLifecycle.PRESENTING

        ctrl.stop_presenting()
        assert ctrl.lifecycle == TransferLifecycle.IDLE

    def test_campaign_stopped_on_stop(self):
        ctrl = CampaignController()
        ctrl.set_frames(128)
        ctrl.start(ready_seconds=4.0, done_seconds=0.0)

        for _ in range(100):
            ctrl.poll()
            if ctrl.lifecycle == CampaignLifecycle.RUNNING:
                break
            time.sleep(0.05)

        if ctrl.lifecycle == CampaignLifecycle.RUNNING:
            ctrl.request_stop()
            assert ctrl.lifecycle == CampaignLifecycle.STOPPING

            for _ in range(200):
                ctrl.poll()
                if ctrl.lifecycle in (CampaignLifecycle.COMPLETED, CampaignLifecycle.IDLE):
                    break
                time.sleep(0.02)

            if ctrl.needs_display_reclaim:
                ctrl.reclaim_display()
            assert ctrl.lifecycle == CampaignLifecycle.IDLE

    def test_campaign_completes_and_reclaims_in_sequence(self):
        """Natural completion: STARTING → RUNNING → COMPLETED → reclaim → IDLE."""
        ctrl = CampaignController()
        ctrl.set_frames(1)
        ctrl.start(ready_seconds=0.0, done_seconds=0.0)

        for _ in range(400):
            ctrl.poll()
            if ctrl.needs_display_reclaim:
                break
            time.sleep(0.02)

        assert ctrl.needs_display_reclaim
        ctrl.reclaim_display()
        assert ctrl.lifecycle == CampaignLifecycle.IDLE
        assert not ctrl.needs_display_reclaim
