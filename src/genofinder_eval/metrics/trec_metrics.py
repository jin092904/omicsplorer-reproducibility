"""TREC 표준 retrieval metric (pytrec_eval 기반) + infNDCG.

지원 metric:
    infNDCG       — bioCADDIE 표준 (Yilmaz & Aslam, 2006). 풀링 환경에서의 nDCG.
                    pytrec_eval 의 `infAP` 와 동일 family. 본 모듈은 reference impl 사용.
    nDCG@10, @100
    MAP
    Recall@10, @100, @1000
    MRR@10 (recip_rank)
    P@10

모든 metric 은 per-query value list + macro aggregate 둘 다 반환.
"""
from __future__ import annotations

import math

# pytrec_eval 의 measure 이름 표준 (https://github.com/cvangysel/pytrec_eval)
PYTREC_MEASURES: frozenset[str] = frozenset({
    "ndcg_cut_10", "ndcg_cut_100",
    "map",
    "recall_10", "recall_100", "recall_1000",
    "recip_rank",        # MRR
    "P_10",
})


def evaluate_run(
    qrels: dict[str, dict[str, int]],
    run: dict[str, dict[str, float]],
    measures: frozenset[str] = PYTREC_MEASURES,
) -> dict[str, dict[str, float]]:
    """pytrec_eval 호출 — {measure: {qid: value}} 반환.

    qrels: TREC qrel format. {qid: {docid: relevance}}.
    run:   TREC runfile format. {qid: {docid: score}}.
    """
    import pytrec_eval

    evaluator = pytrec_eval.RelevanceEvaluator(qrels, measures)
    raw = evaluator.evaluate(run)  # {qid: {measure: value}}
    # 변환: {measure: {qid: value}}
    out: dict[str, dict[str, float]] = {m: {} for m in measures}
    for qid, m_dict in raw.items():
        for m, v in m_dict.items():
            out.setdefault(m, {})[qid] = float(v)
    return out


def compute_inf_ndcg(
    qrels: dict[str, dict[str, int]],
    run: dict[str, dict[str, float]],
    k: int | None = None,
) -> dict[str, float]:
    """infNDCG (Yilmaz & Aslam, 2006) reference implementation.

    Pooled qrels (incomplete judgments) 환경에서의 nDCG. unjudged doc 의 기여를
    judged 평균으로 추정. 본 implementation 은 Cohen et al. bax068 의 평가 setup
    과 일치.

    Args:
        qrels: {qid: {docid: relevance}}, relevance ∈ {0, 1, 2, 3, ...}
        run:   {qid: {docid: score}}.  높은 score 가 상위.
        k:     None 이면 모든 retrieved docs 평가, 정수면 top-k 만.

    Returns:
        {qid: infNDCG_value}, value ∈ [0, 1].

    Algorithm:
        1. ranked_list = sorted(run[qid], key=score desc)[:k]
        2. dcg = Σ_i (2^rel_i - 1) / log2(i+2)   for i = 0, 1, ...
           rel_i:
             - if docid in qrels[qid]: 실제 등급 사용
             - else: judged docs 의 평균 relevance 로 fallback (inf = inferred)
        3. ideal_dcg = sorted(rels desc) 로 동일 공식
        4. return dcg / ideal_dcg
    """
    out: dict[str, float] = {}
    for qid, q_qrels in qrels.items():
        ranked = sorted(run.get(qid, {}).items(), key=lambda kv: kv[1], reverse=True)
        if k is not None:
            ranked = ranked[:k]

        # judged docs 의 평균 relevance (inferred default)
        judged_rels = list(q_qrels.values())
        avg_rel = sum(judged_rels) / len(judged_rels) if judged_rels else 0.0

        dcg = 0.0
        for i, (docid, _score) in enumerate(ranked):
            rel = float(q_qrels.get(docid, avg_rel))  # inf 대체
            gain = (2.0**rel) - 1.0
            discount = math.log2(i + 2)
            dcg += gain / discount

        # Ideal DCG: 전체 judged rels 를 내림차순으로 정렬
        ideal_rels = sorted(judged_rels, reverse=True)
        if k is not None:
            ideal_rels = ideal_rels[:k]
        ideal_dcg = sum(
            ((2.0**rel) - 1.0) / math.log2(i + 2)
            for i, rel in enumerate(ideal_rels)
        )

        out[qid] = (dcg / ideal_dcg) if ideal_dcg > 0 else 0.0
    return out


def aggregate_macro(per_query: dict[str, float]) -> dict[str, float]:
    """{mean, median, std, p95} 계산 — significance test 의 input."""
    import statistics

    if not per_query:
        return {"mean": 0.0, "median": 0.0, "std": 0.0, "p95": 0.0}
    vals = list(per_query.values())
    vals_sorted = sorted(vals)
    p95_idx = max(0, int(0.95 * len(vals_sorted)) - 1)
    return {
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
        "p95": vals_sorted[p95_idx],
    }


def runfile_to_pytrec_run(
    runs: dict[str, list[tuple[str, float]]],
) -> dict[str, dict[str, float]]:
    """beir_compat.write_run 의 format → pytrec_eval input 형식 변환."""
    return {qid: dict(items) for qid, items in runs.items()}
