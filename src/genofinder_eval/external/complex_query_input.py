"""Build the external-run input from the frozen reviewed query workbook."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from genofinder_eval.external.models import QuerySpec

PRESPEC_TAG = "omicsplorer-complex-query-prespec-v1"
EXPECTED_COUNTS = {"simple": 20, "medium": 20, "complex": 20}
EXPECTED_QUERY_AUTHOR = "Hojin Lee"
EXPECTED_CRITERIA_AUTHOR = "Hojin Lee (reviewed AI-assisted draft)"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_reviewed_query_specs(query_csv: Path, criteria_csv: Path) -> list[QuerySpec]:
    """Validate the frozen workbook metadata and return service-neutral English queries."""
    query_rows = _read_csv(query_csv)
    criteria_rows = _read_csv(criteria_csv)
    if len(query_rows) != 60:
        raise ValueError(f"Expected 60 query rows; observed {len(query_rows)}")
    if len(criteria_rows) != 60:
        raise ValueError(f"Expected 60 criteria rows; observed {len(criteria_rows)}")

    query_ids = [row.get("query_id", "") for row in query_rows]
    criteria_ids = [row.get("query_id", "") for row in criteria_rows]
    if len(set(query_ids)) != 60:
        raise ValueError("Query IDs must be non-empty and unique")
    if set(query_ids) != set(criteria_ids):
        raise ValueError("Query and criteria sheets have different query IDs")

    counts = Counter(row.get("difficulty", "") for row in query_rows)
    if counts != Counter(EXPECTED_COUNTS):
        raise ValueError(
            f"Difficulty counts must be {EXPECTED_COUNTS}; observed {dict(counts)}"
        )

    criteria_by_id = {row["query_id"]: row for row in criteria_rows}
    specs: list[QuerySpec] = []
    for row in query_rows:
        qid = row["query_id"]
        if row.get("query_author") != EXPECTED_QUERY_AUTHOR:
            raise ValueError(f"{qid}: unexpected query author")
        if row.get("original_language", "").lower() != "ko":
            raise ValueError(f"{qid}: original language must be ko")
        if row.get("results_not_seen_yes", "").lower() != "yes":
            raise ValueError(f"{qid}: query was not confirmed as written before results")
        text = row.get("query_en", "")
        if not text:
            raise ValueError(f"{qid}: missing English query")

        criteria = criteria_by_id[qid]
        if criteria.get("criteria_author") != EXPECTED_CRITERIA_AUTHOR:
            raise ValueError(f"{qid}: expected criteria lack recorded human approval")
        if criteria.get("results_not_seen_yes", "").lower() != "yes":
            raise ValueError(f"{qid}: criteria were not confirmed as written before results")
        if "review required" in criteria.get("notes", "").lower():
            raise ValueError(f"{qid}: expected criteria still require review")

        specs.append(
            QuerySpec(
                qid=qid,
                text=text,
                category=row["difficulty"],
                corpus="geo",
                phase="confirmatory",
                provenance=(
                    f"{PRESPEC_TAG}:{query_csv.name}:{qid};"
                    "query_author=Hojin Lee;original_language=ko"
                ),
            )
        )
    return specs


def export_collection_input(
    *,
    query_csv: Path,
    criteria_csv: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Write deterministic JSONL and a checksum-bound projection manifest."""
    specs = load_reviewed_query_specs(query_csv, criteria_csv)
    output_dir.mkdir(parents=True, exist_ok=True)
    query_output = output_dir / "queries_en.confirmatory.jsonl"
    query_output.write_text(
        "".join(spec.model_dump_json() + "\n" for spec in specs),
        encoding="utf-8",
    )
    counts = Counter(spec.category for spec in specs)
    manifest: dict[str, Any] = {
        "projection_type": "deterministic_collection_input",
        "prespec_tag": PRESPEC_TAG,
        "source_query_csv": str(query_csv.resolve()),
        "source_query_csv_sha256": _sha256(query_csv),
        "source_criteria_csv": str(criteria_csv.resolve()),
        "source_criteria_csv_sha256": _sha256(criteria_csv),
        "output_query_file": query_output.name,
        "output_query_file_sha256": _sha256(query_output),
        "query_count": len(specs),
        "difficulty_counts": dict(sorted(counts.items())),
        "language_sent_to_common_services": "en",
        "corpus": "geo",
        "phase": "confirmatory",
    }
    manifest_path = output_dir / "queries_en.confirmatory.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
