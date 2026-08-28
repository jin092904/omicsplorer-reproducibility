#!/usr/bin/env python3
"""Select the metadata-enrichment pilot in an explicit read-only transaction."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from genofinder_eval.metadata_pilot import (
    load_selection_spec,
    public_summary,
    select_records,
    utc_now,
    write_private_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "protocols/metadata-enrichment-pilot-v1/selection-spec.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        parser.error("DATABASE_URL is required")

    spec = load_selection_spec(args.spec)
    spec_sha256 = hashlib.sha256(args.spec.read_bytes()).hexdigest()
    records = asyncio.run(select_records(database_url, spec))
    write_private_jsonl(args.private_manifest, records)

    summary = public_summary(
        records,
        spec=spec,
        spec_sha256=spec_sha256,
        generated_at_utc=utc_now(),
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"selected_total={summary['selected_total']}")
    print(f"private_manifest={args.private_manifest} mode=0600")
    print(f"summary={args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
