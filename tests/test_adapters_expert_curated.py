"""Expert-curated 30q domain diversity 검증."""
from __future__ import annotations

import pytest

from genofinder_eval.adapters.expert_curated_30 import (
    ExpertQuery,
    verify_domain_diversity,
)


def _q(qid: str, en: str, ko: str = "") -> ExpertQuery:
    return ExpertQuery(
        qid=qid,
        category="short",
        text_en=en,
        text_ko=ko or en,
        expected_facets={},
    )


def test_diversity_within_limit() -> None:
    # 3건 BCG / bladder cancer 직접 언급 — 허용
    queries = {
        "Q01": _q("Q01", "BCG bladder cancer scRNA-seq"),
        "Q02": _q("Q02", "bladder cancer immune"),
        "Q03": _q("Q03", "BCG response stratification"),
        "Q04": _q("Q04", "lung cancer scRNA-seq"),
        "Q05": _q("Q05", "diabetes pancreas single-cell"),
    }
    verify_domain_diversity(queries, max_bcg_or_bladder=3)


def test_diversity_violation() -> None:
    queries = {f"Q0{i}": _q(f"Q0{i}", "BCG bladder cancer", "BCG 방광암") for i in range(4)}
    with pytest.raises(ValueError, match="BCG / bladder cancer"):
        verify_domain_diversity(queries, max_bcg_or_bladder=3)
