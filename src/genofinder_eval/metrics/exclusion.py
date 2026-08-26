"""Exclusion / negation satisfaction scoring (must_not_contain).

동기:
    facet_satisfaction 은 "기대 facet 이 top-k 에 *있는가*"(positive recall)만 본다.
    하지만 부정/제외 쿼리("비흡연 폐조직", "치료 경험 없는 환자", "소아 제외")의 품질은
    정반대 — 금지된 속성을 가진 결과가 top-k 에 *없어야* 좋다. 본 메트릭은 그 negative
    constraint 충족도를 측정한다.

근거 신호:
    각 dataset 의 CURIE 태그(disease/tissue/cell_type)에는 "smoker", "chemotherapy" 같은
    free-text 금지어가 안 들어있다 → 그 신호는 dataset 의 title + abstract_snippet 에 있다.
    따라서 must_not_contain 위반은 result 의 title + abstract_snippet 텍스트에서 substring
    매칭으로 판정한다.

한계 (정직하게 명시):
    - abstract_snippet 은 *스니펫*(절단됨)이라 본문 깊은 곳의 금지어는 놓칠 수 있음(=과소탐지,
      낙관적 편향). 더 엄밀히는 result 별 full-abstract DB 조회가 필요하나 본 메트릭은 search
      응답만으로 자립 채점한다.
    - 의미적 부정("non-smoker" vs "smoker")은 substring 으로 못 가른다 → 금지어 리스트는
      쿼리 작성 시 "smoker","smoking","cigarette","tobacco" 처럼 충분히 구체적으로 줄 것.
"""
from __future__ import annotations

import unicodedata
from typing import Any


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return " ".join(s.lower().strip().split())


def _doc_text(doc: dict[str, Any]) -> str:
    """채점 대상 텍스트 = title + abstract_snippet (있는 것만)."""
    parts = [doc.get("title") or "", doc.get("abstract_snippet") or ""]
    return _norm(" ".join(p for p in parts if p))


def _violations(doc_text: str, forbidden: list[str]) -> list[str]:
    """이 doc 텍스트가 포함한 금지어 목록."""
    return [term for term in forbidden if _norm(term) and _norm(term) in doc_text]


def exclusion_satisfaction_at_k(
    must_not_contain: list[str],
    retrieved_docs: list[dict[str, Any]],
    k: int = 10,
) -> dict[str, Any]:
    """단일 쿼리의 제외-제약 충족도.

    Args:
        must_not_contain: 금지어 substring 목록. 비면 평가 대상 아님(None 반환 형태).
        retrieved_docs:   top-k 결과(정렬됨). 각 doc 은 title / abstract_snippet 보유.
        k:                상위 몇 개까지 평가할지.

    Returns:
        {
          "applicable": bool,                 # must_not_contain 이 있었는가
          "clean_at_k": float (0..1),         # 금지어 0개인 결과 비율 (높을수록 좋음)
          "violation_count": int,             # 금지어 포함 결과 수
          "first_violation_rank": int | None, # 최초 위반 결과의 rank(1-based), 없으면 None
          "n_docs_evaluated": int,
        }
    """
    forbidden = [t for t in (must_not_contain or []) if str(t).strip()]
    docs = retrieved_docs[: max(0, k)]
    if not forbidden:
        return {
            "applicable": False, "clean_at_k": 1.0, "violation_count": 0,
            "first_violation_rank": None, "n_docs_evaluated": len(docs),
        }
    if not docs:
        return {
            "applicable": True, "clean_at_k": 1.0, "violation_count": 0,
            "first_violation_rank": None, "n_docs_evaluated": 0,
        }

    violation_count = 0
    first_violation_rank: int | None = None
    for rank, doc in enumerate(docs, start=1):
        if _violations(_doc_text(doc), forbidden):
            violation_count += 1
            if first_violation_rank is None:
                first_violation_rank = rank

    clean = (len(docs) - violation_count) / len(docs)
    return {
        "applicable": True,
        "clean_at_k": clean,
        "violation_count": violation_count,
        "first_violation_rank": first_violation_rank,
        "n_docs_evaluated": len(docs),
    }
