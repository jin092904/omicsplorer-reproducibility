"""Expert-curated 30-query ground truth loader.

30 query 는 편집자 (호진) 가 직접 작성. **LLM 자동 생성 금지** — `scripts/02-build-30q-template.sh`
가 빈 schema 만 제공하고, 실제 query 내용은 사람이 채운다.

Schema (각 jsonl row):
    queries_{en,ko}.jsonl:
        {"_id": "Q01", "category": "short" | "medium" | "complex",
         "text": str, "expected_facets": {...} }

    qrels.tsv (TREC 표준):
        qid \\t Q0 \\t docid \\t relevance (0/1/2/3)
        relevance 등급:
            3 = highly relevant   — query 의 모든 facet 일치
            2 = relevant          — 대부분 facet 일치
            1 = marginally        — 일부 facet 일치
            0 = not relevant

    facet_judgments.jsonl:
        {"qid": "Q01",
         "expected": {"disease": "bladder cancer", "tissue": "urinary bladder",
                      "cell_type": null, "modality": "scRNA-seq",
                      "design_type": "case_control"}}

Domain diversity 강제:
    BCG / bladder cancer 직접 언급 query 수 ≤ 3 (전체 30 중).
    Short: 10 modality 카테고리 강제.
    Medium: 10 disease 카테고리 강제.
    Complex: 10 design_type 카테고리 강제.

자세한 protocol → data/expert_curated_30/CONSTRUCTION_PROTOCOL.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypedDict, cast


class ExpertQuery(TypedDict):
    qid: str
    category: Literal["short", "medium", "complex"]
    text_en: str
    text_ko: str
    expected_facets: dict[str, str | None]


def load_queries_paired(en_path: Path, ko_path: Path) -> dict[str, ExpertQuery]:
    """EN + KO 두 jsonl 을 qid 기준 join. qid 불일치 시 raise.

    EN 과 KO 가 1:1 paired 인지 검증. 빠진 query 가 있으면 작성 미완으로 간주.
    """
    en_rows: dict[str, dict[str, Any]] = {}
    ko_rows: dict[str, dict[str, Any]] = {}
    for path, sink in [(en_path, en_rows), (ko_path, ko_rows)]:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                sink[d["_id"]] = d
    if set(en_rows) != set(ko_rows):
        miss_en = set(ko_rows) - set(en_rows)
        miss_ko = set(en_rows) - set(ko_rows)
        raise ValueError(f"qid mismatch — only-in-ko={sorted(miss_en)} only-in-en={sorted(miss_ko)}")

    out: dict[str, ExpertQuery] = {}
    for qid, en in en_rows.items():
        ko = ko_rows[qid]
        out[qid] = ExpertQuery(
            qid=qid,
            category=cast(Literal["short", "medium", "complex"], en["category"]),
            text_en=en["text"],
            text_ko=ko["text"],
            expected_facets=cast(dict[str, str | None], en.get("expected_facets", {})),
        )
    return out


def verify_domain_diversity(queries: dict[str, ExpertQuery], max_bcg_or_bladder: int = 3) -> None:
    """BCG / bladder cancer 직접 언급 query 가 ≤ max_bcg_or_bladder 인지 검증.

    OmicsPlorer 의 cohort 추출 데모 사례가 BCG bladder cancer 라 ground truth 가
    그쪽으로 편향될 위험을 자동 차단. 편집자가 30 query 작성 후 첫 단위 테스트.
    """
    needles = ("bcg", "bladder cancer", "방광암")
    n = 0
    for q in queries.values():
        text = (q["text_en"] + " " + q["text_ko"]).lower()
        if any(nd in text for nd in needles):
            n += 1
    if n > max_bcg_or_bladder:
        raise ValueError(
            f"BCG / bladder cancer 직접 언급 query {n}건 — 최대 {max_bcg_or_bladder} 허용. "
            "도메인 다양성 매트릭스 (CONSTRUCTION_PROTOCOL.md) 재검토 필요."
        )
