from superqr_desktop.campaign.controller import CampaignController
from superqr_desktop.campaign.qr_ecc_map import build_qr_ecc_map_runs
from superqr_desktop.v7_capacity_lab.phase1_profiles import (
    build_qr_control_payload,
    build_qr_matrix,
    profile_id,
    qr_controls,
    qr_ecc_map_controls,
    validate_qr_ecc_map_vectors,
)
from superqr_desktop.v7_capacity_lab.protocol_bridge import load_qr_ecc_map_manifest


FPS = {20.0, 24.0, 30.0}
PROFILE_META = {
    "qr_v36_l_map": (36, "L"),
    "qr_v36_m_ecc": (36, "M"),
    "qr_v36_q_ecc": (36, "Q"),
    "qr_v40_l_ceiling": (40, "L"),
    "qr_v40_m_ecc": (40, "M"),
    "qr_v40_q_ecc": (40, "Q"),
}


def test_qr_ecc_extension_keeps_canonical_iteration_frozen():
    assert list(qr_controls()) == ["qr_v27_l_safe", "qr_v40_l_ceiling"]
    assert list(qr_ecc_map_controls()) == [
        "qr_v36_m_ecc",
        "qr_v36_q_ecc",
        "qr_v40_m_ecc",
        "qr_v40_q_ecc",
    ]
    assert profile_id("qr_v36_l_map") == 9
    assert profile_id("qr_v36_m_ecc") == 10
    assert profile_id("qr_v36_q_ecc") == 11
    assert profile_id("qr_v40_m_ecc") == 12
    assert profile_id("qr_v40_q_ecc") == 13


def test_ecc_payload_header_and_exact_qr_versions_validate():
    validate_qr_ecc_map_vectors()
    expected_ecc = {"M": 2, "Q": 3}
    for control in qr_ecc_map_controls().values():
        payload = build_qr_control_payload(control, 0)
        assert payload[4] == control["version"]
        assert payload[5] == expected_ecc[control["error_correction"]]
        assert len(payload) == control["frame_bytes"]
        matrix = build_qr_matrix(control, 0)
        assert len(matrix) == control["module_count"]
        assert all(len(row) == control["module_count"] for row in matrix)


def test_focused_campaign_covers_each_version_ecc_fps_once():
    manifest = load_qr_ecc_map_manifest()
    runs = build_qr_ecc_map_runs(dwell=3, frames=256)
    assert len(runs) == manifest["campaign"]["run_count"] == 21
    assert max(run.target_fps for run in runs) == 30.0

    controls = [run for run, item in zip(runs, manifest["campaign"]["runs"]) if item["role"].startswith("stability_control")]
    assert [runs.index(run) for run in controls] == [0, 10, 20]
    assert all(run.profile == "qr_v27_l_safe" and run.target_fps == 24.0 for run in controls)

    candidates = [
        run for run, item in zip(runs, manifest["campaign"]["runs"])
        if item["role"] == "candidate"
    ]
    observed = {
        (PROFILE_META[run.profile][0], PROFILE_META[run.profile][1], run.target_fps)
        for run in candidates
    }
    expected = {
        (version, ecc, fps)
        for version in (36, 40)
        for ecc in ("L", "M", "Q")
        for fps in FPS
    }
    assert observed == expected


def test_controller_exposes_focused_campaign_and_respects_frame_control():
    ctrl = CampaignController()
    ctrl.set_frames(64)
    ctrl.set_preset("QR ECC focused map")
    assert ctrl.run_count == 21
    assert all(run.frame_count == 64 for run in ctrl.runs)
    assert {run.target_fps for run in ctrl.runs} == FPS
