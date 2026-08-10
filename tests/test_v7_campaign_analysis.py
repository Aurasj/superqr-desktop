from superqr_desktop.v7_capacity_lab.analysis import analyze_records, format_analysis


def test_campaign_analysis_reports_runs_and_current_acquisition_stage():
    records = [
        {
            "run_id": "ABBA", "run_token": 0xABBA, "profile": "mono_64x50_matched",
            "completed_ns": 1_000_000_000, "frame_index": 0, "scored": True,
            "observed_bits": 3200, "bit_errors": 0, "erased_bits": 0,
            "raw_valid": True, "inner_fec_valid": True, "innovative_bytes": 340,
            "pipeline_ms": 5.0, "acquisition_ms": 0.3,
        },
        {
            "run_id": "ABBA", "run_token": 0xABBA, "profile": "mono_64x50_matched",
            "completed_ns": 2_000_000_000, "frame_index": 1, "scored": False,
            "observed_bits": 0, "bit_errors": 0, "erased_bits": 0,
            "raw_valid": False, "inner_fec_valid": False, "innovative_bytes": 0,
            "pipeline_ms": 7.0, "acquisition_ms": 1.2, "failure_reason": "SYNC_TOP_CRC_OR_HEADER",
        },
        {
            "run_id": "ABBA", "run_token": 0xABBA, "profile": "mono_64x50_matched",
            "completed_ns": 3_000_000_000, "frame_index": 2, "scored": True,
            "observed_bits": 3200, "bit_errors": 4, "erased_bits": 8,
            "raw_valid": False, "inner_fec_valid": True, "innovative_bytes": 340,
            "pipeline_ms": 6.0, "acquisition_ms": 0.4,
        },
        {
            "run_id": "ABBB", "run_token": 0xABBB, "profile": "mono_96x75_medium",
            "completed_ns": 4_000_000_000, "frame_index": 0, "scored": True,
            "observed_bits": 7200, "bit_errors": 10, "erased_bits": 20,
            "raw_valid": False, "inner_fec_valid": False, "innovative_bytes": 0,
            "pipeline_ms": 8.0, "acquisition_ms": 0.5,
        },
    ]

    summary = analyze_records(records)
    assert summary["unique_frame_indices"] == 3
    assert len(summary["runs"]) == 2
    assert summary["runs"][0]["run_id"] == "ABBA"
    assert summary["runs"][0]["scored_frames"] == 2
    assert summary["runs"][0]["rejected_frames"] == 1
    assert summary["runs"][0]["unique_frame_indices"] == 2
    assert summary["stage_mean_ms"]["acquisition_ms"] == 0.6
    text = format_analysis(summary)
    assert "Receiver-window goodput" in text
    assert "diagnostic; pair sender report for final goodput" in text
    assert "ABBA" in text and "ABBB" in text
