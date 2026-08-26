"""OmicsPlorer retrieval evaluation pipeline.

본 패키지는 OmicsPlorer v1.0 의 retrieval ablation + Korean/English parity +
facet-aware satisfaction 평가를 수행한다. 외부 LLM SaaS 호출은 *전혀 없으며*,
모든 retrieval / reranking 은 OmicsPlorer 자체 API 를 통해서만 호출된다.

Top-level layout:
    adapters/   — 외부 데이터셋 (bioCADDIE) / 자체 ground truth (expert_curated_30) loader
    client/     — OmicsPlorer API (FastAPI) 호출 wrapper + 4-system mode toggle
    metrics/    — TREC 표준 (pytrec_eval) + facet-aware satisfaction (자체 정의)
    runners/    — bioCADDIE / expert-curated 30q 평가 일괄 실행 + significance test
    figures/    — manuscript paper-ready Figure 1/2/3 생성
    utils/      — seed 고정, structlog redact processor
"""
from __future__ import annotations

__version__ = "0.1.0"
