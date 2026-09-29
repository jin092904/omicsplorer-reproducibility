"""Recompute the blinded complex-query assessment from its public result files.

The public files are written by `scripts/export_complex_query_public_results.py`. Metric code is
shared with `ranking_metrics` so that the public recomputation and the frozen private analysis
use the same definitions, bootstrap seed, and iteration count. Rows are processed in
(system, query) order, the order in which the frozen analysis read the raw responses, so the
bootstrap intervals are reproduced exactly.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genofinder_eval.external.ranking_metrics import (
    bootstrap_mean_ci,
    load_qrels,
    metrics_for_query,
    paired_primary,
    summarize,
)

SYSTEMS = ("ncbi_geo", "omicsdi_geo", "omicsplorer_geo")
REFERENCE = "omicsplorer_geo"
SEED = 20260720
ITERATIONS = 10_000
REQUIREMENTS = (
    ("required_disease", "disease_met"),
    ("required_tissue", "tissue_met"),
    ("required_cell_type", "cell_type_met"),
    ("required_organism", "organism_met"),
    ("required_modality", "modality_met"),
    ("required_design", "design_met"),
    ("required_comparison_groups", "comparison_groups_met"),
    ("required_time_treatment_or_dose", "time_treatment_or_dose_met"),
)


@dataclass(frozen=True)
class PublicResults:
    qrels: dict[str, dict[str, int]]
    conditions: dict[tuple[str, str], dict[str, str]]
    rankings: dict[tuple[str, str], list[str]]
    responses: dict[tuple[str, str], dict[str, str]]
    criteria: dict[str, dict[str, str]]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_public_results(results_dir: Path, criteria_path: Path) -> PublicResults:
    """Load and cross-check the public files; every returned accession must be judged."""
    qrels = load_qrels(results_dir / "qrels.tsv")
    conditions = {(row["qid"], row["accession"]): row
                  for row in _read_csv(results_dir / "condition_judgments.csv")}
    if set(conditions) != {(qid, acc) for qid, docs in qrels.items() for acc in docs}:
        raise ValueError("condition judgements and qrels cover different judged pairs")
    responses = {(row["system"], row["qid"]): row for row in _read_csv(results_dir / "responses.csv")}
    ranked: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in _read_csv(results_dir / "rankings.csv"):
        ranked[(row["system"], row["qid"])].append((int(row["rank"]), row["accession"]))
    rankings: dict[tuple[str, str], list[str]] = {}
    for pair, response in responses.items():
        ordered = sorted(ranked.get(pair, []))
        if [rank for rank, _ in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError(f"non-contiguous ranks for {pair}")
        if len(ordered) != int(response["returned"]):
            raise ValueError(f"returned count differs from ranked rows for {pair}")
        if any(accession not in qrels[pair[1]] for _, accession in ordered):
            raise ValueError(f"unjudged returned accession for {pair}")
        rankings[pair] = [accession for _, accession in ordered]
    if set(ranked) - set(responses):
        raise ValueError("rankings contain a system/query pair without a response row")
    expected = {(system, qid) for system in SYSTEMS for qid in qrels}
    if set(responses) != expected:
        raise ValueError("expected one response row for every system and query")
    criteria = {row["query_id"]: row for row in _read_csv(criteria_path)}
    if set(criteria) != set(qrels):
        raise ValueError("criteria sheet and qrels cover different queries")
    return PublicResults(qrels, conditions, rankings, responses, criteria)


def _pairs(results: PublicResults) -> list[tuple[str, str]]:
    return sorted(results.responses)


def per_query_metrics(results: PublicResults) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system, qid in _pairs(results):
        ranking = results.rankings[(system, qid)]
        rows.append({
            "system": system,
            "qid": qid,
            "difficulty": results.criteria[qid]["difficulty"],
            **metrics_for_query(ranking, results.qrels[qid]),
            "wall_latency_ms": float(results.responses[(system, qid)]["wall_latency_ms"]),
            "returned": len(ranking),
        })
    return rows


def summarize_groups(rows: list[dict[str, Any]], metrics: tuple[str, ...], group_fields: tuple[str, ...],
                     *, iterations: int = ITERATIONS, seed: int = SEED) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row[field]) for field in group_fields)].append(row)
    output: list[dict[str, Any]] = []
    for group, group_rows in sorted(grouped.items()):
        for metric in metrics:
            values = [float(row[metric]) for row in group_rows]
            low, high = bootstrap_mean_ci(values, iterations=iterations, seed=seed)
            output.append({**dict(zip(group_fields, group, strict=True)), "metric": metric,
                           "mean": statistics.fmean(values), "ci95_low": low, "ci95_high": high,
                           "n_queries": len(values)})
    return output


def availability_rows(per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "system": row["system"], "qid": row["qid"], "difficulty": row["difficulty"],
        "returned": int(row["returned"]),
        "nonempty_response": float(int(row["returned"]) > 0),
        "full_top_10_response": float(int(row["returned"]) == 10),
        "returned_fraction_of_10": int(row["returned"]) / 10,
    } for row in per_query]


def _strict_match(condition: dict[str, str], criteria: dict[str, str]) -> bool:
    for required, met in REQUIREMENTS:
        if criteria[required].strip() and condition[met] != "1":
            return False
    if criteria["must_not_contain_or_condition"].strip() and condition["exclusion_violated"] != "no":
        return False
    return condition["insufficient_evidence"] == "no"


def _required_fraction(condition: dict[str, str], criteria: dict[str, str]) -> float:
    values = [condition[met] for required, met in REQUIREMENTS if criteria[required].strip()]
    return sum(value == "1" for value in values) / len(values) if values else 1.0


def condition_rows(results: PublicResults) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system, qid in _pairs(results):
        criteria = results.criteria[qid]
        observed = [results.conditions[(qid, accession)] for accession in results.rankings[(system, qid)]]
        n = len(observed)
        rows.append({
            "system": system, "qid": qid, "difficulty": criteria["difficulty"],
            "strict_all_conditions_success_at_10": float(any(_strict_match(c, criteria) for c in observed)),
            "mean_required_condition_fraction_at_10":
                statistics.fmean(_required_fraction(c, criteria) for c in observed) if n else 0.0,
            "exclusion_violation_fraction_at_10":
                sum(c["exclusion_violated"] == "yes" for c in observed) / n if n else 0.0,
            "insufficient_evidence_fraction_at_10":
                sum(c["insufficient_evidence"] == "yes" for c in observed) / n if n else 0.0,
        })
    return rows


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (1 - (position - low)) + ordered[high] * (position - low)


def latency_rows(per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system in SYSTEMS:
        values = [float(row["wall_latency_ms"]) for row in per_query if row["system"] == system]
        rows.append({
            "system": system, "n_queries": len(values), "median_ms": statistics.median(values),
            "p90_ms": _percentile(values, 0.90), "p95_ms": _percentile(values, 0.95),
            "p99_observed_ms": _percentile(values, 0.99), "max_ms": max(values),
            "measurement_scope": "adapter wall time; not browser end-to-end latency",
        })
    return rows


def returned_candidate_yield(results: PublicResults) -> list[dict[str, Any]]:
    """Post-hoc descriptive analysis: relevant (grade >= 2) share of the returned candidates."""
    rows: list[dict[str, Any]] = []
    for scope in ("all", "simple", "medium", "complex"):
        for system in SYSTEMS:
            qids = sorted(qid for qid in results.qrels
                          if scope == "all" or results.criteria[qid]["difficulty"] == scope)
            if not qids:
                continue
            returned = relevant = grade3 = 0
            for qid in qids:
                for accession in results.rankings[(system, qid)]:
                    grade = results.qrels[qid][accession]
                    returned += 1
                    relevant += grade >= 2
                    grade3 += grade == 3
            rows.append({
                "scope": scope, "system": system, "n_queries": len(qids),
                "returned_candidates": returned, "relevant_candidates": relevant,
                "grade3_candidates": grade3,
                "relevant_share_of_returned": relevant / returned if returned else math.nan,
                "relevant_per_query": relevant / len(qids), "grade3_per_query": grade3 / len(qids),
            })
    return rows


def nonempty_sensitivity(per_query: list[dict[str, Any]], *, iterations: int = ITERATIONS,
                         seed: int = SEED) -> list[dict[str, Any]]:
    """Post-hoc: nDCG@10 differences on the queries where each comparator returned results."""
    lookup = {(row["system"], row["qid"]): row for row in per_query}
    rows: list[dict[str, Any]] = []
    for comparator in ("ncbi_geo", "omicsdi_geo"):
        qids = sorted(row["qid"] for row in per_query
                      if row["system"] == comparator and int(row["returned"]) > 0)
        reference = [float(lookup[(REFERENCE, qid)]["ndcg_at_10"]) for qid in qids]
        other = [float(lookup[(comparator, qid)]["ndcg_at_10"]) for qid in qids]
        differences = [left - right for left, right in zip(reference, other, strict=True)]
        rng = random.Random(seed)
        samples = [statistics.fmean(differences[rng.randrange(len(differences))] for _ in differences)
                   for _ in range(iterations)]
        rows.append({
            "subset_definition": f"queries where {comparator} returned at least one result",
            "reference": REFERENCE, "comparator": comparator, "n_queries": len(qids),
            "reference_mean_ndcg_at_10": statistics.fmean(reference),
            "comparator_mean_ndcg_at_10": statistics.fmean(other),
            "mean_difference": statistics.fmean(differences),
            "ci95_low": _percentile(samples, 0.025), "ci95_high": _percentile(samples, 0.975),
            "bootstrap_iterations": iterations, "bootstrap_seed": seed,
        })
    return rows


def all_systems_nonempty(per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Post-hoc: mean nDCG@10 per system on the queries where every system returned results."""
    lookup = {(row["system"], row["qid"]): row for row in per_query}
    qids = sorted(qid for qid in {row["qid"] for row in per_query}
                  if all(int(lookup[(system, qid)]["returned"]) > 0 for system in SYSTEMS))
    return [{
        "subset_definition": "queries where all three systems returned at least one result",
        "system": system, "n_queries": len(qids),
        "mean_ndcg_at_10": (statistics.fmean(float(lookup[(system, qid)]["ndcg_at_10"]) for qid in qids)
                            if qids else math.nan),
    } for system in SYSTEMS]


