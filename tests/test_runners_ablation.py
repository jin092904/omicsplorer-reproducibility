"""Paired bootstrap significance test 검증."""
from __future__ import annotations

from genofinder_eval.runners.ablation import paired_bootstrap, pairwise_compare


def test_paired_bootstrap_zero_diff() -> None:
    """동일 metric 두 list → mean_diff = 0, p-value ≈ 1.0."""
    a = [0.5, 0.6, 0.7, 0.8]
    b = list(a)
    mean_diff, (lo, hi), p = paired_bootstrap(a, b, iterations=500, seed=42)
    assert mean_diff == 0.0
    assert lo == 0.0 and hi == 0.0
    assert p == 1.0  # 정확히 같으면 부호 반전 없음 → p=1


def test_paired_bootstrap_large_diff() -> None:
    """확연한 차이 → p-value 작음, CI 가 0 포함 안 함."""
    a = [0.9, 0.85, 0.92, 0.88, 0.91, 0.87, 0.93, 0.89]
    b = [0.5, 0.45, 0.48, 0.52, 0.51, 0.49, 0.47, 0.50]
    mean_diff, (lo, _hi), p = paired_bootstrap(a, b, iterations=1000, seed=42)
    assert mean_diff > 0.3
    assert lo > 0  # 95% CI 가 양수 → significant
    assert p < 0.05


def test_paired_bootstrap_length_mismatch() -> None:
    import pytest
    with pytest.raises(ValueError, match="length mismatch"):
        paired_bootstrap([1.0, 2.0], [1.0])


def test_pairwise_compare_returns_4c2() -> None:
    """4 mode 의 6 pairwise comparison."""
    qids = [f"Q{i}" for i in range(5)]
    metrics = {
        "bm25_only":   {q: 0.4 for q in qids},
        "dense_only":  {q: 0.6 for q in qids},
        "rrf":         {q: 0.7 for q in qids},
        "rrf_rerank":  {q: 0.85 for q in qids},
    }
    rows = pairwise_compare(metrics, iterations=200, seed=42)
    assert len(rows) == 6  # 4C2
    # 모든 결과가 mean_diff < 0 (alphabetical: bm25_only < dense_only < rrf < rrf_rerank)
    for row in rows:
        assert row["mean_diff"] < 0  # mode_a 가 alphabetically 작아 metric 도 낮음
