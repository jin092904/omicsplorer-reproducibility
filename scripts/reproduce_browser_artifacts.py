#!/usr/bin/env python3
"""Recompute public browser summaries and the manuscript tail-latency figure."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from genofinder_eval.external.browser_latency import summarize_by_category, summarize_observations
from genofinder_eval.figures.figure_tail_latency_category import render

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/browser_2026-07-20/browser_timings_public.jsonl"
COMMITTED_SUMMARY = ROOT / "results/browser_2026-07-20/browser_latency_summary.csv"
COMMITTED_CATEGORY = ROOT / "results/browser_2026-07-20/browser_latency_by_category.csv"
OUTPUT = ROOT / "build/browser_2026-07-20"
METRICS = ("search_first_result_ms", "search_settled_ms")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def verify(recomputed: list[dict[str, Any]], committed: list[dict[str, str]], keys: tuple[str, ...]) -> None:
    retained = ("n", "n_success", "n_timeout", "n_error", "success_rate", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms")
    expected = {tuple(row[key] for key in keys): row for row in committed}
    for row in recomputed:
        identity = tuple(str(row[key]) for key in keys)
        if row.get("metric") not in METRICS:
            continue
        if identity not in expected:
            raise ValueError(f"committed summary is missing {identity}")
        for field in retained:
            left = float(row[field])
            right = float(expected[identity][field])
            if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(f"{identity} {field} differs: {left} != {right}")


def main() -> int:
    rows = load_jsonl(SOURCE)
    if len(rows) != 240:
        raise ValueError(f"expected 240 public timing rows, found {len(rows)}")
    summary = summarize_observations(rows)
    category = summarize_by_category(rows)
    verify(summary, read_csv(COMMITTED_SUMMARY), ("metric",))
    verify(category, read_csv(COMMITTED_CATEGORY), ("category", "metric"))
    write_csv(OUTPUT / "browser_latency_summary.csv", summary)
    write_csv(OUTPUT / "browser_latency_by_category.csv", category)
    render(OUTPUT / "browser_latency_by_category.csv", OUTPUT / "figures")
    print(f"verified {len(rows)} rows; wrote reproducible artifacts under {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
