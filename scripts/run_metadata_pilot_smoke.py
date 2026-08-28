#!/usr/bin/env python3
"""Run one write-disabled Sol4 feasibility record per prespecified stratum."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from genofinder_eval.metadata_pilot import load_selection_spec
from genofinder_eval.metadata_pilot_runner import run_smoke

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "protocols/metadata-enrichment-pilot-v1/selection-spec.json"
DEFAULT_CONTRACT = ROOT / "protocols/metadata-enrichment-pilot-v1/frozen-contract"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--selection-spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--contract-dir", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--per-stratum", type=int, default=1)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11437")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--opensearch-url", default="http://127.0.0.1:9200")
    args = parser.parse_args()

    summary = asyncio.run(
        run_smoke(
            database_url=os.environ.get("DATABASE_URL", ""),
            selection_manifest=args.selection_manifest.resolve(),
            selection_spec=load_selection_spec(args.selection_spec.resolve()),
            contract_dir=args.contract_dir.resolve(),
            product_root=args.product_root.resolve(),
            output_path=args.output.resolve(),
            ollama_url=args.ollama_url,
            qdrant_url=args.qdrant_url,
            opensearch_url=args.opensearch_url,
            per_stratum=args.per_stratum,
            preflight_only=args.preflight_only,
        )
    )
    public = {
        key: summary[key]
        for key in (
            "status",
            "mode",
            "selected_n",
            "outcome_counts",
            "write_guard_passed",
            "elapsed_seconds",
        )
    }
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    if not summary["write_guard_passed"]:
        return 3
    return 0 if summary["status"] in {"preflight_complete", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
