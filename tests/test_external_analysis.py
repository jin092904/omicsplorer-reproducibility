from __future__ import annotations

import json
from pathlib import Path

import pytest

from genofinder_eval.external.combine_browser import combine
from genofinder_eval.external.descriptive_metrics import summarize_run
from genofinder_eval.external.known_item import score
from genofinder_eval.external.models import QuerySpec, SearchHit, SearchResponse
from genofinder_eval.external.sol4_metrics import summarize


def _response(system: str, qid: str, hits: list[SearchHit], latency: float) -> SearchResponse:
    return SearchResponse(
        system=system,
        qid=qid,
        query_text="test query",
        corpus="geo",
        requested_top_k=10,
        total=len(hits),
        hits=hits,
        wall_latency_ms=latency,
        fetched_at_utc="2026-07-20T00:00:00Z",
        endpoint="https://example.test/search",
        request_parameters={},
        raw_sha256="0" * 64,
        raw_response={},
        http_status=200,
        adapter_version="test",
    )


def _write_response(run: Path, response: SearchResponse) -> None:
    path = run / "raw" / response.system / f"{response.qid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.model_dump_json(), encoding="utf-8")


def test_descriptive_summary_counts_zero_overlap_and_exclusive(tmp_path: Path) -> None:
    common = SearchHit(rank=1, canonical_id="GSE1", native_id="GSE1", title="common")
    unique = SearchHit(rank=2, canonical_id="GSE2", native_id="GSE2", title="unique")
    _write_response(tmp_path, _response("a", "q1", [common, unique], 100.0))
    _write_response(tmp_path, _response("b", "q1", [common], 200.0))

    result = summarize_run(tmp_path)

    systems = {row["system"]: row for row in result["systems"]}
    assert systems["a"]["zero_result_rate"] == 0
    assert systems["a"]["mean_returned"] == 2
    overlap = result["overlap"][0]
    assert overlap["mean_jaccard_at_10"] == pytest.approx(0.5)
    exclusive = {row["system"]: row for row in result["exclusive"]}
    assert exclusive["a"]["exclusive_share"] == pytest.approx(0.5)
    assert exclusive["b"]["exclusive_share"] == 0


def test_combine_browser_concatenates_only_observed_rows(tmp_path: Path) -> None:
    row_a = {
        "metric": "search_settled_ms",
        "outcome": "success",
        "elapsed_ms": 100.0,
        "category": "short",
    }
    row_b = {**row_a, "elapsed_ms": 300.0}
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    first.write_text(json.dumps(row_a) + "\n", encoding="utf-8")
    second.write_text(json.dumps(row_b) + "\n", encoding="utf-8")

    rows = combine([first, second], tmp_path / "combined")

    assert [row["elapsed_ms"] for row in rows] == [100.0, 300.0]
    summary = (tmp_path / "combined" / "browser_latency_summary.csv").read_text()
    assert "200.0" in summary


def test_sol4_summary_preserves_shadow_safety_and_tail() -> None:
    rows = [
        {
            "event": "dataset",
            "mode": "shadow",
            "model": "gemma4:31b",
            "extraction_version": "v1",
            "outcome": "updated",
            "changed": True,
            "new_curies": 2,
            "elapsed_ms": 10.0,
            "llm_ms": 7.0,
            "normalization_merge_ms": 2.0,
            "sample_fetch_ms": 1.0,
        },
        {
            "event": "dataset",
            "mode": "shadow",
            "model": "gemma4:31b",
            "extraction_version": "v1",
            "outcome": "updated",
            "changed": True,
            "new_curies": 3,
            "elapsed_ms": 20.0,
            "llm_ms": 14.0,
            "normalization_merge_ms": 4.0,
            "sample_fetch_ms": 2.0,
        },
        {
            "event": "run_summary",
            "candidate_pool": 100,
            "elapsed_seconds": 30.0,
            "throughput_per_hour": 240.0,
        },
    ]

    stages, summary = summarize(rows)

    assert summary["database_writes"] is False
    assert summary["n_changed"] == 2
    assert summary["new_curies_total"] == 5
    dataset = next(row for row in stages if row["stage"] == "dataset_total_ms")
    assert dataset["p50_ms"] == 15.0
    assert dataset["max_ms"] == 20.0


def test_known_item_score_keeps_failures_in_denominator(tmp_path: Path) -> None:
    query = QuerySpec(
        qid="known_GSE1",
        text="a sufficiently long known item title query",
        category="known_item_title",
        phase="known_item",
        target_accession="GSE1",
        provenance="test",
    )
    query_file = tmp_path / "queries.jsonl"
    query_file.write_text(query.model_dump_json() + "\n", encoding="utf-8")
    (tmp_path / "run_manifest.json").write_text(
        json.dumps({"systems": ["good", "failed"]}), encoding="utf-8"
    )
    hit = SearchHit(rank=2, canonical_id="GSE1", native_id="GSE1", title="target")
    _write_response(tmp_path, _response("good", query.qid, [hit], 100.0))
    failure = tmp_path / "raw" / "failed" / f"{query.qid}.failure.json"
    failure.parent.mkdir(parents=True, exist_ok=True)
    failure.write_text("{}", encoding="utf-8")

    rows, summaries = score(tmp_path, query_file)

    assert len(rows) == 2
    by_system = {row["system"]: row for row in summaries}
    assert by_system["good"]["mrr_at_50"] == 0.5
    assert by_system["failed"]["request_failure_rate"] == 1.0
    assert by_system["failed"]["hit_at_50"] == 0
