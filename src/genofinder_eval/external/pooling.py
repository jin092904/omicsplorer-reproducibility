"""Build a blinded, deduplicated relevance-judgment pool from raw runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import secrets
from collections import defaultdict
from pathlib import Path
from typing import Any

from genofinder_eval.external.models import SearchHit, SearchResponse
from genofinder_eval.external.provenance import utc_now, write_json


def load_responses(run_dir: Path) -> list[SearchResponse]:
    responses: list[SearchResponse] = []
    for path in sorted((run_dir / "raw").glob("*/*.json")):
        if path.name.endswith(".failure.json"):
            continue
        responses.append(SearchResponse.model_validate_json(path.read_text(encoding="utf-8")))
    if not responses:
        raise ValueError(f"No successful raw responses under {run_dir / 'raw'}")
    return responses


def _candidate_code(qid: str, canonical_id: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}\0{qid}\0{canonical_id}".encode()).hexdigest()
    return f"C{digest[:12].upper()}"


def _best_hit(hits: list[SearchHit]) -> SearchHit:
    """Choose the richest public display record without using system rank."""
    return max(
        hits,
        key=lambda hit: (
            bool(hit.title),
            len(hit.description),
            len(hit.organism) + len(hit.assay),
            -hit.rank,
        ),
    )


def build_pool(
    responses: list[SearchResponse],
    *,
    salt: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[tuple[str, SearchHit]]] = defaultdict(list)
    query_meta: dict[str, tuple[str, str]] = {}
    for response in responses:
        previous = query_meta.setdefault(response.qid, (response.query_text, response.corpus))
        if previous != (response.query_text, response.corpus):
            raise ValueError(f"Inconsistent query metadata for {response.qid}")
        for hit in response.hits:
            grouped[(response.qid, hit.canonical_id)].append((response.system, hit))

    blind_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for (qid, canonical_id), system_hits in sorted(grouped.items()):
        hits = [hit for _, hit in system_hits]
        display = _best_hit(hits)
        candidate_code = _candidate_code(qid, canonical_id, salt)
        systems = sorted({system for system, _ in system_hits})
        ranks = {
            system: min(hit.rank for observed_system, hit in system_hits if observed_system == system)
            for system in systems
        }
        query_text, corpus = query_meta[qid]
        blind_rows.append(
            {
                "qid": qid,
                "candidate_code": candidate_code,
                "query_text": query_text,
                "corpus": corpus,
                "title": display.title,
                "description": display.description,
                "organism": " | ".join(display.organism),
                "assay": " | ".join(display.assay),
                "publication_date": display.publication_date or "",
                "source_url": display.url or "",
                "relevance_0_3": "",
                "annotator_id": "",
                "notes": "",
            }
        )
        key_rows.append(
            {
                "qid": qid,
                "candidate_code": candidate_code,
                "canonical_id": canonical_id,
                "systems": "|".join(systems),
                "ranks_json": json.dumps(ranks, sort_keys=True, separators=(",", ":")),
                "native_ids": "|".join(sorted({hit.native_id for hit in hits})),
            }
        )
    return blind_rows, key_rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty pool: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--salt", help="Optional fixed salt for exact reruns; keep restricted")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run.resolve()
    output = (args.output or run_dir).resolve()
    salt = args.salt or secrets.token_hex(32)
    blind, key = build_pool(load_responses(run_dir), salt=salt)
    _write_csv(output / "annotation_template.csv", blind)
    _write_csv(output / "pool_key.restricted.csv", key)
    write_json(
        output / "pool_manifest.restricted.json",
        {
            "created_at_utc": utc_now(),
            "salt": salt,
            "candidates": len(blind),
            "queries": len({row["qid"] for row in blind}),
            "warning": "Do not give this manifest or pool_key to annotators.",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
