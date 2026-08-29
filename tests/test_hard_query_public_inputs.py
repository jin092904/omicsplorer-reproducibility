from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "hard_queries"
EXPECTED_QUERY_COUNT = 49
UNRESOLVED_MARKERS = ("<TODO>", "REVIEW_REQUIRED", "TBD", "PLACEHOLDER")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            assert isinstance(row, dict), f"{path}:{line_number} is not a JSON object"
            rows.append(row)
    return rows


def _index_unique(rows: list[dict[str, Any]], key: str, path: Path) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        identifier = str(row.get(key) or "").strip()
        assert identifier, f"{path}:{line_number} has no {key}"
        assert identifier not in indexed, f"duplicate {key} in {path}:{line_number}: {identifier}"
        indexed[identifier] = row
    return indexed


def test_hard_query_files_have_the_same_49_ordered_identifiers() -> None:
    en_path = DATA_DIR / "queries_en.jsonl"
    ko_path = DATA_DIR / "queries_ko.jsonl"
    facets_path = DATA_DIR / "facet_judgments.jsonl"
    manifest_path = DATA_DIR / "manifest.csv"

    en_rows = _load_jsonl(en_path)
    ko_rows = _load_jsonl(ko_path)
    facet_rows = _load_jsonl(facets_path)
    with manifest_path.open(encoding="utf-8", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))

    ordered_identifiers = [
        [str(row.get("_id") or "").strip() for row in en_rows],
        [str(row.get("_id") or "").strip() for row in ko_rows],
        [str(row.get("qid") or "").strip() for row in facet_rows],
        [str(row.get("qid") or "").strip() for row in manifest_rows],
    ]
    assert len(ordered_identifiers[0]) == EXPECTED_QUERY_COUNT
    assert all(identifiers == ordered_identifiers[0] for identifiers in ordered_identifiers[1:])
    assert len(set(ordered_identifiers[0])) == EXPECTED_QUERY_COUNT


def test_paired_queries_match_author_defined_facet_file() -> None:
    en_path = DATA_DIR / "queries_en.jsonl"
    ko_path = DATA_DIR / "queries_ko.jsonl"
    facets_path = DATA_DIR / "facet_judgments.jsonl"
    manifest_path = DATA_DIR / "manifest.csv"

    en = _index_unique(_load_jsonl(en_path), "_id", en_path)
    ko = _index_unique(_load_jsonl(ko_path), "_id", ko_path)
    facets = _index_unique(_load_jsonl(facets_path), "qid", facets_path)
    with manifest_path.open(encoding="utf-8", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))
    manifest = _index_unique(manifest_rows, "qid", manifest_path)

    assert en.keys() == ko.keys() == facets.keys() == manifest.keys()
    for qid in en:
        expected = facets[qid].get("expected")
        assert isinstance(expected, dict) and expected, f"empty facet expectation: {qid}"
        assert en[qid].get("expected_facets") == expected, f"EN facet mismatch: {qid}"
        assert ko[qid].get("expected_facets") == expected, f"KO facet mismatch: {qid}"
        assert str(en[qid].get("text") or "").strip(), f"blank EN query: {qid}"
        assert str(ko[qid].get("text") or "").strip(), f"blank KO query: {qid}"
        assert en[qid].get("category") == ko[qid].get("category"), f"category mismatch: {qid}"
        assert en[qid].get("category") == manifest[qid].get("axis"), f"axis mismatch: {qid}"


def test_hard_query_inputs_contain_no_unresolved_release_markers() -> None:
    for path in sorted(DATA_DIR.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in UNRESOLVED_MARKERS:
            assert marker.casefold() not in text.casefold(), f"unresolved marker {marker!r} in {path}"
