"""Generate and score a fixed-seed GEO known-item pilot benchmark."""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from genofinder_eval.external.models import QuerySpec
from genofinder_eval.external.pooling import load_responses
from genofinder_eval.external.provenance import sha256_file, utc_now, write_json
from genofinder_eval.external.runner import load_queries

_ACCESSION_RE = re.compile(r"\bGSE\d+\b", re.I)


def generate_queries(run_dir: Path, output: Path, *, n: int, seed: int) -> list[QuerySpec]:
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for response in load_responses(run_dir):
        for hit in response.hits:
            candidates[hit.canonical_id].append((response.system, hit.title))
    eligible: list[tuple[str, str]] = []
    for accession, observations in candidates.items():
        systems = {system for system, _ in observations}
        if not {"ncbi_geo", "omicsdi_geo"}.issubset(systems):
            continue
        titles = [title.strip() for _, title in observations if title.strip()]
        if not titles:
            continue
        title = max(titles, key=len)
        query = " ".join(_ACCESSION_RE.sub("", title).split())
        if len(query.split()) < 5:
            continue
        eligible.append((accession, query))
    if len(eligible) < n:
        raise ValueError(f"Only {len(eligible)} eligible common items; requested {n}")
    selected = random.Random(seed).sample(sorted(eligible), n)
    queries = [
        QuerySpec(
            qid=f"known_{accession}",
            text=query,
            category="known_item_title",
            corpus="geo",
            phase="known_item",
            target_accession=accession,
            provenance=(
                "Fixed-seed sample from accessions observed in both NCBI GEO and OmicsDI "
                "during the frozen 30-query pilot; exact source title with accession removed."
            ),
        )
        for accession, query in selected
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(query.model_dump_json() + "\n" for query in queries), encoding="utf-8"
    )
    write_json(
        output.with_suffix(".manifest.json"),
        {
            "created_at_utc": utc_now(),
            "source_run": str(run_dir.resolve()),
            "seed": seed,
            "requested_n": n,
            "eligible_n": len(eligible),
            "selection_frame": "Observed in both NCBI GEO and OmicsDI pilot top-10 pools",
            "limitation": "Pilot known-item sample; not human topical relevance.",
        },
    )
    return queries


def score(run_dir: Path, query_file: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets = {
        query.qid: query.target_accession for query in load_queries(query_file)
        if query.target_accession
    }
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    systems = [str(value) for value in manifest["systems"]]
    responses = {(response.system, response.qid): response for response in load_responses(run_dir)}
    failures = {
        (path.parent.name, path.name.removesuffix(".failure.json"))
        for path in (run_dir / "raw").glob("*/*.failure.json")
    }
    rows: list[dict[str, Any]] = []
    for system in systems:
        for qid, target in targets.items():
            response = responses.get((system, qid))
            rank = None if response is None else next(
                (hit.rank for hit in response.hits if hit.canonical_id == target), None
            )
            request_outcome = (
                "success" if response is not None
                else "failure" if (system, qid) in failures
                else "missing"
            )
            rows.append(
                {
                    "system": system,
                    "qid": qid,
                    "target_accession": target,
                    "request_outcome": request_outcome,
                    "rank": rank or "",
                    "reciprocal_rank": 1 / rank if rank else 0.0,
                    "hit_at_1": int(rank is not None and rank <= 1),
                    "hit_at_5": int(rank is not None and rank <= 5),
                    "hit_at_10": int(rank is not None and rank <= 10),
                    "hit_at_50": int(rank is not None and rank <= 50),
                }
            )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["system"])].append(row)
    summaries = []
    for system, system_rows in sorted(grouped.items()):
        summaries.append(
            {
                "system": system,
                "n_queries": len(system_rows),
                "request_failure_rate": statistics.fmean(
                    row["request_outcome"] != "success" for row in system_rows
                ),
                "mrr_at_50": statistics.fmean(float(row["reciprocal_rank"]) for row in system_rows),
                **{
                    field: statistics.fmean(float(row[field]) for row in system_rows)
                    for field in ("hit_at_1", "hit_at_5", "hit_at_10", "hit_at_50")
                },
            }
        )
    return rows, summaries


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--source-run", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--n", type=int, default=30)
    generate.add_argument("--seed", type=int, default=20260720)
    evaluate = sub.add_parser("score")
    evaluate.add_argument("--run", type=Path, required=True)
    evaluate.add_argument("--queries", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate_queries(args.source_run.resolve(), args.output.resolve(), n=args.n, seed=args.seed)
        return 0
    output = (args.output or args.run).resolve()
    per_query, summary = score(args.run.resolve(), args.queries.resolve())
    _write_csv(output / "known_item_per_query.csv", per_query)
    _write_csv(output / "known_item_summary.csv", summary)
    write_json(
        output / "known_item_metrics_manifest.json",
        {
            "created_at_utc": utc_now(),
            "query_file": str(args.queries.resolve()),
            "query_file_sha256": sha256_file(args.queries.resolve()),
            "interpretation": "Known-item title retrieval pilot; not topical relevance.",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
