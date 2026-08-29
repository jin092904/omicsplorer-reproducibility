#!/usr/bin/env python3
"""Recompute and verify the committed public metadata pilot summaries."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from genofinder_eval.metadata_pilot import load_selection_spec
from genofinder_eval.metadata_pilot_public import (
    aggregate_results,
    by_stratum_rows,
    timing_rows,
    validate_public_observations,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "results/metadata_enrichment_pilot_v1"
OUTPUT_DIR = ROOT / "build/metadata_enrichment_pilot_v1"
SPEC = ROOT / "protocols/metadata-enrichment-pilot-v1/selection-spec.json"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalized_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{key: str(value) for key, value in row.items()} for row in rows]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    observations_path = SOURCE_DIR / "metadata_pilot_observations_public.jsonl"
    rows = read_jsonl(observations_path)
    spec = load_selection_spec(SPEC)
    expected_by_stratum = {
        str(definition["label"]): int(definition["target_n"])
        for definition in spec["strata"]
    }
    validate_public_observations(
        rows,
        expected_n=sum(expected_by_stratum.values()),
        expected_by_stratum=expected_by_stratum,
    )

    by_stratum = by_stratum_rows(rows, spec["strata"])
    timings = timing_rows(rows, spec["strata"])
    if normalized_csv_rows(by_stratum) != read_csv(
        SOURCE_DIR / "metadata_pilot_by_stratum.csv"
    ):
        raise ValueError("committed by-stratum summary differs from public observations")
    if normalized_csv_rows(timings) != read_csv(
        SOURCE_DIR / "metadata_pilot_timing_summary.csv"
    ):
        raise ValueError("committed timing summary differs from public observations")

    summary = json.loads((SOURCE_DIR / "metadata_pilot_summary.json").read_text())
    if summary.get("results") != aggregate_results(rows):
        raise ValueError("committed JSON summary differs from public observations")
    digest = hashlib.sha256(observations_path.read_bytes()).hexdigest()
    if summary.get("provenance", {}).get("public_observations_sha256") != digest:
        raise ValueError("public observation checksum differs from the JSON summary")

    write_csv(OUTPUT_DIR / "metadata_pilot_by_stratum.csv", by_stratum)
    write_csv(OUTPUT_DIR / "metadata_pilot_timing_summary.csv", timings)
    print(f"verified {len(rows)} public observations; wrote summaries under {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
