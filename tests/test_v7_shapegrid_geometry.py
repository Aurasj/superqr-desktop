from __future__ import annotations

from superqr_desktop.v7_capacity_lab.protocol_bridge import load_shapegrid_manifest
from superqr_desktop.v7_capacity_lab.shapegrid import shapegrid_profile
from superqr_desktop.v7_capacity_lab.shapegrid_geometry import canonical_grid_bbox


def test_shapegrid_canonical_bboxes_are_sender_independent():
    manifest = load_shapegrid_manifest()
    payload = manifest["acquisition"]["reference_payload_bbox"]
    expected = {
        18: (92.0, 260.0, 908.0, 740.0),
        19: (92.0, 200.0, 908.0, 800.0),
        20: (70.0, 194.4736842105263, 930.0, 805.5263157894738),
    }
    for profile in manifest["profiles"]:
        actual = canonical_grid_bbox(profile, payload)
        assert all(abs(a - b) < 1e-9 for a, b in zip(actual, expected[profile["profile_id"]]))
        pitch_x = (actual[2] - actual[0]) / profile["grid_cols"]
        pitch_y = (actual[3] - actual[1]) / profile["grid_rows"]
        assert abs(pitch_x - pitch_y) < 1e-12


def test_fast_geometry_uses_six_canonical_units_per_tile():
    manifest = load_shapegrid_manifest()
    fast = shapegrid_profile("shapegrid_c4_s16_136x100_fast20")
    bbox = canonical_grid_bbox(fast, manifest["acquisition"]["reference_payload_bbox"])
    assert abs((bbox[2] - bbox[0]) / fast["grid_cols"] - 6.0) < 1e-12
    assert abs((bbox[3] - bbox[1]) / fast["grid_rows"] - 6.0) < 1e-12
