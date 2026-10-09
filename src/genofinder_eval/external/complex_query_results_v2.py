"""Recompute the v2 complex-query assessment from its public result files.

The v2 assessment keeps the 60 frozen queries and the expected-criteria sheet of v1. It adds
keyword searches of NCBI GEO DataSets (arm B) and OmicsDI (arm C), OmicsPlorer on an index whose
GEO source filter keeps lexical candidates (arm A), and a rerun of the v1 OmicsPlorer path on the
work server (arm E). Pairs already judged in v1 keep their v1 grade; pairs judged for the first
time in v2 are added to the v1 qrels ("extended qrels"). The 74 sealed v1 pairs judged again in
v2 give the retest agreement and a sensitivity analysis.

Metric code is shared with `ranking_metrics` (and so with v1): same definitions, bootstrap seed,
and iteration count. Rows are processed in the order of the private analysis so that bootstrap
intervals and sign-flip p-values are reproduced exactly.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genofinder_eval.external.complex_query_results import _read_csv, _unique_rows, write_csv
from genofinder_eval.external.ranking_metrics import (
    bootstrap_mean_ci,
    load_qrels,
    metrics_for_query,
    paired_primary,
    summarize,
)

SEED = 20260720
ITERATIONS = 10_000
ARMS = {"A": "omicsplorer_fixed_index", "B": "ncbi_geo_keyword", "C": "omicsdi_geo_keyword",
        "E": "omicsplorer_v1_path_rerun"}
MAIN_SYSTEMS = (ARMS["A"], ARMS["B"], ARMS["C"])
V1_SYSTEMS = ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")
ALL_SYSTEMS = (*MAIN_SYSTEMS, ARMS["E"], *V1_SYSTEMS)
REFERENCE = ARMS["A"]
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
class PublicResultsV2:
    criteria: dict[str, dict[str, str]]
    v1_qrels: dict[str, dict[str, int]]
    new_grades: dict[tuple[str, str], int]
    received_grades: dict[tuple[str, str], int]
    conditions: dict[tuple[str, str], dict[str, str]]
    rankings: dict[tuple[str, str], list[str]]
    retest: list[dict[str, Any]]
    v1_reported: dict[tuple[str, str], dict[str, str]]


def _rankings(path: Path, systems: tuple[str, ...], qids: list[str]) -> dict[tuple[str, str], list[str]]:
    ranked: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in _read_csv(path):
        if row["system"] in systems:
            ranked[(row["system"], row["qid"])].append((int(row["rank"]), row["accession"]))
    out: dict[tuple[str, str], list[str]] = {}
    for system in systems:
        for qid in qids:
            ordered = sorted(ranked.pop((system, qid), []))
            if [rank for rank, _ in ordered] != list(range(1, len(ordered) + 1)) or len(ordered) > 10:
                raise ValueError(f"bad ranks for {system}/{qid}")
            out[(system, qid)] = [accession for _, accession in ordered]
    if ranked:
        raise ValueError(f"rankings for unknown queries: {sorted(ranked)[:3]}")
    return out


def load_public_results_v2(results_dir: Path, v1_dir: Path, criteria_path: Path) -> PublicResultsV2:
    """Load and cross-check the public v1 and v2 files; every ranked accession must be judged."""
    criteria = {row["query_id"]: row for row in _read_csv(criteria_path)}
    qids = sorted(criteria)
    v1_qrels = load_qrels(v1_dir / "qrels.tsv")
    v2_qrels = load_qrels(results_dir / "qrels.tsv")
    new_grades = {(qid, acc): grade for qid, docs in v2_qrels.items() for acc, grade in docs.items()}
    if any(acc in v1_qrels.get(qid, {}) for qid, acc in new_grades):
        raise ValueError("a v2 qrels pair was already judged in v1")
    v1_conditions = _unique_rows(_read_csv(v1_dir / "condition_judgments.csv"), ("qid", "accession"),
                                 "v1 condition judgement")
    v2_conditions = _unique_rows(_read_csv(results_dir / "condition_judgments.csv"), ("qid", "accession"),
                                 "v2 condition judgement")
    if set(v2_conditions) != set(new_grades):
        raise ValueError("v2 condition judgements and qrels cover different pairs")
    # received grades = final grades with the grade corrections reverted
    received = dict(new_grades)
    retest: list[dict[str, Any]] = [
        {**raw, "v1_grade": int(raw["v1_grade"]), "v2_received_grade": int(raw["v2_received_grade"]),
         "v2_final_grade": int(raw["v2_final_grade"])}
        for raw in _read_csv(results_dir / "retest_pairs.csv")
    ]
    retest_ids = {pair_row["judgment_id"] for pair_row in retest}
    for correction in _read_csv(results_dir / "judgment_corrections.csv"):
        pair = (correction["qid"], correction["accession"])
        if correction["field"] == "grade" and correction["judgment_id"] not in retest_ids:
            if received[pair] != int(correction["corrected_value"]):
                raise ValueError(f"grade correction for {pair} does not match the qrels")
            received[pair] = int(correction["received_value"])
    for pair_row in retest:
        if v1_qrels[pair_row["qid"]].get(pair_row["accession"]) != pair_row["v1_grade"]:
            raise ValueError(f"retest pair {pair_row['judgment_id']} differs from the v1 qrels")
    rankings = {**_rankings(results_dir / "rankings.csv", (*MAIN_SYSTEMS, ARMS["E"]), qids),
                **_rankings(v1_dir / "rankings.csv", V1_SYSTEMS, qids)}
    for (system, qid), ranking in rankings.items():
        for accession in ranking:
            if accession not in v1_qrels.get(qid, {}) and (qid, accession) not in new_grades:
                raise ValueError(f"unjudged ranked accession {system}/{qid}/{accession}")
    v1_reported = {(row["system"], row["metric"]): row for row in _read_csv(v1_dir / "derived/metrics_summary.csv")}
    return PublicResultsV2(criteria, v1_qrels, new_grades, received, {**v1_conditions, **v2_conditions},
                           rankings, retest, v1_reported)


def extended_qrels(results: PublicResultsV2, grades: dict[tuple[str, str], int],
                   retest_from_v2: bool = False) -> dict[str, dict[str, int]]:
    qrels = {qid: dict(results.v1_qrels.get(qid, {})) for qid in sorted(results.criteria)}
    for (qid, accession), grade in grades.items():
        qrels[qid][accession] = grade
    if retest_from_v2:
        for row in results.retest:
            qrels[row["qid"]][row["accession"]] = row["v2_final_grade"]
    return qrels


def strict_match(condition: dict[str, str], criteria: dict[str, str]) -> bool:
    for required, met in REQUIREMENTS:
        if criteria[required].strip() and condition[met] != "1":
            return False
    if criteria["must_not_contain_or_condition"].strip() and condition["exclusion_violated"] != "no":
        return False
    return condition["insufficient_evidence"] == "no"


def per_query_metrics(results: PublicResultsV2, qrels: dict[str, dict[str, int]],
                      systems: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for system in systems:
        for qid in sorted(results.criteria):
            ranking = results.rankings[(system, qid)]
            criteria = results.criteria[qid]
            rows.append({
                "system": system, "qid": qid, "difficulty": criteria["difficulty"],
                **metrics_for_query(ranking, qrels[qid]),
                "returned": len(ranking),
                "nonempty": float(bool(ranking)),
                "relevant_returned": sum(qrels[qid][acc] >= 2 for acc in ranking),
                "grade3_returned": sum(qrels[qid][acc] == 3 for acc in ranking),
                "strict_success_at_10": float(any(strict_match(results.conditions[(qid, acc)], criteria)
                                                  for acc in ranking)),
            })
    return rows


def _bootstrap_row(values: list[float], **labels: Any) -> dict[str, Any]:
    low, high = bootstrap_mean_ci(values, iterations=ITERATIONS, seed=SEED)
    return {**labels, "mean": statistics.fmean(values), "ci95_low": low, "ci95_high": high,
            "n_queries": len(values)}


def summary_rows(per_query: list[dict[str, Any]], systems: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = summarize(per_query, iterations=ITERATIONS, seed=SEED)
    for system in systems:
        group = [row for row in per_query if row["system"] == system]
        for metric in ("strict_success_at_10", "nonempty", "relevant_returned", "grade3_returned"):
            rows.append(_bootstrap_row([float(row[metric]) for row in group], system=system, metric=metric))
        returned = sum(row["returned"] for row in group)
        relevant = sum(row["relevant_returned"] for row in group)
        rows.append({"system": system, "metric": "relevant_share_of_returned",
                     "mean": relevant / returned if returned else float("nan"),
                     "ci95_low": "", "ci95_high": "", "n_queries": len(group)})
    return rows


def by_difficulty(per_query: list[dict[str, Any]], systems: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for system in systems:
        for level in ("simple", "medium", "complex"):
            group = [row for row in per_query if row["system"] == system and row["difficulty"] == level]
            for metric in ("ndcg_at_10", "success_at_10", "strict_success_at_10"):
                rows.append(_bootstrap_row([float(row[metric]) for row in group],
                                           system=system, difficulty=level, metric=metric))
    return rows


def relevant_overlap(results: PublicResultsV2, qrels: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    """Relevant (grade >= 2) query-candidate pairs by the set of main arms that returned them."""
    overlap: Counter[str] = Counter()
    for qid in sorted(results.criteria):
        found = {system: {acc for acc in results.rankings[(system, qid)] if qrels[qid][acc] >= 2}
                 for system in MAIN_SYSTEMS}
        for accession in set().union(*found.values()):
            overlap["+".join(letter for letter, system in ARMS.items()
                             if system in found and accession in found[system])] += 1
    return [{"arms": arms, "relevant_candidates": count} for arms, count in sorted(overlap.items())]


def quadratic_kappa(a: list[int], b: list[int], categories: int = 4) -> float:
    n = len(a)
    observed = [[0.0] * categories for _ in range(categories)]
    for x, y in zip(a, b, strict=True):
        observed[x][y] += 1
    row = [sum(observed[i]) for i in range(categories)]
    col = [sum(observed[i][j] for i in range(categories)) for j in range(categories)]
    weight = [[(i - j) ** 2 / (categories - 1) ** 2 for j in range(categories)] for i in range(categories)]
    num = sum(weight[i][j] * observed[i][j] for i in range(categories) for j in range(categories))
    den = sum(weight[i][j] * row[i] * col[j] / n for i in range(categories) for j in range(categories))
    return 1 - num / den if den else float("nan")


def retest_agreement(retest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for label, column in (("received", "v2_received_grade"), ("final", "v2_final_grade")):
        a = [row["v1_grade"] for row in retest]
        b = [row[column] for row in retest]
        rows.append({
            "v2_values": label, "n_pairs": len(a),
            "exact_agreement": sum(x == y for x, y in zip(a, b, strict=True)) / len(a),
            "within_one": sum(abs(x - y) <= 1 for x, y in zip(a, b, strict=True)) / len(a),
            "relevant_binary_agreement": sum((x >= 2) == (y >= 2) for x, y in zip(a, b, strict=True)) / len(a),
            "quadratic_weighted_kappa": quadratic_kappa(a, b),
            "v1_mean": statistics.fmean(a), "v2_mean": statistics.fmean(b),
            "crosstab_v1_by_v2": json.dumps({f"{x}->{y}": c for (x, y), c in sorted(Counter(zip(a, b, strict=True)).items())}),
        })
    return rows


def paired_descriptive(per_query: list[dict[str, Any]], left: str, right: str, metric: str) -> dict[str, Any]:
    values = {(row["system"], row["qid"]): float(row[metric]) for row in per_query}
    qids = sorted({row["qid"] for row in per_query})
    diffs = [values[(left, qid)] - values[(right, qid)] for qid in qids]
    low, high = bootstrap_mean_ci(diffs, iterations=ITERATIONS, seed=SEED)
    return {"left": left, "right": right, "metric": metric, "n_queries": len(qids),
            "left_mean": statistics.fmean(values[(left, qid)] for qid in qids),
            "right_mean": statistics.fmean(values[(right, qid)] for qid in qids),
            "mean_difference": statistics.fmean(diffs), "ci95_low": low, "ci95_high": high,
            "queries_left_higher": sum(d > 0 for d in diffs), "queries_equal": sum(d == 0 for d in diffs),
            "queries_right_higher": sum(d < 0 for d in diffs)}


def analyze_v2(results: PublicResultsV2, out_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    qrels = extended_qrels(results, results.new_grades)
    per_query = per_query_metrics(results, qrels, ALL_SYSTEMS)
    summary = summary_rows(per_query, ALL_SYSTEMS)
    main = [row for row in per_query if row["system"] in MAIN_SYSTEMS]
    received = per_query_metrics(results, extended_qrels(results, results.received_grades), MAIN_SYSTEMS)
    retest_v2 = per_query_metrics(results, extended_qrels(results, results.new_grades, retest_from_v2=True),
                                  MAIN_SYSTEMS)
    extended_pool = []
    for row in summary:
        if row["system"] in V1_SYSTEMS and (row["system"], row["metric"]) in results.v1_reported:
            reported = float(results.v1_reported[(row["system"], row["metric"])]["mean"])
            extended_pool.append({"system": row["system"], "metric": row["metric"], "v1_reported": reported,
                                  "extended_pool": row["mean"], "difference": row["mean"] - reported})
    outputs = {
        "metrics_per_query": per_query,
        "metrics_summary": summary,
        "pairwise_primary_ndcg": paired_primary(main, reference=REFERENCE, iterations=ITERATIONS, seed=SEED),
        "metrics_by_difficulty": by_difficulty(per_query, ALL_SYSTEMS),
        "relevant_overlap": relevant_overlap(results, qrels),
        "v1_systems_extended_pool": extended_pool,
        "retest_agreement": retest_agreement(results.retest),
        "arm_a_vs_v1_path": [paired_descriptive(per_query, left, right, metric)
                             for left, right in ((ARMS["A"], "omicsplorer_geo"), (ARMS["E"], "omicsplorer_geo"),
                                                 (ARMS["A"], ARMS["E"]))
                             for metric in ("ndcg_at_10", "relevant_returned", "success_at_10")],
        "sensitivity_received_grades_summary": summarize(received, iterations=ITERATIONS, seed=SEED),
        "sensitivity_received_grades_pairwise": paired_primary(received, reference=REFERENCE,
                                                               iterations=ITERATIONS, seed=SEED),
        "sensitivity_retest_v2_grades_summary": summarize(retest_v2, iterations=ITERATIONS, seed=SEED),
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in outputs.items():
            write_csv(out_dir / f"{name}.csv", rows)
    return outputs
