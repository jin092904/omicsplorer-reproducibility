"""Summarize privacy-safe Sol4 shadow operational measurements."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def summarize(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    datasets = [row for row in rows if row.get("event") == "dataset"]
    if not datasets:
        raise ValueError("No Sol4 dataset observations")
    stage_fields = {
        "dataset_total_ms": "elapsed_ms",
        "llm_ms": "llm_ms",
        "normalization_merge_ms": "normalization_merge_ms",
        "sample_fetch_ms": "sample_fetch_ms",
    }
    stage_rows: list[dict[str, Any]] = []
    for stage, field in stage_fields.items():
        values = [float(row[field]) for row in datasets if row.get(field) is not None]
        stage_rows.append(
            {
                "stage": stage,
                "n": len(values),
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
                "p99_ms": _percentile(values, 0.99),
                "max_ms": max(values),
                "mean_ms": statistics.fmean(values),
            }
        )
    for event, label in (("candidate_count", "candidate_count_ms"), ("candidate_select", "candidate_select_ms")):
        values = [float(row["elapsed_ms"]) for row in rows if row.get("event") == event]
        if values:
            stage_rows.append(
                {
                    "stage": label,
                    "n": len(values),
                    "p50_ms": _percentile(values, 0.50),
                    "p95_ms": _percentile(values, 0.95),
                    "p99_ms": _percentile(values, 0.99),
                    "max_ms": max(values),
                    "mean_ms": statistics.fmean(values),
                }
            )
    outcomes = Counter(str(row.get("outcome")) for row in datasets)
    run_summary = next(
        (row for row in reversed(rows) if row.get("event") == "run_summary"), {}
    )
    summary = {
        "mode": datasets[0].get("mode"),
        "model": datasets[0].get("model"),
        "extraction_version": datasets[0].get("extraction_version"),
        "n_datasets": len(datasets),
        "n_changed": sum(bool(row.get("changed")) for row in datasets),
        "n_errors": sum("error" in str(row.get("outcome")) for row in datasets),
        "new_curies_total": sum(int(row.get("new_curies") or 0) for row in datasets),
        "outcomes": dict(outcomes),
        "candidate_pool": run_summary.get("candidate_pool"),
        "elapsed_seconds": run_summary.get("elapsed_seconds"),
        "throughput_per_hour": run_summary.get("throughput_per_hour"),
        "database_writes": datasets[0].get("mode") != "shadow",
    }
    return stage_rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line]
    stages, summary = summarize(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "sol4_stage_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stages[0]))
        writer.writeheader()
        writer.writerows(stages)
    (args.output / "sol4_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
