"""bioCADDIE adapter assertion 검증.

Step 3-1 실 fetch 후 verify_counts 가 정확히 동작하는지 확인.
"""
from __future__ import annotations

import pytest

from genofinder_eval.adapters.biocaddie import verify_counts


def test_verify_counts_happy() -> None:
    verify_counts(corpus_n=794992, queries_n=15, qrels_n=20001)


def test_verify_counts_corpus_mismatch() -> None:
    with pytest.raises(ValueError, match="corpus count mismatch"):
        verify_counts(corpus_n=500000, queries_n=15, qrels_n=20001)


def test_verify_counts_queries_mismatch() -> None:
    with pytest.raises(ValueError, match="queries count mismatch"):
        verify_counts(corpus_n=794992, queries_n=10, qrels_n=20001)


def test_verify_counts_qrels_too_few() -> None:
    with pytest.raises(ValueError, match="qrels count suspicious"):
        verify_counts(corpus_n=794992, queries_n=15, qrels_n=1000)
