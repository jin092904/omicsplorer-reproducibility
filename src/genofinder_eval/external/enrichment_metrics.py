"""Paired field-level metrics for LLM structuring and Sol4 safe enrichment."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

FIELDS = (
    "modality",
    "organism_taxid",
    "disease_ids",
    "tissue_ids",
    "cell_type_ids",
)
SAFE_MERGE_FIELDS = ("disease_ids", "tissue_ids", "cell_type_ids")


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        value = [value]
    return {str(item).strip() for item in value if str(item).strip()}


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            rows.append(value)
    return rows


def compute_metrics(
    gold_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gold = {str(row["dataset_id"]): row for row in gold_rows}
    if len(gold) != len(gold_rows):
        raise ValueError("Duplicate dataset_id in gold")

    aggregates: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    dataset_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for row in prediction_rows:
        dataset_id = str(row["dataset_id"])
        condition = str(row["condition"])
        pair = (dataset_id, condition)
        if pair in seen_pairs:
            raise ValueError(f"Duplicate prediction: {pair}")
        seen_pairs.add(pair)
        if dataset_id not in gold:
            raise ValueError(f"Prediction has no gold row: {dataset_id}")

        gold_fields = gold[dataset_id].get("gold", {})
        prediction = row.get("prediction", {})
        before = row.get("before", {})
        any_regression = False
        any_shrink = False

        for field in FIELDS:
            expected = _as_set(gold_fields.get(field))
            predicted = _as_set(prediction.get(field))
            previous = _as_set(before.get(field))
            tp = len(expected & predicted)
            fp = len(predicted - expected)
            fn = len(expected - predicted)
            union = expected | predicted
            exact = float(expected == predicted)
            jaccard = _safe_div(tp, len(union)) if union else 1.0

            correct_before = previous & expected
            lost_correct = correct_before - predicted
            gain_possible = expected - previous
            correct_gained = (predicted & expected) - previous
            regression = bool(lost_correct)
            shrink = field in SAFE_MERGE_FIELDS and not previous.issubset(predicted)
            any_regression |= regression
            any_shrink |= shrink

            bucket = aggregates[(condition, field)]
            bucket["tp"] += tp
            bucket["fp"] += fp
            bucket["fn"] += fn
            bucket["exact_sum"] += exact
            bucket["jaccard_sum"] += jaccard
            bucket["datasets"] += 1
            bucket["gain_possible"] += len(gain_possible)
            bucket["correct_gained"] += len(correct_gained)
            bucket["correct_before"] += len(correct_before)
            bucket["lost_correct"] += len(lost_correct)
            bucket["shrink_datasets"] += float(shrink)

            dataset_rows.append(
                {
                    "dataset_id": dataset_id,
                    "condition": condition,
                    "field": field,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "exact": exact,
                    "jaccard": jaccard,
                    "correct_gained": len(correct_gained),
                    "lost_correct": len(lost_correct),
                    "regression": regression,
                    "safe_merge_shrink": shrink,
                }
            )

        overall = aggregates[(condition, "__overall__")]
        overall["datasets"] += 1
        overall["schema_valid"] += float(bool(row.get("schema_valid")))
        overall["first_pass_valid"] += float(bool(row.get("first_pass_valid")))
        overall["retry_count"] += int(row.get("retry_count") or 0)
        overall["regression_datasets"] += float(any_regression)
        overall["shrink_datasets"] += float(any_shrink)
        curie_validation = row.get("curie_validation", {})
        if isinstance(curie_validation, dict):
            overall["curies_checked"] += len(curie_validation)
            overall["invalid_curies"] += sum(not bool(value) for value in curie_validation.values())
        wall_ms = row.get("timing", {}).get("wall_ms") if isinstance(row.get("timing"), dict) else None
        if isinstance(wall_ms, (int, float)):
            overall["wall_ms_sum"] += float(wall_ms)
            overall["wall_ms_count"] += 1

    summary_rows: list[dict[str, Any]] = []
    for (condition, field), bucket in sorted(aggregates.items()):
        datasets = bucket["datasets"]
        if field == "__overall__":
            summary_rows.append(
                {
                    "condition": condition,
                    "field": field,
                    "n_datasets": int(datasets),
                    "schema_pass_rate": _safe_div(bucket["schema_valid"], datasets),
                    "first_pass_rate": _safe_div(bucket["first_pass_valid"], datasets),
                    "mean_retry_count": _safe_div(bucket["retry_count"], datasets),
                    "dataset_regression_rate": _safe_div(bucket["regression_datasets"], datasets),
                    "safe_merge_shrink_rate": _safe_div(bucket["shrink_datasets"], datasets),
                    "invalid_curie_rate": _safe_div(
                        bucket["invalid_curies"], bucket["curies_checked"]
                    ),
                    "mean_wall_ms": _safe_div(bucket["wall_ms_sum"], bucket["wall_ms_count"]),
                }
            )
            continue
        precision = _safe_div(bucket["tp"], bucket["tp"] + bucket["fp"])
        recall = _safe_div(bucket["tp"], bucket["tp"] + bucket["fn"])
        f1 = _safe_div(2 * precision * recall, precision + recall)
        summary_rows.append(
            {
                "condition": condition,
                "field": field,
                "n_datasets": int(datasets),
                "precision_micro": precision,
                "recall_micro": recall,
                "f1_micro": f1,
                "exact_set_rate": _safe_div(bucket["exact_sum"], datasets),
                "mean_jaccard": _safe_div(bucket["jaccard_sum"], datasets),
                "information_gain_rate": _safe_div(
                    bucket["correct_gained"], bucket["gain_possible"]
                ),
                "correct_value_loss_rate": _safe_div(
                    bucket["lost_correct"], bucket["correct_before"]
                ),
                "safe_merge_shrink_rate": _safe_div(bucket["shrink_datasets"], datasets),
            }
        )
    return summary_rows, dataset_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--per-dataset", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary, per_dataset = compute_metrics(load_jsonl(args.gold), load_jsonl(args.predictions))
    write_csv(args.summary, summary)
    write_csv(args.per_dataset, per_dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
