from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from genofinder_eval.external.complex_query_results import compare_tables
from genofinder_eval.external.complex_query_results_v2 import analyze_v2, load_public_results_v2

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "results" / "complex_query_evaluation_v2"
V1 = ROOT / "results" / "complex_query_evaluation_v1"
CRITERIA = ROOT / "protocols" / "complex-query-evaluation-v1" / "02-expected-criteria-sheet.csv"

pytestmark = pytest.mark.skipif(not (PUBLIC / "qrels.tsv").exists(), reason="public v2 results not present")


@pytest.fixture(scope="module")
def outputs() -> dict:
    return analyze_v2(load_public_results_v2(PUBLIC, V1, CRITERIA), None)


def test_public_files_reproduce_reported_numbers(outputs: dict) -> None:
    summary = {(row["system"], row["metric"]): row for row in outputs["metrics_summary"]}
    ndcg = summary[("omicsplorer_fixed_index", "ndcg_at_10")]
    assert round(ndcg["mean"], 3) == 0.657
    assert (round(ndcg["ci95_low"], 3), round(ndcg["ci95_high"], 3)) == (0.608, 0.706)
    assert round(summary[("ncbi_geo_keyword", "ndcg_at_10")]["mean"], 3) == 0.483
    assert round(summary[("omicsdi_geo_keyword", "ndcg_at_10")]["mean"], 3) == 0.526
    assert [round(summary[(system, "strict_success_at_10")]["mean"], 3)
            for system in ("omicsplorer_fixed_index", "ncbi_geo_keyword", "omicsdi_geo_keyword")
            ] == [0.567, 0.617, 0.567]
    pairwise = {row["comparator"]: row for row in outputs["pairwise_primary_ndcg"]}
    assert round(pairwise["ncbi_geo_keyword"]["mean_difference"], 3) == 0.173
    assert round(pairwise["ncbi_geo_keyword"]["p_value_holm"], 4) == 0.0006
    assert round(pairwise["omicsdi_geo_keyword"]["p_value_holm"], 4) == 0.0066
    overlap = {row["arms"]: row["relevant_candidates"] for row in outputs["relevant_overlap"]}
    assert (overlap["A"], overlap["B"], overlap["C"], overlap["A+B+C"], sum(overlap.values())) == (
        251, 167, 148, 23, 698)
    pool = {row["system"]: row for row in outputs["v1_systems_extended_pool"] if row["metric"] == "ndcg_at_10"}
    assert round(pool["omicsplorer_geo"]["extended_pool"], 3) == 0.608
    retest = {row["v2_values"]: row for row in outputs["retest_agreement"]}
    assert retest["received"]["n_pairs"] == 74
    assert round(retest["received"]["quadratic_weighted_kappa"], 3) == 0.911


def test_committed_tables_match_the_recomputation(outputs: dict) -> None:
    assert compare_tables(PUBLIC / "derived", outputs) == []


def test_unjudged_ranked_accession_is_rejected(tmp_path: Path) -> None:
    copy = tmp_path / "v2"
    shutil.copytree(PUBLIC, copy)
    with (copy / "rankings.csv").open("a", encoding="utf-8") as handle:
        handle.write("ncbi_geo_keyword,C01,11,GSE0000001\n")
    with pytest.raises(ValueError, match=r"bad ranks|unjudged"):
        load_public_results_v2(copy, V1, CRITERIA)
