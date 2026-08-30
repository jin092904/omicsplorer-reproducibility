from __future__ import annotations

import json
from pathlib import Path

from genofinder_eval.figures.figure_corpus import DEFAULT_SUMMARY, load_summary, render


def test_public_corpus_identity_summary_reconciles() -> None:
    summary = load_summary()
    counts = summary["counts"]

    assert counts["isolated_rows"] - counts["excluded_rows"] == counts["retained_rows"]
    assert sum(item["rows"] for item in summary["sources"]) == counts["retained_rows"]
    assert all(
        item["dataset_id_count"] == counts["retained_rows"] for item in summary["stores"]
    )
    assert summary["mismatch_counts"] == {
        "dataset_id": 0,
        "source_accession_membership": 0,
    }


def test_public_corpus_identity_summary_contains_aggregates_only() -> None:
    raw: object = json.loads(DEFAULT_SUMMARY.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert "dataset_ids" not in raw
    assert "source_accessions" not in raw
    assert "rows" not in raw
    assert "model_outputs" not in raw
    assert raw["target_restore_status"] == "not performed"


def test_corpus_identity_figure_renders_from_public_summary(tmp_path: Path) -> None:
    render(tmp_path)

    assert (tmp_path / "fig_corpus_overview.png").stat().st_size > 0
    assert (tmp_path / "fig_corpus_overview.pdf").stat().st_size > 0
