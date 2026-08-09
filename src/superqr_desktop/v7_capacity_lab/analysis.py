"""Receiver-log analysis used by the Desktop UI and CLI automation."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path


def analyze_records(records: list[dict]) -> dict:
    scored = [record for record in records if record.get("scored", True)]
    observed = sum(int(record.get("observed_bits", 0)) for record in scored)
    erased = sum(int(record.get("erased_bits", 0)) for record in scored)
    errors = sum(int(record.get("bit_errors", 0)) for record in scored)
    non_erased = observed - erased
    indices = [record.get("frame_index") for record in scored]
    valid_indices = [int(index) for index in indices if isinstance(index, (int, float)) and 0 <= index <= 255]
    failures = Counter(
        str(record["failure_reason"])
        for record in records if record.get("failure_reason")
    )
    if not failures:
        for record in records:
            if int(record.get("valid_samples", 1)) == 0:
                failures["NO_GEOMETRY_OR_SAMPLES"] += 1
            elif record.get("frame_index") is None:
                failures["FRAME_INDEX_UNREADABLE"] += 1
            elif int(record.get("erased_bits", 0)):
                failures["CELL_ERASURES"] += 1
            elif int(record.get("bit_errors", 0)):
                failures["CELL_ERRORS"] += 1
    prefix_zero = 0
    for index in indices:
        if index == 0:
            prefix_zero += 1
        else:
            break
    run_times: dict[str, list[int]] = defaultdict(list)
    for record in scored:
        run_times[str(record.get("run_id", "unknown"))].append(int(record.get("completed_ns", 0)))
    elapsed = sum(
        (max(times) - min(times)) / 1_000_000_000.0
        for times in run_times.values() if len(times) > 1
    )
    raw_valid = sum(bool(record.get("raw_valid", record.get("frame_valid", False))) for record in scored)
    inner_valid = sum(bool(record.get("inner_fec_valid", record.get("post_fec_valid", False))) for record in scored)
    innovative = sum(int(record.get("innovative_bytes", 0)) for record in scored)
    pipelines = sorted(float(record.get("pipeline_ms", 0.0)) for record in scored)
    p95 = pipelines[max(0, int(len(pipelines) * 0.95 + 0.999) - 1)] if pipelines else 0.0
    return {
        "observations": len(records),
        "scored_frames": len(scored),
        "rejected_frames": len(records) - len(scored),
        "unique_frame_indices": len(set(valid_indices)),
        "unreadable_frame_indices": len(indices) - len(valid_indices),
        "initial_frame_zero_observations": prefix_zero,
        "ber_non_erased": errors / non_erased if non_erased else 0.0,
        "erasure_rate": erased / observed if observed else 0.0,
        "raw_valid_yield": raw_valid / len(scored) if scored else 0.0,
        "inner_fec_valid_yield": inner_valid / len(scored) if scored else 0.0,
        "goodput_kib_s": innovative / elapsed / 1024.0 if elapsed else 0.0,
        "pipeline_mean_ms": sum(pipelines) / len(pipelines) if pipelines else 0.0,
        "pipeline_p95_ms": p95,
        "failure_reasons": dict(failures.most_common()),
    }


def analyze_jsonl(path: str | Path) -> dict:
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
    if not records:
        raise ValueError("receiver log is empty")
    return analyze_records(records)


def format_analysis(summary: dict) -> str:
    reasons = ", ".join(f"{key}={value}" for key, value in summary["failure_reasons"].items()) or "none"
    return (
        f"Observations {summary['observations']} • scored {summary['scored_frames']} • "
        f"rejected {summary['rejected_frames']}\n"
        f"Unique indices {summary['unique_frame_indices']} • unreadable {summary['unreadable_frame_indices']} • "
        f"initial frame-0 samples {summary['initial_frame_zero_observations']}\n"
        f"BER {summary['ber_non_erased']:.3%} • erasures {summary['erasure_rate']:.3%} • "
        f"raw yield {summary['raw_valid_yield']:.2%} • inner-FEC yield {summary['inner_fec_valid_yield']:.2%}\n"
        f"Goodput {summary['goodput_kib_s']:.2f} KiB/s • pipeline mean/p95 "
        f"{summary['pipeline_mean_ms']:.2f}/{summary['pipeline_p95_ms']:.2f} ms\n"
        f"Failure evidence: {reasons}"
    )
