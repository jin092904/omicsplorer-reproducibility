"""Facet-aware satisfaction scoring (자체 정의, motivated by DeepGEOSearch 2025).

원전:
    DeepGEOSearch: LLM-Powered Schemaless Retrieval for Biomedical Data Discovery.
    bioRxiv 2025, doi:10.64898/2025.12.27.696662.
    본 메트릭은 그 paper 가 제기한 *ranking-only metric 이 facet-attribute 매칭을
    과소평가한다* 는 관찰에 동기를 두고 자체 정의한 것이며, 원전 framework 의 1:1
    재현이 아님.

정의:
    각 query q 에 대해 expected_facets = {disease, tissue, cell_type, modality, design_type}
    의 일부 또는 전부가 주어진다. 상위 top-k retrieved dataset 의 cohort_design /
    extraction 결과와 facet 별 일치 여부를 측정.

    facet_satisfaction@k(q) = |{f ∈ expected_facets : ∃ d ∈ top-k, d.facet[f] matches q.expected[f]}|
                              / |expected_facets|

    macro avg 와 facet 별 break-down 둘 다 보고.

매칭 우선순위:
    1. CURIE exact match (예: MONDO:0008903 == MONDO:0008903)
    2. Normalized string match (NFKC + lowercase + whitespace trim)
    3. mismatch
"""
from __future__ import annotations

import unicodedata
from typing import Any

# query 의 expected_facets 키 → retrieved doc 의 매칭 후보 키들.
_FACET_TO_DOC_KEYS = {
    "disease": ("disease_ids",),
    "tissue": ("tissue_ids",),
    "cell_type": ("cell_type_ids",),
    "modality": ("modality",),
    "organism": ("organism_taxid",),
    "design_type": ("design_type",),  # cohort_design.design_type 또는 평탄화된 키
}


def normalize_text(s: str) -> str:
    """NFKC + lowercase + strip + collapse internal whitespace."""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower().strip()
    return " ".join(s.split())


def facet_matches(expected: str | None, candidates: list[str]) -> bool:
    """expected 가 None 이면 True (해당 facet 무관). 아니면 CURIE / normalized text 매칭."""
    if expected is None:
        return True
    if not candidates:
        return False
    str_candidates = [str(c) for c in candidates]
    if ":" in expected:  # CURIE
        return expected in str_candidates
    norm_exp = normalize_text(expected)
    return any(normalize_text(c) == norm_exp for c in str_candidates)


def _extract_doc_facet(doc: dict[str, Any], doc_keys: tuple[str, ...]) -> list[str]:
    """retrieved doc 에서 facet 후보 값 추출. list 또는 single string 모두 처리.

    design_type 의 경우 doc 의 cohort_design JSON 에 들어있을 수도, 평탄화된
    키에 있을 수도 있다 (평가 시점의 schema 에 따라).
    """
    for key in doc_keys:
        if key in doc and doc[key] is not None:
            val = doc[key]
            if isinstance(val, list):
                return [str(v) for v in val]
            if isinstance(val, dict):
                # cohort_design 같은 nested object 의 design_type 등 추출
                inner = val.get("design_type")
                if inner is not None:
                    return [str(inner)]
                continue
            return [str(val)]
    # cohort_design JSON 안의 design_type fallback
    if "cohort_design" in doc and isinstance(doc["cohort_design"], dict):
        v = doc["cohort_design"].get(doc_keys[0])
        if v is not None:
            return [str(v)]
    return []


def facet_satisfaction_at_k(
    expected_facets: dict[str, str | None],
    retrieved_docs: list[dict[str, Any]],
    k: int = 10,
) -> dict[str, Any]:
    """단일 query 의 facet-aware satisfaction.

    Args:
        expected_facets: {"disease": "bladder cancer", "tissue": ..., ...}.
                         값이 None 또는 빈 문자열인 항목은 평가 대상에서 제외.
        retrieved_docs:  top-k 결과 (이미 정렬된 순서). 각 doc 은 disease_ids,
                         tissue_ids, cell_type_ids, modality, cohort_design 등.
        k:               상위 몇 개 doc 까지 평가할지 (top-k window).

    Returns:
        {
          "macro": float (0..1) — 평가 facet 중 hit 비율,
          "per_facet": {facet_name: bool},
          "n_facets_evaluated": int,
        }
    """
    docs = retrieved_docs[: max(0, k)]
    # None / 빈 값 제외
    active = {
        f: v for f, v in expected_facets.items()
        if v is not None and str(v).strip() != "" and f in _FACET_TO_DOC_KEYS
    }
    per_facet: dict[str, bool] = {}
    for facet, exp_value in active.items():
        doc_keys = _FACET_TO_DOC_KEYS[facet]
        hit = False
        for doc in docs:
            candidates = _extract_doc_facet(doc, doc_keys)
            if facet_matches(exp_value, candidates):
                hit = True
                break
        per_facet[facet] = hit

    if not per_facet:
        return {"macro": 0.0, "per_facet": {}, "n_facets_evaluated": 0}

    macro = sum(1 for v in per_facet.values() if v) / len(per_facet)
    return {
        "macro": macro,
        "per_facet": per_facet,
        "n_facets_evaluated": len(per_facet),
    }
