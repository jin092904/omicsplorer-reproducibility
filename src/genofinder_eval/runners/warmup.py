"""Reranker / embedding model cold-start 회피용 warmup 호출.

평가 query 첫 호출 시 Qwen3-Reranker-0.6B 가 sentence-transformers 로 lazy load 되어
3-5 초 지연. warm-up 호출 1회 후 정상 latency 측정.

`runners/run_*.py` 가 본 함수를 평가 시작 전 자동 호출.
"""
from __future__ import annotations

from genofinder_eval.client.geno_finder import GenoFinderClient
from genofinder_eval.client.search_modes import SearchMode


async def warmup_reranker(client: GenoFinderClient) -> None:
    """Dummy query 1회 발사 — 결과 폐기."""
    try:
        await client.search(
            query_text="warmup query for reranker cold start",
            top_k=5,
            mode=SearchMode.RRF_RERANK,
        )
    except NotImplementedError:
        # Step 2 미구현 시점에는 silent — Step 2 구현 후 정상 동작.
        return
