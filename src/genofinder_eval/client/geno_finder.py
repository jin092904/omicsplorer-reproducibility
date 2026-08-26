"""OmicsPlorer `/api/v1/search` async client.

`apps/api/src/schemas/search.py` 의 `SearchRequest` / `SearchResponse` 와 일치하는 schema 를
사용. 본 client 가 schema 를 *재정의* 하지 않고, 호환 가능한 minimal model 만 정의 (api
패키지를 evaluation 패키지가 import 하지 않도록 — 결합도 최소화).

Step 2.5 API patch 이후 (commit e9f757d) `SearchRequest` 에 `mode: SearchMode` 와
`corpus: Literal["production","biocaddie_2016_eval"]` field 가 추가됨. 본 client 는
그 field 를 body 에 그대로 실어 보낸다.

Retry / error 정책:
  - 5xx: exponential backoff max 3 retry (1s → 2s → 4s)
  - 4xx (400/401/403): 즉시 raise GenoFinderUnavailable (사용자 오류 / 인증)
  - timeout / connect error: retry 후 GenoFinderUnavailable
  - Bearer token 우선순위: 인자 > GENOFINDER_BEARER_TOKEN env
  - query_text 는 structlog redact 처리.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from genofinder_eval.client.search_modes import SearchMode
from genofinder_eval.utils.logging import get_logger

logger: structlog.stdlib.BoundLogger = get_logger(__name__)


class GenoFinderUnavailable(RuntimeError):
    """OmicsPlorer API request failed, with publishable attempt metadata."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 1,
        status_code: int | None = None,
        response_body_sha256: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.status_code = status_code
        self.response_body_sha256 = response_body_sha256


class GenoFinderResponseInvalid(GenoFinderUnavailable):
    """The service responded, but its JSON did not satisfy the evaluation schema."""


class _SearchResultMin(BaseModel):
    """`SearchResult` 의 minimal subset — eval 에서 필요한 필드만."""

    # Preserve server-added fields in the normalized per-query release artifact.
    model_config = ConfigDict(extra="allow")

    dataset_id: str
    source_db: str
    source_id: str
    title: str | None = None
    abstract_snippet: str | None = None  # exclusion(must_not_contain) 채점용 텍스트 신호
    score: float
    score_breakdown: dict[str, float | None]  # semantic / lexical / rrf / rerank
    modality: list[str] = Field(default_factory=list)
    organism_taxid: list[int] = Field(default_factory=list)
    disease_ids: list[str] = Field(default_factory=list)
    tissue_ids: list[str] = Field(default_factory=list)
    cell_type_ids: list[str] = Field(default_factory=list)
    library_strategy: str | None = None
    platform: str | None = None
    access_type: str | None = None
    has_processed_data: bool | None = None
    submission_date: str | None = None
    n_samples: int | None = None


class _SearchResponseMin(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[_SearchResultMin]
    latency_ms: int
    query_id: str
    page: int | None = None
    page_size: int | None = None
    total_estimated: int | None = None
    servable_total: int | None = None
    original_query: str | None = None
    translated_query: str | None = None
    client_attempts: int = 1
    http_status: int = 200
    response_body_sha256: str | None = None
    evaluation_request: dict[str, Any] = Field(default_factory=dict)


def _is_retryable(exc: BaseException) -> bool:
    """5xx 또는 connect 실패(일시적)만 retry. ReadTimeout(느린 응답)은 재시도해도
    안 빨라지므로 즉시 fail → 러너가 그 쿼리만 스킵하고 계속. 4xx 즉시 fail."""
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    return False


class GenoFinderClient:
    """async wrapper for `/api/v1/search`.

    Usage:
        async with GenoFinderClient() as client:
            resp = await client.search("scRNA-seq lung", top_k=15, mode=SearchMode.RRF_RERANK)
    """

    def __init__(
        self,
        base_url: str | None = None,
        bearer_token: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._base = (base_url or os.environ.get("GENOFINDER_API_BASE", "http://localhost:8000")).rstrip("/")
        self._token = (
            bearer_token if bearer_token is not None else os.environ.get("GENOFINDER_BEARER_TOKEN", "")
        )
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GenoFinderClient:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.AsyncClient(base_url=self._base, headers=headers, timeout=self._timeout)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(
        self,
        query_text: str,
        *,
        top_k: int = 15,
        mode: SearchMode = SearchMode.RRF_RERANK,
        lang: Literal["ko", "en"] | None = None,
        corpus: str = "production",
        auto_translate: bool = True,
        access_preference: Literal["any", "open_only"] = "open_only",
        filters: dict[str, Any] | None = None,
    ) -> _SearchResponseMin:
        """OmicsPlorer `/api/v1/search` 호출.

        Args:
            query_text: 검색 query.
            top_k: 결과 갯수 상한 (api 의 page_size 에 매핑, 1-100).
            mode: 4-system ablation 모드. non-default 시 X-Eval-Mode 헤더 자동 추가.
            lang: 요청에 명시하는 언어 메타정보.
            corpus: 'production' | 'biocaddie_2016_eval'.
            auto_translate: 비ASCII 검색어의 서버측 번역 허용 여부. 동결 평가에서는
                설정 manifest 와 동일한 값을 명시해야 함.
            access_preference: 공개 데이터만 또는 접근조건 무관 검색.
            filters: api `SearchRequest` 의 기타 필드 (modality / disease_ids 등).

        Raises:
            GenoFinderUnavailable: 5xx retry 초과, timeout, connect error, 4xx (즉시).
        """
        if self._client is None:
            raise RuntimeError("Use `async with GenoFinderClient()` context manager.")

        body: dict[str, Any] = {
            "query_text": query_text,
            "mode": str(mode),
            "corpus": corpus,
            "page": 1,
            "page_size": max(1, min(100, top_k)),
            "lang": lang,
            "auto_translate": auto_translate,
            "access_preference": access_preference,
        }
        if filters:
            body.update(filters)

        headers: dict[str, str] = {}
        if mode != SearchMode.RRF_RERANK or corpus != "production":
            headers["X-Eval-Mode"] = "1"

        logger.info(
            "search_request",
            mode=str(mode),
            corpus=corpus,
            top_k=top_k,
            lang=lang,
            query_text=query_text,  # redact processor 가 masking
        )

        attempt_count = 0
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                attempt_count = attempt.retry_state.attempt_number
                with attempt:
                    resp = await self._client.post(
                        "/api/v1/search", json=body, headers=headers
                    )
                    resp.raise_for_status()
        except GenoFinderUnavailable:
            raise
        except httpx.HTTPStatusError as exc:
            body_hash = hashlib.sha256(exc.response.content).hexdigest()
            raise GenoFinderUnavailable(
                f"HTTP {exc.response.status_code}; response body retained only by SHA-256",
                attempts=max(1, attempt_count),
                status_code=exc.response.status_code,
                response_body_sha256=body_hash,
            ) from exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise GenoFinderUnavailable(
                type(exc).__name__, attempts=max(1, attempt_count)
            ) from exc

        response_hash = hashlib.sha256(resp.content).hexdigest()
        try:
            data = resp.json()
            parsed = _SearchResponseMin.model_validate(data)
        except Exception as exc:
            raise GenoFinderResponseInvalid(
                f"invalid search response: {type(exc).__name__}",
                attempts=max(1, attempt_count),
                status_code=resp.status_code,
                response_body_sha256=response_hash,
            ) from exc
        parsed.client_attempts = max(1, attempt_count)
        parsed.http_status = resp.status_code
        parsed.response_body_sha256 = response_hash
        parsed.evaluation_request = body
        return parsed
