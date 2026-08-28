#!/usr/bin/env python3
"""Run or resume a write-disabled metadata feasibility batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from genofinder_eval.metadata_pilot import load_selection_spec
from genofinder_eval.metadata_pilot_batch import run_batch

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "protocols/metadata-enrichment-pilot-v1/selection-spec.json"
DEFAULT_CONTRACT = ROOT / "protocols/metadata-enrichment-pilot-v1/frozen-contract"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--selection-spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--contract-dir", type=Path, default=DEFAULT_CONTRACT)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all-records", action="store_true")
    selection.add_argument("--per-stratum", type=int)
    parser.add_argument("--failure-stop", type=int, default=5)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11437")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--opensearch-url", default="http://127.0.0.1:9200")
    args = parser.parse_args()

    manifest = asyncio.run(
        run_batch(
            repo_root=ROOT,
            database_url=os.environ.get("DATABASE_URL", ""),
            selection_manifest=args.selection_manifest.resolve(),
            selection_spec=load_selection_spec(args.selection_spec.resolve()),
            contract_dir=args.contract_dir.resolve(),
            product_root=args.product_root.resolve(),
            run_dir=args.run_dir.resolve(),
            ollama_url=args.ollama_url,
            qdrant_url=args.qdrant_url,
            opensearch_url=args.opensearch_url,
            all_records=args.all_records,
            per_stratum=args.per_stratum,
            failure_stop=args.failure_stop,
            resume=args.resume,
        )
    )
    public = {
        key: manifest.get(key)
        for key in ("status", "processed_n", "outcome_counts", "write_guard_passed")
    }
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return {
        "complete": 0,
        "complete_with_failures": 2,
        "failed_write_guard": 3,
    }.get(str(manifest["status"]), 4)


if __name__ == "__main__":
    raise SystemExit(main())
