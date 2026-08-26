"""TREC metric known-answer test — pytrec_eval + infNDCG reference impl."""
from __future__ import annotations

from genofinder_eval.metrics.trec_metrics import (
    aggregate_macro,
    compute_inf_ndcg,
    evaluate_run,
)


def test_aggregate_macro_empty() -> None:
    out = aggregate_macro({})
    assert out["mean"] == 0.0


def test_aggregate_macro_simple() -> None:
    out = aggregate_macro({"Q1": 0.5, "Q2": 0.7, "Q3": 0.9})
    assert abs(out["mean"] - 0.7) < 1e-6
    assert abs(out["median"] - 0.7) < 1e-6


def test_inf_ndcg_perfect_ranking() -> None:
    """relevance 3, 2, 1 의 doc 을 정확한 순서로 retrieve 하면 infNDCG=1.0."""
    qrels = {"Q1": {"docA": 3, "docB": 2, "docC": 1}}
    run = {"Q1": {"docA": 10.0, "docB": 5.0, "docC": 1.0}}
    out = compute_inf_ndcg(qrels, run)
    assert abs(out["Q1"] - 1.0) < 1e-6


def test_inf_ndcg_reverse_ranking_low() -> None:
    """relevance 3, 2, 1 의 doc 을 *역순* 으로 retrieve → infNDCG 낮음."""
    qrels = {"Q1": {"docA": 3, "docB": 2, "docC": 1}}
    run = {"Q1": {"docC": 10.0, "docB": 5.0, "docA": 1.0}}
    out = compute_inf_ndcg(qrels, run)
    assert 0.0 < out["Q1"] < 0.7  # perfect 1.0 보다 훨씬 낮음


def test_inf_ndcg_empty_run() -> None:
    qrels = {"Q1": {"docA": 3}}
    run = {"Q1": {}}
    out = compute_inf_ndcg(qrels, run)
    assert out["Q1"] == 0.0


def test_evaluate_run_pytrec_ndcg10() -> None:
    """pytrec_eval 의 ndcg_cut_10 — perfect ranking → 1.0."""
    qrels = {"Q1": {"docA": 3, "docB": 2, "docC": 1, "docD": 0}}
    run = {"Q1": {"docA": 10.0, "docB": 5.0, "docC": 1.0, "docD": 0.5}}
    out = evaluate_run(qrels, run)
    assert abs(out["ndcg_cut_10"]["Q1"] - 1.0) < 1e-6


def test_evaluate_run_pytrec_mrr() -> None:
    """첫 번째 relevant 가 rank 2 → recip_rank = 0.5."""
    qrels = {"Q1": {"docA": 1, "docB": 0}}
    run = {"Q1": {"docB": 10.0, "docA": 5.0}}
    out = evaluate_run(qrels, run)
    assert abs(out["recip_rank"]["Q1"] - 0.5) < 1e-6
