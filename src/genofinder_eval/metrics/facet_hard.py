"""Facet satisfaction for the HARD / adversarial query set (rich multi-value format).

기존 facet_satisfaction.py 와의 차이:
    - 입력 expected 가 *list* 다중값 + `_ids` 접미 키(disease_ids/tissue_ids/cell_type_ids/
      modality/organism_taxid)를 쓰는 풍부 포맷을 소비한다(compound_2026_06_04 + 신규 하드셋).
      (기존 메트릭은 {"modality":"scRNA-seq"} 단일 문자열 포맷만 처리 → 하드셋 미채점.)
    - 두 가지 충족도를 분리 보고:
        * present     : 각 기대 값이 top-k 어딘가의 doc 태그에 등장(관대한 recall, OR).
        * conjunctive : *한 doc* 이 그 facet 의 기대 값을 전부 보유(엄격, paired/cardinality
                        용 — "urine+stool 한 연구에 둘 다" 같은 L1/L5 약점 측정).

검색 응답에 없는 facet(organism_taxid / design_intent)은 채점 대상에서 제외하고 명시
(search result 가 그 필드를 안 돌려줌 — eval 자립성 우선, 추후 API 확장 시 추가).
"""
from __future__ import annotations

import unicodedata
from typing import Any

# 기대 facet 키 → 검색결과 doc 의 태그 키 (검색 응답에 실제 존재하는 것만).
_HARD_FACET_KEYS = {
    "disease_ids": "disease_ids",
    "tissue_ids": "tissue_ids",
    "cell_type_ids": "cell_type_ids",
    "modality": "modality",
}
# 검색 응답에 없어 현재 채점 불가(투명성 위해 기록만).
_UNSCORED_FACETS = ("organism_taxid", "design_intent", "design_type", "must_not_contain")


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKC", str(s))
    return " ".join(s.lower().strip().split())


def _value_matches(expected_val: str, doc_tags: list[str]) -> bool:
    """CURIE 면 exact, 아니면 normalized 문자열 매칭."""
    ev = str(expected_val)
    if ":" in ev:  # CURIE (UBERON:/MONDO:/CL:)
        return ev in [str(t) for t in doc_tags]
    nev = _norm(ev)
    return any(_norm(t) == nev for t in doc_tags)


def facet_satisfaction_hard_at_k(
    expected: dict[str, Any],
    retrieved_docs: list[dict[str, Any]],
    k: int = 10,
) -> dict[str, Any]:
    """단일 하드 쿼리의 facet 충족도(풍부 포맷).

    Args:
        expected: {"disease_ids":[...], "tissue_ids":[...], "modality":[...], ...}.
                  list 가 비었거나 키 없으면 해당 facet 평가 제외.
        retrieved_docs: top-k 결과(정렬됨). 각 doc 은 disease_ids/tissue_ids/cell_type_ids/modality.
        k: 상위 평가 window.

    Returns:
        {
          "present_macro": float,       # facet 중 present 비율
          "conjunctive_macro": float,   # facet 중 한 doc 전부보유 비율
          "per_facet": {facet: {"present": bool, "conjunctive": bool, "n_expected": int}},
          "n_facets_evaluated": int,
          "unscored_present": [facet,...],  # 기대엔 있으나 검색응답에 없어 못 채점한 facet
        }
    """
    docs = retrieved_docs[: max(0, k)]

    active: dict[str, list[str]] = {}
    for exp_key, doc_key in _HARD_FACET_KEYS.items():
        vals = expected.get(exp_key)
        if isinstance(vals, list) and len(vals) > 0:
            active[doc_key] = [str(v) for v in vals]
        elif isinstance(vals, str) and vals.strip():
            active[doc_key] = [vals.strip()]

    unscored = [f for f in _UNSCORED_FACETS if expected.get(f) not in (None, [], "")]

    if not active:
        return {
            "present_macro": 0.0, "conjunctive_macro": 0.0, "per_facet": {},
            "n_facets_evaluated": 0, "unscored_present": unscored,
        }

    per_facet: dict[str, dict[str, Any]] = {}
    for doc_key, exp_vals in active.items():
        # present: 각 기대값이 top-k 어딘가의 doc 태그에 등장하는가 (모든 기대값에 대해)
        present = all(
            any(_value_matches(ev, doc.get(doc_key) or []) for doc in docs)
            for ev in exp_vals
        )
        # conjunctive: 한 doc 이 기대값 전부 보유하는가
        conjunctive = any(
            all(_value_matches(ev, doc.get(doc_key) or []) for ev in exp_vals)
            for doc in docs
        )
        per_facet[doc_key] = {
            "present": present, "conjunctive": conjunctive, "n_expected": len(exp_vals),
        }

    n = len(per_facet)
    present_macro = sum(1 for v in per_facet.values() if v["present"]) / n
    conjunctive_macro = sum(1 for v in per_facet.values() if v["conjunctive"]) / n
    return {
        "present_macro": present_macro,
        "conjunctive_macro": conjunctive_macro,
        "per_facet": per_facet,
        "n_facets_evaluated": n,
        "unscored_present": unscored,
    }
