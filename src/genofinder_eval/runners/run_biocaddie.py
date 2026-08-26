"""bioCADDIE 2016 evaluation runner.

15 query × 4 mode = 60 search calls. 각 query top-100 retrieval.

흐름:
  1. preflight: API health
  2. warmup: reranker cold start 회피
  3. corpus 지정: `corpus="biocaddie_2016_eval"` (별도 임시 인덱스)
  4. 4 mode × 15 query 순차 호출
  5. runfile 저장 → results/raw/biocaddie_<mode>_<timestamp>.run
  6. metric 계산 → results/aggregated/biocaddie_results.csv
"""
from __future__ import annotations

import asyncio
import csv
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from genofinder_eval.adapters.beir_compat import load_qrels, load_queries, write_run
from genofinder_eval.client.geno_finder import GenoFinderClient
from genofinder_eval.client.search_modes import SearchMode
from genofinder_eval.metrics.trec_metrics import (
    aggregate_macro,
    compute_inf_ndcg,
    evaluate_run,
    runfile_to_pytrec_run,
)
from genofinder_eval.runners.warmup import warmup_reranker
from genofinder_eval.utils.logging import configure_logging, get_logger
from genofinder_eval.utils.seed import set_global_seed

logger = get_logger(__name__)


async def run(
    data_dir: Path | None = None,
    results_dir: Path | None = None,
    top_k: int = 100,
) -> Path:
    """bioCADDIE 평가 일괄 실행. 결과 CSV 경로 반환.

    Returns:
        results/aggregated/biocaddie_results.csv 의 Path.
    """
    set_global_seed()
    configure_logging()

    data_dir = data_dir or Path(os.environ.get("EVAL_DATA_DIR", "data")) / "biocaddie"
    results_dir = results_dir or Path(os.environ.get("EVAL_RESULTS_DIR", "results"))
    raw_dir = results_dir / "raw"
    agg_dir = results_dir / "aggregated"
    raw_dir.mkdir(parents=True, exist_ok=True)
    agg_dir.mkdir(parents=True, exist_ok=True)

    queries = load_queries(data_dir / "queries.jsonl")
    qrels = load_qrels(data_dir / "qrels" / "test.tsv")
    logger.info("biocaddie_loaded", queries=len(queries), qrels_qids=len(qrels))

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = agg_dir / "biocaddie_results.csv"

    async with GenoFinderClient() as client:
        await warmup_reranker(client)

        rows: list[dict[str, float | str]] = []
        for mode in SearchMode:
            runs_per_query: dict[str, list[tuple[str, float]]] = {}
            for qid, qtext in queries.items():
                t0 = time.perf_counter()
                resp = await client.search(
                    query_text=qtext,
                    top_k=top_k,
                    mode=mode,
                    corpus="biocaddie_2016_eval",
                )
                wall = time.perf_counter() - t0
                runs_per_query[qid] = [(r.dataset_id, r.score) for r in resp.results]
                logger.info(
                    "biocaddie_query_done",
                    mode=str(mode), qid=qid, n_results=len(resp.results),
                    wall_s=round(wall, 3),
                )

            # Save runfile (atomic)
            run_path = raw_dir / f"biocaddie_{mode}_{timestamp}.run"
            write_run(run_path, runs_per_query, tag=f"genofinder-{mode}")

            # Compute metrics
            pytrec_run = runfile_to_pytrec_run(runs_per_query)
            trec_metrics = evaluate_run(qrels, pytrec_run)
            inf_ndcg = compute_inf_ndcg(qrels, pytrec_run)
            for measure, per_q in trec_metrics.items():
                agg = aggregate_macro(per_q)
                rows.append({
                    "dataset": "biocaddie_2016", "mode": str(mode),
                    "metric": measure, "mean": agg["mean"], "median": agg["median"],
                    "std": agg["std"], "p95": agg["p95"], "n_queries": len(per_q),
                })
            agg_inf = aggregate_macro(inf_ndcg)
            rows.append({
                "dataset": "biocaddie_2016", "mode": str(mode),
                "metric": "infNDCG", "mean": agg_inf["mean"], "median": agg_inf["median"],
                "std": agg_inf["std"], "p95": agg_inf["p95"], "n_queries": len(inf_ndcg),
            })

    # Atomic CSV write
    tmp = csv_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
    logger.info("biocaddie_csv_written", path=str(csv_path), rows=len(rows))
    return csv_path


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
