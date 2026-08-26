from genofinder_eval.external.ranking_metrics import (
    metrics_for_query,
    paired_primary,
    summarize,
)


def test_ranking_metrics_reward_graded_correct_order() -> None:
    qrels = {"GSE1": 3, "GSE2": 2, "GSE3": 0}
    perfect = metrics_for_query(["GSE1", "GSE2", "GSE3"], qrels)
    reversed_run = metrics_for_query(["GSE3", "GSE2", "GSE1"], qrels)
    assert perfect["ndcg_at_10"] == 1.0
    assert perfect["mrr_at_10"] == 1.0
    assert perfect["success_at_10"] == 1.0
    assert perfect["ndcg_at_10"] > reversed_run["ndcg_at_10"]


def test_summary_and_paired_primary_use_query_pairs() -> None:
    rows = [
        {"system": "omicsplorer_geo", "qid": "q1", "ndcg_at_10": 1.0},
        {"system": "omicsplorer_geo", "qid": "q2", "ndcg_at_10": 0.8},
        {"system": "ncbi_geo", "qid": "q1", "ndcg_at_10": 0.2},
        {"system": "ncbi_geo", "qid": "q2", "ndcg_at_10": 0.4},
        {"system": "omicsdi_geo", "qid": "q1", "ndcg_at_10": 0.3},
        {"system": "omicsdi_geo", "qid": "q2", "ndcg_at_10": 0.5},
    ]
    # Add secondary metrics required by summarize.
    for row in rows:
        for metric in (
            "precision_at_10",
            "recall_at_10_judged",
            "mrr_at_10",
            "success_at_10",
            "bpref",
        ):
            row[metric] = row["ndcg_at_10"]

    summary = summarize(rows, iterations=100, seed=7)
    omics_ndcg = next(
        row for row in summary if row["system"] == "omicsplorer_geo" and row["metric"] == "ndcg_at_10"
    )
    paired = paired_primary(rows, iterations=1000, seed=7)
    assert omics_ndcg["mean"] == 0.9
    assert len(paired) == 2
    assert all(row["mean_difference"] > 0 for row in paired)
    assert all(0 <= row["p_value_holm"] <= 1 for row in paired)
