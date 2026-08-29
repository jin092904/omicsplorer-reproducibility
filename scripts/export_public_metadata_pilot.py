#!/usr/bin/env python3
"""Export identifier-free aggregate evidence from a private metadata pilot run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from genofinder_eval.metadata_pilot import load_selection_spec, validate_records
from genofinder_eval.metadata_pilot_batch import load_result_chain, ordered_all_records
from genofinder_eval.metadata_pilot_public import (
    aggregate_results,
    by_stratum_rows,
    public_observations,
    timing_rows,
    validate_public_observations,
)
from genofinder_eval.metadata_pilot_runner import load_private_manifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "protocols/metadata-enrichment-pilot-v1/selection-spec.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--selection-spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.run_dir / "run-manifest.json"
    results_path = args.run_dir / "results.private.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chain = load_result_chain(results_path)
    private_results = [envelope["result"] for envelope in chain]

    spec = load_selection_spec(args.selection_spec)
    selected = load_private_manifest(args.selection_manifest)
    validate_records(selected, spec)
    ordered = ordered_all_records(selected, spec)
    if len(chain) != len(ordered) or len(chain) != int(manifest["plan"]["target_n"]):
        raise ValueError("private results do not cover the frozen target")
    if [result["record_key_sha256"] for result in private_results] != [
        record["record_key_sha256"] for record in ordered
    ]:
        raise ValueError("private results differ from the frozen target order")
    if [result["input_sha256"] for result in private_results] != [
        record["source_input_sha256"] for record in ordered
    ]:
        raise ValueError("private input hashes differ from the selection manifest")
    if manifest.get("status") not in {"complete", "complete_with_failures"}:
        raise ValueError("private run is not complete")
    if manifest.get("store_observation_initial") != manifest.get("store_observation_latest"):
        raise ValueError("private store observations changed during the run")
    if manifest.get("write_guard_passed") is not True:
        raise ValueError("private write guard did not pass")

    rows = public_observations(private_results)
    expected_by_stratum = {
        str(definition["label"]): int(definition["target_n"])
        for definition in spec["strata"]
    }
    validate_public_observations(
        rows,
        expected_n=len(ordered),
        expected_by_stratum=expected_by_stratum,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    observations_path = args.output_dir / "metadata_pilot_observations_public.jsonl"
    with observations_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    by_stratum = by_stratum_rows(rows, spec["strata"])
    timings = timing_rows(rows, spec["strata"])
    write_csv(args.output_dir / "metadata_pilot_by_stratum.csv", by_stratum)
    write_csv(args.output_dir / "metadata_pilot_timing_summary.csv", timings)

    summary = {
        "schema_version": "omicsplorer-metadata-pilot-public-summary-v1",
        "protocol_version": spec["protocol_version"],
        "interpretation": (
            "write-disabled execution feasibility under the frozen runtime; not metadata "
            "accuracy, search latency, production throughput, or an SLA"
        ),
        "privacy": (
            "identifier-free observations sorted independently of private execution order; "
            "source accessions, input hashes, predictions, and model response text excluded"
        ),
        "provenance": {
            "evaluator_git_commit": manifest["evaluator_git_commit"],
            "product_git_commit": manifest["product_git_commit"],
            "contract_manifest_sha256": manifest["contract_manifest_sha256"],
            "selection_manifest_sha256": manifest["selection_manifest_sha256"],
            "private_results_sha256": sha256_file(results_path),
            "public_observations_sha256": sha256_file(observations_path),
        },
        "execution": {
            "selection_mode": manifest["plan"]["selection_mode"],
            "target_n": manifest["plan"]["target_n"],
            "parallelism": manifest["plan"]["parallelism"],
            "process_elapsed_seconds": round(
                float(manifest["elapsed_seconds_this_process"]), 1
            ),
            "write_guard_passed": True,
            "store_observations_equal": True,
        },
        "results": aggregate_results(rows),
    }
    (args.output_dir / "metadata_pilot_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(rows)} identifier-free observations to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