def compare_tables(expected_dir: Path, actual: dict[str, list[dict[str, Any]]],
                   *, tolerance: float = 1e-12) -> list[str]:
    """Differences between recomputed tables and the CSV files committed in `expected_dir`."""
    problems: list[str] = []
    for name, rows in actual.items():
        path = expected_dir / f"{name}.csv"
        if not path.exists():
            problems.append(f"{name}: committed table missing")
            continue
        committed = _read_csv(path)
        if len(committed) != len(rows):
            problems.append(f"{name}: {len(committed)} committed rows, {len(rows)} recomputed")
            continue
        for index, (old, new) in enumerate(zip(committed, rows, strict=True)):
            if list(old) != [str(key) for key in new]:
                problems.append(f"{name}: columns differ")
                break
            for key, value in new.items():
                try:
                    if abs(float(old[key]) - float(value)) > tolerance:
                        problems.append(f"{name} row {index} {key}: {old[key]} != {value}")
                except ValueError:
                    if old[key] != str(value):
                        problems.append(f"{name} row {index} {key}: {old[key]!r} != {value!r}")
    return problems


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze(results: PublicResults, out_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    per_query = per_query_metrics(results)
    availability = availability_rows(per_query)
    conditions = condition_rows(results)
    outputs = {
        "metrics_per_query": per_query,
        "metrics_summary": summarize(per_query, iterations=ITERATIONS, seed=SEED),
        "pairwise_primary_ndcg": paired_primary(per_query, iterations=ITERATIONS, seed=SEED),
        "metrics_by_difficulty": summarize_groups(per_query, ("ndcg_at_10", "success_at_10"),
                                                  ("system", "difficulty")),
        "response_availability_per_query": availability,
        "response_availability_summary": summarize_groups(
            availability, ("nonempty_response", "full_top_10_response", "returned_fraction_of_10"),
            ("system",)),
        "response_availability_by_difficulty": summarize_groups(
            availability, ("nonempty_response", "returned_fraction_of_10"), ("system", "difficulty")),
        "condition_metrics_per_query": conditions,
        "condition_metrics_summary": summarize_groups(
            conditions, ("strict_all_conditions_success_at_10", "mean_required_condition_fraction_at_10",
                         "exclusion_violation_fraction_at_10", "insufficient_evidence_fraction_at_10"),
            ("system",)),
        "condition_metrics_by_difficulty": summarize_groups(
            conditions, ("strict_all_conditions_success_at_10",), ("system", "difficulty")),
        "latency_summary": latency_rows(per_query),
        "posthoc_returned_candidate_yield": returned_candidate_yield(results),
        "posthoc_nonempty_sensitivity": nonempty_sensitivity(per_query),
        "posthoc_all_systems_nonempty": all_systems_nonempty(per_query),
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in outputs.items():
            write_csv(out_dir / f"{name}.csv", rows)
    return outputs
