from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.v7_capacity_lab.campaign import build_campaign


def test_v40_cadence_sweep_builds_four_qr_runs():
    runs = build_campaign("V40 cadence sweep", "mono_64x50_matched", 3, 256)

    assert [run.profile for run in runs] == ["qr_v40_l_ceiling"] * 4
    assert [run.target_fps for run in runs] == [24.0, 30.0, 40.0, 60.0]
    assert [run.frame_count for run in runs] == [256] * 4
    assert [run.dwell_epochs for run in runs] == [3] * 4


def test_canonical_runs_keep_profile_target_fps():
    runs = build_campaign("Selected profile", "qr_v40_l_ceiling", 3, 256)

    assert len(runs) == 1
    assert runs[0].profile == "qr_v40_l_ceiling"
    assert runs[0].target_fps is None


def test_controller_exposes_v40_cadence_sweep():
    ctrl = CampaignController()
    ctrl.set_preset("V40 cadence sweep")

    assert ctrl.run_count == 4
    assert [run.target_fps for run in ctrl.runs] == [24.0, 30.0, 40.0, 60.0]
