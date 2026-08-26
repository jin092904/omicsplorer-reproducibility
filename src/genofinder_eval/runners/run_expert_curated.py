"""Expert-curated 30q evaluation runner.

30 query × 4 mode × 2 lang = 240 search calls. 각 query top-100 retrieval.

흐름:
  1. preflight + warmup
  2. corpus="production" (우리 v1.0 인덱스)
  3. 4 mode × 30 query × {EN, KO} 순차 호출
  4. TREC metric + facet satisfaction 계산
  5. results/aggregated/expert_curated_results.csv (long-form)
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from genofinder_eval.adapters.beir_compat import load_qrels, write_run
from genofinder_eval.adapters.expert_curated_30 import load_queries_paired
from genofinder_eval.client.geno_finder import GenoFinderClient
from genofinder_eval.client.search_modes import SearchMode
from genofinder_eval.metrics.facet_satisfaction import facet_satisfaction_at_k
from genofinder_eval.metrics.trec_metrics import (
    aggregate_macro,
    evaluate_run,
    runfile_to_pytrec_run,
)
from genofinder_eval.runners.warmup import warmup_reranker
from genofinder_eval.utils.logging import configure_logging, get_logger
from genofinder_eval.utils.seed import set_global_seed

logger = get_logger(__name__)


def _load_facet_judgments(path: Path) -> dict[str, dict[str, str | None]]:
    """qid → expected_facets dict."""
    out: dict[str, dict[str, str | None]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["qid"]] = row.get("expected", {})
    return out


async def run(
    data_dir: Path | None = None,
    results_dir: Path | None = None,
    top_k: int = 100,
) -> Path:
    """Expert-curated 30q 평가. 결과 CSV 경로 반환."""
    set_global_seed()
    configure_logging()

    data_dir = data_dir or Path(os.environ.get("EVAL_DATA_DIR", "data")) / "expert_curated_30"
    results_dir = results_dir or Path(os.environ.get("EVAL_RESULTS_DIR", "results"))
    raw_dir = results_dir / "raw"
    agg_dir = results_dir / "aggregated"
    raw_dir.mkdir(parents=True, exist_ok=True)
    agg_dir.mkdir(parents=True, exist_ok=True)

    queries = load_queries_paired(
        data_dir / "queries_en.jsonl",
        data_dir / "queries_ko.jsonl",
    )
    qrels = load_qrels(data_dir / "qrels.tsv")
    facet_judgments = _load_facet_judgments(data_dir / "facet_judgments.jsonl")
    logger.info(
        "expert_loaded",
        queries=len(queries), qrels_qids=len(qrels), facets=len(facet_judgments),
    )

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = agg_dir / "expert_curated_results.csv"

    rows: list[dict[str, Any]] = []
    async with GenoFinderClient() as client:
        await warmup_reranker(client)

        languages: tuple[Literal["en", "ko"], ...] = ("en", "ko")
        for mode in SearchMode:
            for lang in languages:
                runs_per_query: dict[str, list[tuple[str, float]]] = {}
                facet_per_query: dict[str, float] = {}
                for qid, q in queries.items():
                    qtext = q["text_en"] if lang == "en" else q["text_ko"]
                    t0 = time.perf_counter()
                    resp = await client.search(
                        query_text=qtext,
                        top_k=top_k,
                        mode=mode,
                        lang=lang,
                        corpus="production",
                    )
                    wall = time.perf_counter() - t0
                    runs_per_query[qid] = [(r.dataset_id, r.score) for r in resp.results]

                    # Facet satisfaction — top-10
                    expected_facets = facet_judgments.get(qid, {})
                    docs_for_facet = [
                        {
                            "disease_ids": r.disease_ids,
                            "tissue_ids": r.tissue_ids,
                            "cell_type_ids": r.cell_type_ids,
                            "modality": r.modality,
                        }
                        for r in resp.results[:10]
                    ]
                    sat = facet_satisfaction_at_k(expected_facets, docs_for_facet, k=10)
                    facet_per_query[qid] = sat["macro"]
                    logger.info(
                        "expert_query_done",
                        mode=str(mode), lang=lang, qid=qid, wall_s=round(wall, 3),
                        facet_sat=round(sat["macro"], 3),
                    )

                # Runfile
                run_path = raw_dir / f"expert_{mode}_{lang}_{timestamp}.run"
                write_run(run_path, runs_per_query, tag=f"genofinder-{mode}-{lang}")

                # TREC metrics
                pytrec_run = runfile_to_pytrec_run(runs_per_query)
                trec_metrics = evaluate_run(qrels, pytrec_run)
                for measure, per_q in trec_metrics.items():
                    agg = aggregate_macro(per_q)
                    rows.append({
                        "dataset": "expert_curated_30", "mode": str(mode), "lang": lang,
                        "metric": measure, "mean": agg["mean"], "median": agg["median"],
                        "std": agg["std"], "p95": agg["p95"], "n_queries": len(per_q),
                    })
                # Facet satisfaction aggregate
                fagg = aggregate_macro(facet_per_query)
                rows.append({
                    "dataset": "expert_curated_30", "mode": str(mode), "lang": lang,
                    "metric": "facet_satisfaction_macro",
                    "mean": fagg["mean"], "median": fagg["median"],
                    "std": fagg["std"], "p95": fagg["p95"], "n_queries": len(facet_per_query),
                })

    tmp = csv_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
    logger.info("expert_csv_written", path=str(csv_path), rows=len(rows))
    return csv_path


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
