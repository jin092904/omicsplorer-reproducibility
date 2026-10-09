from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from genofinder_eval.figures import figure_architecture, figure_complex_query_relevance


def _assert_submission_tiff(path: Path) -> None:
    with Image.open(path) as image:
        assert image.mode == "RGB"
        assert image.info["dpi"] == pytest.approx((600, 600))
        assert image.info["compression"] == "tiff_lzw"


def test_relevance_panels_use_the_reported_values() -> None:
    values = figure_complex_query_relevance.load_panel_values()

    assert values.n_queries == 60
    assert values.nonempty_queries == (60, 57, 52)
    assert [round(item.mean, 3) for item in values.ndcg_at_10] == [0.657, 0.483, 0.526]
    for item in values.ndcg_at_10:
        assert item.low <= item.mean <= item.high
    # Panel A: grade-3, grade-2, and grade-0/1 candidates per query (320, 257, and 276 relevant).
    relevant_per_query = [grade3 + grade2 for grade3, grade2, _ in values.slot_composition]
    assert [round(value * 60) for value in relevant_per_query] == [320, 257, 276]
    assert [round(sum(item) * 60) for item in values.slot_composition] == [600, 480, 406]
    # Panel C: relevant candidates that neither other system returned.
    assert values.relevant_found == (320, 257, 276)
    assert values.relevant_found_only_here == (251, 167, 148)


def test_relevance_panels_reject_a_missing_system(tmp_path: Path) -> None:
    derived = figure_complex_query_relevance.DEFAULT_DERIVED
    for name in ("metrics_summary.csv", "metrics_per_query.csv", "relevant_overlap.csv"):
        lines = (derived / name).read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith("omicsdi_geo_keyword,")]
        (tmp_path / name).write_text("".join(kept), encoding="utf-8")

    with pytest.raises(ValueError, match="omicsdi_geo_keyword"):
        figure_complex_query_relevance.load_panel_values(tmp_path)


def test_relevance_figure_renders_submission_formats(tmp_path: Path) -> None:
    figure_complex_query_relevance.render(tmp_path)

    for suffix in ("png", "pdf"):
        assert (tmp_path / f"fig_complex_query_relevance.{suffix}").stat().st_size > 0
    _assert_submission_tiff(tmp_path / "fig_complex_query_relevance.tiff")


def test_architecture_figure_renders_submission_formats(tmp_path: Path) -> None:
    figure_architecture.render(tmp_path)

    for suffix in ("png", "pdf"):
        assert (tmp_path / f"fig_architecture.{suffix}").stat().st_size > 0
    _assert_submission_tiff(tmp_path / "fig_architecture.tiff")
