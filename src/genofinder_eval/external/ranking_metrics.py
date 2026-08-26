"""Graded ranking metrics and paired inference for adjudicated external qrels."""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from genofinder_eval.external.models import SearchResponse
from genofinder_eval.external.pooling import load_responses


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 4:
                raise ValueError(f"Expected TREC qrel at {path}:{line_number}")
            qid, _iteration, docid, relevance = parts
            grade = int(relevance)
            if grade not in {0, 1, 2, 3}:
                raise ValueError(f"Relevance must be 0..3 at {path}:{line_number}")
            if docid in qrels[qid]:
                raise ValueError(f"Duplicate qrel: {qid}/{docid}")
            qrels[qid][docid] = grade
    if not qrels:
        raise ValueError(f"No qrels in {path}")
    return dict(qrels)


def _dcg(grades: list[int]) -> float:
    return float(
        sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))
    )


def metrics_for_query(
    ranking: list[str],
    qrels: dict[str, int],
    *,
    k: int = 10,
    relevant_threshold: int = 2,
) -> dict[str, float]:
    top = ranking[:k]
    grades = [qrels.get(docid, 0) for docid in top]
    ideal = sorted(qrels.values(), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    binary = [grade >= relevant_threshold for grade in grades]
    total_relevant = sum(grade >= relevant_threshold for grade in qrels.values())
    reciprocal_rank = next((1.0 / rank for rank, value in enumerate(binary, 1) if value), 0.0)

    judged_relevant = {docid for docid, grade in qrels.items() if grade >= relevant_threshold}
    judged_nonrelevant = {docid for docid, grade in qrels.items() if grade < relevant_threshold}
    r_count = len(judged_relevant)
    bpref_sum = 0.0
    for relevant_id in judged_relevant:
        if relevant_id not in ranking:
            continue
        rank = ranking.index(relevant_id)
        nonrelevant_before = sum(docid in judged_nonrelevant for docid in ranking[:rank])
        bpref_sum += 1.0 - min(nonrelevant_before, r_count) / r_count if r_count else 0.0

    return {
        "ndcg_at_10": _dcg(grades) / ideal_dcg if ideal_dcg else 0.0,
        "precision_at_10": sum(binary) / k,
        "recall_at_10_judged": sum(binary) / total_relevant if total_relevant else 0.0,
        "mrr_at_10": reciprocal_rank,
        "success_at_10": float(any(binary)),
        "bpref": bpref_sum / r_count if r_count else 0.0,
    }


def compute_per_query(
    responses: list[SearchResponse],
    qrels: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    observed: set[tuple[str, str]] = set()
    for response in responses:
        pair = (response.system, response.qid)
        if pair in observed:
            raise ValueError(f"Duplicate response: {pair}")
        observed.add(pair)
        if response.qid not in qrels:
            raise ValueError(f"Missing qrels for response qid: {response.qid}")
        ranking = [hit.canonical_id for hit in response.hits]
        rows.append(
            {
                "system": response.system,
                "qid": response.qid,
                **metrics_for_query(ranking, qrels[response.qid]),
                "wall_latency_ms": response.wall_latency_ms,
                "returned": len(ranking),
            }
        )
    return rows


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


def bootstrap_mean_ci(values: list[float], *, iterations: int, seed: int) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    rng = random.Random(seed)
    samples = [
        statistics.fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(iterations)
    ]
    return _percentile(samples, 0.025), _percentile(samples, 0.975)


def summarize(
    per_query: list[dict[str, Any]],
    *,
    iterations: int = 10_000,
    seed: int = 20260720,
) -> list[dict[str, Any]]:
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_query:
        by_system[str(row["system"])].append(row)
    metric_names = (
        "ndcg_at_10",
        "precision_at_10",
        "recall_at_10_judged",
        "mrr_at_10",
        "success_at_10",
        "bpref",
    )
    rows: list[dict[str, Any]] = []
    for system, system_rows in sorted(by_system.items()):
        for metric in metric_names:
            values = [float(row[metric]) for row in system_rows]
            low, high = bootstrap_mean_ci(values, iterations=iterations, seed=seed)
            rows.append(
                {
                    "system": system,
                    "metric": metric,
                    "mean": statistics.fmean(values),
                    "ci95_low": low,
                    "ci95_high": high,
                    "n_queries": len(values),
                }
            )
    return rows


def paired_primary(
    per_query: list[dict[str, Any]],
    *,
    reference: str = "omicsplorer_geo",
    metric: str = "ndcg_at_10",
    iterations: int = 10_000,
    seed: int = 20260720,
) -> list[dict[str, Any]]:
    values: dict[str, dict[str, float]] = defaultdict(dict)
    for row in per_query:
        values[str(row["system"])][str(row["qid"])] = float(row[metric])
    if reference not in values:
        raise ValueError(f"Reference system not found: {reference}")

    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for comparator in sorted(set(values) - {reference}):
        qids = sorted(set(values[reference]) & set(values[comparator]))
        if not qids:
            raise ValueError(f"No paired queries for {reference} vs {comparator}")
        differences = [values[reference][qid] - values[comparator][qid] for qid in qids]
        observed = statistics.fmean(differences)
        boot = [
            statistics.fmean(differences[rng.randrange(len(differences))] for _ in differences)
            for _ in range(iterations)
        ]
        sign_flip = [
            statistics.fmean(value if rng.random() < 0.5 else -value for value in differences)
            for _ in range(iterations)
        ]
        p_value = (1 + sum(abs(value) >= abs(observed) for value in sign_flip)) / (iterations + 1)
        rows.append(
            {
                "reference": reference,
                "comparator": comparator,
                "metric": metric,
                "mean_difference": observed,
                "ci95_low": _percentile(boot, 0.025),
                "ci95_high": _percentile(boot, 0.975),
                "p_value": p_value,
                "n_queries": len(qids),
            }
        )

    # Holm step-down adjusted p-values, monotonic in sorted order.
    order = sorted(range(len(rows)), key=lambda index: float(rows[index]["p_value"]))
    running = 0.0
    for position, index in enumerate(order):
        adjusted = min(1.0, (len(rows) - position) * float(rows[index]["p_value"]))
        running = max(running, adjusted)
        rows[index]["p_value_holm"] = running
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty metrics: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260720)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = (args.output or args.run).resolve()
    per_query = compute_per_query(load_responses(args.run.resolve()), load_qrels(args.qrels))
    summary = summarize(per_query, iterations=args.iterations, seed=args.seed)
    paired = paired_primary(per_query, iterations=args.iterations, seed=args.seed)
    _write_csv(output / "metrics_per_query.csv", per_query)
    _write_csv(output / "metrics_summary.csv", summary)
    _write_csv(output / "pairwise_bootstrap.csv", paired)
    (output / "metrics_manifest.json").write_text(
        json.dumps(
            {
                "qrels": str(args.qrels.resolve()),
                "iterations": args.iterations,
                "seed": args.seed,
                "primary_metric": "ndcg_at_10",
                "relevant_threshold": 2,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
