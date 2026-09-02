from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from genofinder_eval.external.complex_query_input import (
    export_collection_input,
    load_reviewed_query_specs,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "protocols" / "complex-query-evaluation-v1"
QUERY_CSV = PROTOCOL / "01-query-authoring-sheet.csv"
CRITERIA_CSV = PROTOCOL / "02-expected-criteria-sheet.csv"


def test_frozen_workbook_exports_60_unchanged_english_queries(tmp_path: Path) -> None:
    specs = load_reviewed_query_specs(QUERY_CSV, CRITERIA_CSV)
    with QUERY_CSV.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))

    assert len(specs) == 60
    assert Counter(spec.category for spec in specs) == {
        "simple": 20,
        "medium": 20,
        "complex": 20,
    }
    assert [spec.qid for spec in specs] == [row["query_id"] for row in source]
    assert [spec.text for spec in specs] == [row["query_en"] for row in source]
    assert all(spec.phase == "confirmatory" for spec in specs)

    manifest = export_collection_input(
        query_csv=QUERY_CSV,
        criteria_csv=CRITERIA_CSV,
        output_dir=tmp_path,
    )
    lines = (tmp_path / "queries_en.confirmatory.jsonl").read_text().splitlines()
    assert len(lines) == 60
    assert [json.loads(line)["text"] for line in lines] == [row["query_en"] for row in source]
    assert manifest["query_count"] == 60
    assert manifest["difficulty_counts"] == {
        "complex": 20,
        "medium": 20,
        "simple": 20,
    }


def test_export_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_a = export_collection_input(
        query_csv=QUERY_CSV,
        criteria_csv=CRITERIA_CSV,
        output_dir=first,
    )
    manifest_b = export_collection_input(
        query_csv=QUERY_CSV,
        criteria_csv=CRITERIA_CSV,
        output_dir=second,
    )

    assert (first / "queries_en.confirmatory.jsonl").read_bytes() == (
        second / "queries_en.confirmatory.jsonl"
    ).read_bytes()
    assert manifest_a["output_query_file_sha256"] == manifest_b["output_query_file_sha256"]


def test_export_rejects_unreviewed_criteria(tmp_path: Path) -> None:
    criteria = tmp_path / "criteria.csv"
    text = CRITERIA_CSV.read_text(encoding="utf-8-sig")
    criteria.write_text(
        text.replace(
            "Hojin Lee (reviewed AI-assisted draft)",
            "OpenAI Codex (AI-assisted draft)",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lack recorded human approval"):
        load_reviewed_query_specs(QUERY_CSV, criteria)
