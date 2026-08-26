#!/usr/bin/env python3
"""Remove deployment-specific fields from an OmicsPlorer browser timing JSONL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PUBLIC_FIELDS = (
    "run_sequence",
    "repeat",
    "qid",
    "category",
    "query_text",
    "fetched_at_utc",
    "browser",
    "browser_version",
    "browser_cache_state",
    "query_cache_state",
    "model_cache_state",
    "timeout_ms",
    "metric",
    "outcome",
    "elapsed_ms",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="private browser_timings.jsonl")
    parser.add_argument("output", type=Path, help="public derived JSONL")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        source = json.loads(line)
        missing = [field for field in PUBLIC_FIELDS if field not in source]
        if missing:
            raise ValueError(f"line {line_number} is missing required fields: {missing}")
        rows.append({field: source[field] for field in PUBLIC_FIELDS})

    if len(rows) != 240:
        raise ValueError(f"expected 240 timing rows, found {len(rows)}")
    if len({(row["run_sequence"], row["metric"]) for row in rows}) != len(rows):
        raise ValueError("duplicate (run_sequence, metric) observation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} public observations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
