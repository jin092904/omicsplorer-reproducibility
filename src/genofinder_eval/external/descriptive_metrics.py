"""Objective external-search descriptors that do not require relevance judgments."""
from __future__ import annotations

import argparse
import csv
import itertools
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from genofinder_eval.external.pooling import load_responses
from genofinder_eval.external.provenance import utc_now, write_json

FIELDS = ("title", "description", "organism", "assay", "publication_date", "sample_count")


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def summarize_run(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    responses = load_responses(run_dir)
    by_system: dict[str, list[Any]] = defaultdict(list)
    by_pair: dict[tuple[str, str], Any] = {}
    for response in responses:
        by_system[response.system].append(response)
        by_pair[(response.system, response.qid)] = response
    systems = sorted(by_system)
    qids = sorted({response.qid for response in responses})

    system_rows: list[dict[str, Any]] = []
    completeness_rows: list[dict[str, Any]] = []
    exclusive_rows: list[dict[str, Any]] = []
    for system in systems:
        system_responses = by_system[system]
        hits = [hit for response in system_responses for hit in response.hits]
        latencies = [float(response.wall_latency_ms) for response in system_responses]
        returned = [len(response.hits) for response in system_responses]
        system_rows.append(
            {
                "system": system,
                "n_queries": len(system_responses),
                "zero_result_queries": sum(value == 0 for value in returned),
                "zero_result_rate": sum(value == 0 for value in returned) / len(returned),
                "mean_returned": statistics.fmean(returned),
                "unique_accessions": len({hit.canonical_id for hit in hits}),
                "wall_p50_ms": _percentile(latencies, 0.50),
                "wall_p95_ms": _percentile(latencies, 0.95),
                "wall_p99_ms": _percentile(latencies, 0.99),
                "wall_max_ms": max(latencies),
            }
        )
        for field in FIELDS:
            present = sum(bool(getattr(hit, field)) for hit in hits)
            completeness_rows.append(
                {
                    "system": system,
                    "field": field,
                    "n_hits": len(hits),
                    "n_present": present,
                    "completeness": present / len(hits) if hits else math.nan,
                }
            )
        exclusive = total = 0
        for qid in qids:
            own = {hit.canonical_id for hit in by_pair[(system, qid)].hits}
            other = set().union(
                *(
                    {hit.canonical_id for hit in by_pair[(other_system, qid)].hits}
                    for other_system in systems
                    if other_system != system
                )
            )
            exclusive += len(own - other)
            total += len(own)
        exclusive_rows.append(
            {
                "system": system,
                "exclusive_hits": exclusive,
                "returned_hits": total,
                "exclusive_share": exclusive / total if total else math.nan,
            }
        )

    overlap_rows: list[dict[str, Any]] = []
    for left, right in itertools.combinations(systems, 2):
        values: list[float] = []
        intersections: list[int] = []
        for qid in qids:
            a = {hit.canonical_id for hit in by_pair[(left, qid)].hits}
            b = {hit.canonical_id for hit in by_pair[(right, qid)].hits}
            union = a | b
            values.append(len(a & b) / len(union) if union else 1.0)
            intersections.append(len(a & b))
        overlap_rows.append(
            {
                "system_a": left,
                "system_b": right,
                "n_queries": len(values),
                "mean_jaccard_at_10": statistics.fmean(values),
                "median_jaccard_at_10": statistics.median(values),
                "mean_intersection_at_10": statistics.fmean(intersections),
            }
        )
    return {
        "systems": system_rows,
        "completeness": completeness_rows,
        "exclusive": exclusive_rows,
        "overlap": overlap_rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    run = args.run.resolve()
    output = (args.output or run).resolve()
    summaries = summarize_run(run)
    for name, rows in summaries.items():
        _write_csv(output / f"descriptive_{name}.csv", rows)
    write_json(
        output / "descriptive_manifest.json",
        {
            "created_at_utc": utc_now(),
            "run": str(run),
            "relevance_judgments_used": False,
            "interpretation": "Discovery overlap/completeness only; not ranking quality.",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
