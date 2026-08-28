"""GenoFinderClient + SearchMode 단위 테스트 (respx 로 API mock)."""
from __future__ import annotations

import inspect

import httpx
import pytest
import respx

from genofinder_eval.client.geno_finder import (
    GenoFinderClient,
    GenoFinderResponseInvalid,
    GenoFinderUnavailable,
)
from genofinder_eval.client.search_modes import SearchMode


def test_search_mode_values() -> None:
    assert SearchMode.BM25_ONLY == "bm25_only"
    assert SearchMode.DENSE_ONLY == "dense_only"
    assert SearchMode.RRF == "rrf"
    assert SearchMode.RRF_RERANK == "rrf_rerank"


def test_search_mode_default_is_rrf_rerank() -> None:
    sig = inspect.signature(GenoFinderClient.search)
    assert sig.parameters["mode"].default == SearchMode.RRF_RERANK


_OK_RESPONSE = {
    "results": [
        {
            "dataset_id": "abc",
            "source_db": "GEO",
            "source_id": "GSE1",
            "title": "test",
            "score": 0.95,
            "score_breakdown": {"semantic": 0.9, "lexical": 0.7, "rrf": 0.03, "rerank": 1.5},
            "modality": ["scRNA-seq"],
            "disease_ids": ["MONDO:1"],
            "tissue_ids": ["UBERON:1"],
            "cell_type_ids": [],
        }
    ],
    "latency_ms": 123,
    "query_id": "qid-1",
}


@respx.mock
async def test_search_default_mode_requests_evaluation_trace() -> None:
    """기본 arm도 요청별 effective-path trace를 위해 평가 헤더를 전송한다."""
    route = respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(200, json=_OK_RESPONSE)
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        resp = await client.search("scRNA-seq lung", top_k=15)
    assert resp.results[0].dataset_id == "abc"
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["X-Eval-Mode"] == "1"


@respx.mock
async def test_search_eval_mode_sends_header() -> None:
    """mode=bm25_only 호출은 X-Eval-Mode: 1 헤더 자동 추가."""
    route = respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(200, json=_OK_RESPONSE)
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        await client.search("x", mode=SearchMode.BM25_ONLY)
    sent = route.calls.last.request
    assert sent.headers["X-Eval-Mode"] == "1"


@respx.mock
async def test_search_eval_corpus_sends_header() -> None:
    """corpus=biocaddie_2016_eval 도 X-Eval-Mode 헤더 자동 추가."""
    route = respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(200, json=_OK_RESPONSE)
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        await client.search("x", corpus="biocaddie_2016_eval")
    sent = route.calls.last.request
    assert sent.headers["X-Eval-Mode"] == "1"


@respx.mock
async def test_search_4xx_raises_immediately() -> None:
    """4xx 는 retry 없이 즉시 GenoFinderUnavailable."""
    route = respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(400, json={"detail": "missing header"})
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        with pytest.raises(GenoFinderUnavailable, match="HTTP 400"):
            await client.search("x", mode=SearchMode.BM25_ONLY)
    assert route.call_count == 1  # retry 안 함


@respx.mock
async def test_search_5xx_retries_then_raises() -> None:
    """5xx 는 3회 retry 후 raise."""
    respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(503, json={"detail": "down"})
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        with pytest.raises(GenoFinderUnavailable) as caught:
            await client.search("x")
    assert caught.value.attempts == 3
    assert caught.value.status_code == 503
    assert len(caught.value.response_body_sha256 or "") == 64


@respx.mock
async def test_search_bearer_token_in_header() -> None:
    respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(200, json=_OK_RESPONSE)
    )
    async with GenoFinderClient(
        base_url="http://localhost:8000", bearer_token="test-token"
    ) as client:
        await client.search("x")
    sent = respx.calls.last.request
    assert sent.headers["Authorization"] == "Bearer test-token"


@respx.mock
async def test_invalid_response_preserves_status_attempts_and_body_hash() -> None:
    respx.post("http://localhost:8000/api/v1/search").mock(
        return_value=httpx.Response(200, json={"unexpected": "schema"})
    )
    async with GenoFinderClient(base_url="http://localhost:8000") as client:
        with pytest.raises(GenoFinderResponseInvalid) as caught:
            await client.search("x")
    assert caught.value.attempts == 1
    assert caught.value.status_code == 200
    assert len(caught.value.response_body_sha256 or "") == 64


async def test_search_without_context_manager_raises() -> None:
    client = GenoFinderClient(base_url="http://localhost:8000")
    with pytest.raises(RuntimeError, match="context manager"):
        await client.search("x")
