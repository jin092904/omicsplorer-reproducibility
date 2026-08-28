from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from genofinder_eval.metadata_pilot import (
    PILOT_SELECTION_SQL,
    MetadataPilotError,
    load_selection_spec,
    manifest_record,
    public_summary,
    sha256_json,
    validate_records,
    write_private_jsonl,
)


def _spec() -> dict:
    return {
        "schema_version": "omicsplorer-metadata-pilot-selection-v1",
        "protocol_version": "test-v1",
        "seed": "fixed-seed",
        "strata": [
            {
                "label": "geo",
                "source_db": "GEO",
                "historical_extraction_version": "old-v1",
                "target_n": 1,
            }
        ],
    }


def _record() -> dict:
    return manifest_record(
        {
            "label": "geo",
            "source_db": "GEO",
            "source_id": "GSE1",
            "historical_extraction_version": "old-v1",
            "selection_rank": 1,
            "title": "title",
            "abstract": "abstract",
            "raw_metadata": '{"b": 2, "a": 1}',
            "n_samples": 2,
            "sample_rows": 2,
            "sample_titles": ["sample 1", "sample 2"],
        },
        seed="fixed-seed",
    )


def test_selection_sql_contains_no_database_mutation() -> None:
    normalized = " ".join(PILOT_SELECTION_SQL.upper().split())
    for keyword in (" INSERT ", " UPDATE ", " DELETE ", " MERGE ", " TRUNCATE ", " ALTER "):
        assert keyword not in f" {normalized} "


def test_load_spec_rejects_duplicate_source_version(tmp_path: Path) -> None:
    spec = _spec()
    spec["strata"].append({**spec["strata"][0], "label": "duplicate"})
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(MetadataPilotError, match="unique"):
        load_selection_spec(path)


def test_manifest_hash_is_canonical_and_contains_no_payload() -> None:
    record = _record()
    assert record["source_input_sha256"] == sha256_json(
        {
            "title": "title",
            "abstract": "abstract",
            "raw_metadata": {"a": 1, "b": 2},
            "n_samples": 2,
            "sample_titles": ["sample 1", "sample 2"],
        }
    )
    assert "title" not in record
    assert "abstract" not in record
    assert "raw_metadata" not in record


def test_validate_and_summarize() -> None:
    record = _record()
    validate_records([record], _spec())
    summary = public_summary(
        [record], spec=_spec(), spec_sha256="a" * 64, generated_at_utc="2026-01-01T00:00:00Z"
    )
    assert summary["selected_total"] == 1
    assert summary["strata"][0]["records_with_usable_sample_titles_n"] == 1


def test_private_manifest_is_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "pilot.private.jsonl"
    write_private_jsonl(path, [_record()])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
