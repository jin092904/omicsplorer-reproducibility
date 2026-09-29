from __future__ import annotations

import csv
from pathlib import Path

import pytest

from genofinder_eval.external.complex_query_results import (
    analyze,
    compare_tables,
    condition_rows,
    load_public_results,
    returned_candidate_yield,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "results" / "complex_query_evaluation_v1"
CRITERIA = ROOT / "protocols" / "complex-query-evaluation-v1" / "02-expected-criteria-sheet.csv"

CONDITION_FIELDS = [
    "judgment_id", "qid", "accession", "disease_met", "tissue_met", "cell_type_met", "organism_met",
    "modality_met", "design_met", "comparison_groups_met", "time_treatment_or_dose_met",
    "exclusion_violated", "insufficient_evidence",
]
CRITERIA_FIELDS = [
    "query_id", "difficulty", "required_disease", "required_tissue", "required_cell_type",
    "required_organism", "required_modality", "required_design", "required_comparison_groups",
    "required_time_treatment_or_dose", "must_not_contain_or_condition",
]


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _condition(judgment: str, qid: str, accession: str, **values: str) -> dict[str, str]:
    row = {field: "NA" for field in CONDITION_FIELDS}
    row.update({"judgment_id": judgment, "qid": qid, "accession": accession,
                "exclusion_violated": "NA", "insufficient_evidence": "no"})
    row.update(values)
    return row


@pytest.fixture
def tiny(tmp_path: Path) -> Path:
    """Two queries; Q1 requires a disease and has an exclusion, Q2 requires a modality."""
    (tmp_path / "qrels.tsv").write_text(
        "Q1\t0\tGSE1\t3\nQ1\t0\tGSE2\t1\nQ1\t0\tGSE3\t2\nQ2\t0\tGSE4\t0\nQ2\t0\tGSE5\t2\n",
        encoding="utf-8",
    )
    _write(tmp_path / "condition_judgments.csv", CONDITION_FIELDS, [
        _condition("J1", "Q1", "GSE1", disease_met="1", exclusion_violated="no"),
        _condition("J2", "Q1", "GSE2", disease_met="0", exclusion_violated="no"),
        _condition("J3", "Q1", "GSE3", disease_met="1", exclusion_violated="yes"),
        _condition("J4", "Q2", "GSE4", modality_met="0"),
        _condition("J5", "Q2", "GSE5", modality_met="1", insufficient_evidence="yes"),
    ])
    _write(tmp_path / "rankings.csv", ["system", "qid", "rank", "accession"], [
        {"system": "omicsplorer_geo", "qid": "Q1", "rank": "1", "accession": "GSE2"},
        {"system": "omicsplorer_geo", "qid": "Q1", "rank": "2", "accession": "GSE1"},
        {"system": "omicsplorer_geo", "qid": "Q2", "rank": "1", "accession": "GSE5"},
        {"system": "ncbi_geo", "qid": "Q1", "rank": "1", "accession": "GSE3"},
        {"system": "omicsdi_geo", "qid": "Q2", "rank": "1", "accession": "GSE4"},
    ])
    returned = {("omicsplorer_geo", "Q1"): 2, ("omicsplorer_geo", "Q2"): 1, ("ncbi_geo", "Q1"): 1,
                ("ncbi_geo", "Q2"): 0, ("omicsdi_geo", "Q1"): 0, ("omicsdi_geo", "Q2"): 1}
    _write(tmp_path / "responses.csv",
           ["system", "qid", "http_status", "requested_top_k", "returned", "wall_latency_ms",
            "fetched_at_utc", "raw_sha256"],
           [{"system": system, "qid": qid, "http_status": "200", "requested_top_k": "10",
             "returned": str(count), "wall_latency_ms": "100", "fetched_at_utc": "2026-09-02T00:00:00Z",
             "raw_sha256": "0" * 64} for (system, qid), count in sorted(returned.items())])
    criteria = tmp_path / "criteria.csv"
    base = {field: "" for field in CRITERIA_FIELDS}
    _write(criteria, CRITERIA_FIELDS, [
        {**base, "query_id": "Q1", "difficulty": "simple", "required_disease": "d",
         "must_not_contain_or_condition": "x"},
        {**base, "query_id": "Q2", "difficulty": "complex", "required_modality": "m"},
    ])
    return tmp_path


def test_strict_condition_requires_every_condition_and_clean_flags(tiny: Path) -> None:
    results = load_public_results(tiny, tiny / "criteria.csv")
    rows = {(row["system"], row["qid"]): row for row in condition_rows(results)}
    # GSE1 meets the disease requirement with no exclusion violation.
    assert rows[("omicsplorer_geo", "Q1")]["strict_all_conditions_success_at_10"] == 1.0
    # GSE3 violates the exclusion; GSE5 carries an insufficient-evidence flag.
    assert rows[("ncbi_geo", "Q1")]["strict_all_conditions_success_at_10"] == 0.0
    assert rows[("omicsplorer_geo", "Q2")]["strict_all_conditions_success_at_10"] == 0.0
    assert rows[("ncbi_geo", "Q1")]["exclusion_violation_fraction_at_10"] == 1.0
    # An empty response scores zero rather than being dropped.
    assert rows[("ncbi_geo", "Q2")]["strict_all_conditions_success_at_10"] == 0.0


def test_returned_candidate_yield_pools_candidates(tiny: Path) -> None:
    results = load_public_results(tiny, tiny / "criteria.csv")
    rows = {(row["scope"], row["system"]): row for row in returned_candidate_yield(results)}
    omicsplorer = rows[("all", "omicsplorer_geo")]
    assert omicsplorer["returned_candidates"] == 3
    assert omicsplorer["relevant_candidates"] == 2  # GSE1 (3) and GSE5 (2)
    assert omicsplorer["relevant_share_of_returned"] == pytest.approx(2 / 3)
    assert omicsplorer["relevant_per_query"] == pytest.approx(1.0)
    assert rows[("complex", "omicsdi_geo")]["relevant_candidates"] == 0


def test_unjudged_returned_accession_is_rejected(tiny: Path) -> None:
    with (tiny / "rankings.csv").open("a", encoding="utf-8") as handle:
        handle.write("omicsdi_geo,Q1,1,GSE999\n")
    rows = list(csv.DictReader((tiny / "responses.csv").open(encoding="utf-8")))
    for row in rows:
        if (row["system"], row["qid"]) == ("omicsdi_geo", "Q1"):
            row["returned"] = "1"
    _write(tiny / "responses.csv", list(rows[0]), rows)
    with pytest.raises(ValueError, match="unjudged"):
        load_public_results(tiny, tiny / "criteria.csv")


@pytest.mark.skipif(not (PUBLIC / "qrels.tsv").exists(), reason="public results not present")
def test_public_files_reproduce_reported_numbers(tmp_path: Path) -> None:
    outputs = analyze(load_public_results(PUBLIC, CRITERIA), tmp_path)
    summary = {(row["system"], row["metric"]): row for row in outputs["metrics_summary"]}
    ndcg = summary[("omicsplorer_geo", "ndcg_at_10")]
    assert round(ndcg["mean"], 3) == 0.838
    assert (round(ndcg["ci95_low"], 3), round(ndcg["ci95_high"], 3)) == (0.800, 0.873)
    assert round(summary[("ncbi_geo", "ndcg_at_10")]["mean"], 3) == 0.177
    assert round(summary[("omicsdi_geo", "ndcg_at_10")]["mean"], 3) == 0.119
    pairwise = {row["comparator"]: row for row in outputs["pairwise_primary_ndcg"]}
    assert round(pairwise["ncbi_geo"]["mean_difference"], 3) == 0.661
    assert round(pairwise["omicsdi_geo"]["p_value_holm"], 4) == 0.0002
    strict = {row["system"]: row for row in outputs["condition_metrics_summary"]
              if row["metric"] == "strict_all_conditions_success_at_10"}
    assert round(strict["omicsplorer_geo"]["mean"], 3) == 0.567
    yield_rows = {(row["scope"], row["system"]): row
                  for row in outputs["posthoc_returned_candidate_yield"]}
    assert yield_rows[("all", "omicsplorer_geo")]["returned_candidates"] == 600
    assert yield_rows[("all", "omicsplorer_geo")]["relevant_candidates"] == 277
    assert round(yield_rows[("all", "ncbi_geo")]["relevant_share_of_returned"], 3) == 0.734
    common = {row["system"]: row for row in outputs["posthoc_all_systems_nonempty"]}
    assert common["omicsplorer_geo"]["n_queries"] == 14
    assert (round(common["omicsplorer_geo"]["mean_ndcg_at_10"], 3),
            round(common["ncbi_geo"]["mean_ndcg_at_10"], 3),
            round(common["omicsdi_geo"]["mean_ndcg_at_10"], 3)) == (0.762, 0.428, 0.468)


def test_compare_tables_reports_changed_values(tiny: Path, tmp_path: Path) -> None:
    results = load_public_results(tiny, tiny / "criteria.csv")
    committed = tmp_path / "derived"
    outputs = analyze(results, committed)
    assert compare_tables(committed, outputs) == []
    path = committed / "metrics_summary.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = lines[1].split(",")
    first[3] = str(float(first[3]) + 0.001)  # the "mean" column
    lines[1] = ",".join(first)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = compare_tables(committed, outputs)
    assert problems and "metrics_summary" in problems[0]

