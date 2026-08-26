"""Combine measured browser JSONL runs without inventing or averaging constants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from genofinder_eval.external.browser_latency import (
    _append_jsonl,
    _write_summary,
    summarize_by_category,
    summarize_observations,
)
from genofinder_eval.external.provenance import sha256_file, utc_now, write_json


def combine(inputs: list[Path], output: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=True)
    combined = output / "browser_timings_combined.jsonl"
    if combined.exists():
        combined.unlink()
    for path in inputs:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                row["source_run"] = str(path.resolve())
                rows.append(row)
                _append_jsonl(combined, row)
    if not rows:
        raise ValueError("No browser observations found")
    _write_summary(output / "browser_latency_summary.csv", summarize_observations(rows))
    _write_summary(output / "browser_latency_by_category.csv", summarize_by_category(rows))
    write_json(
        output / "combined_manifest.json",
        {
            "created_at_utc": utc_now(),
            "inputs": [
                {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in inputs
            ],
            "observations": len(rows),
            "warning": "Runs are combined by concatenation; cache/model states remain separate metrics.",
        },
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    combine([path.resolve() for path in args.input], args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
