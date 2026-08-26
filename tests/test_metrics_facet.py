"""Facet matching + facet_satisfaction_at_k 단위 테스트."""
from __future__ import annotations

from genofinder_eval.metrics.facet_satisfaction import (
    facet_matches,
    facet_satisfaction_at_k,
    normalize_text,
)


def test_normalize_text_nfkc() -> None:
    assert normalize_text("ＨＥＬＬＯ") == "hello"


def test_facet_matches_curie() -> None:
    assert facet_matches("MONDO:0008903", ["MONDO:0008903", "MONDO:0001"])
    assert not facet_matches("MONDO:0008903", ["MONDO:0001"])


def test_facet_matches_string() -> None:
    assert facet_matches("bladder cancer", ["Bladder Cancer", "lung"])
    assert facet_matches("scRNA-seq", ["scrna-seq"])
    assert not facet_matches("scRNA-seq", ["bulk RNA-seq"])


def test_facet_matches_none_expected() -> None:
    assert facet_matches(None, [])
    assert facet_matches(None, ["whatever"])


def test_facet_satisfaction_all_hit() -> None:
    """top-3 결과가 모두 expected facet 충족 → macro=1.0."""
    expected = {"disease": "MONDO:0008903", "tissue": "UBERON:0001264", "modality": "scRNA-seq"}
    docs = [
        {"disease_ids": ["MONDO:0008903"], "tissue_ids": ["UBERON:0001264"], "modality": ["scRNA-seq"]},
        {"disease_ids": ["MONDO:0001"], "tissue_ids": ["UBERON:0001264"], "modality": ["bulk RNA-seq"]},
        {"disease_ids": [], "tissue_ids": [], "modality": ["scRNA-seq"]},
    ]
    out = facet_satisfaction_at_k(expected, docs, k=3)
    assert out["macro"] == 1.0
    assert out["per_facet"]["disease"] is True
    assert out["per_facet"]["tissue"] is True
    assert out["per_facet"]["modality"] is True


def test_facet_satisfaction_partial_hit() -> None:
    """disease 는 hit, tissue 는 miss → macro = 1/2 = 0.5."""
    expected = {"disease": "MONDO:0008903", "tissue": "UBERON:0001264"}
    docs = [
        {"disease_ids": ["MONDO:0008903"], "tissue_ids": ["UBERON:9999"]},
    ]
    out = facet_satisfaction_at_k(expected, docs, k=10)
    assert out["macro"] == 0.5


def test_facet_satisfaction_none_facets() -> None:
    """expected 가 모두 None 이면 평가 facet 0 → macro=0.0."""
    expected = {"disease": None, "tissue": None}
    docs = [{"disease_ids": ["MONDO:1"]}]
    out = facet_satisfaction_at_k(expected, docs)
    assert out["n_facets_evaluated"] == 0
    assert out["macro"] == 0.0


def test_facet_satisfaction_design_type_nested() -> None:
    """cohort_design.design_type 도 추출 가능."""
    expected = {"design_type": "case_control"}
    docs = [{"cohort_design": {"design_type": "case_control", "groups": []}}]
    out = facet_satisfaction_at_k(expected, docs)
    assert out["macro"] == 1.0
