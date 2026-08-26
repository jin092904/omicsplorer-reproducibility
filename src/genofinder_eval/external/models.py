"""Normalized, service-neutral records for external benchmark runs."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Corpus = Literal["geo"]


class QuerySpec(BaseModel):
    """One preregistered benchmark query.

    ``text`` is sent unchanged to every service.  Adapters may only append the
    preregistered corpus constraint (GEO Series), never service-specific synonyms.
    """

    qid: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    text: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1)
    corpus: Corpus = "geo"
    phase: Literal["pilot", "confirmatory", "known_item"] = "pilot"
    target_accession: str | None = None
    provenance: str


class SearchHit(BaseModel):
    """The common subset needed for ranking, pooling, and auditing."""

    rank: int = Field(ge=1)
    canonical_id: str
    native_id: str
    title: str = ""
    description: str = ""
    source: str = ""
    url: str | None = None
    organism: list[str] = Field(default_factory=list)
    assay: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    sample_count: int | None = None
    native_score: float | None = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Normalized response plus enough provenance to audit one request."""

    system: str
    qid: str
    query_text: str
    corpus: Corpus
    requested_top_k: int
    total: int | None = None
    hits: list[SearchHit]
    wall_latency_ms: float = Field(ge=0)
    service_latency_ms: float | None = None
    fetched_at_utc: str
    endpoint: str
    request_parameters: dict[str, Any]
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_response: dict[str, Any]
    http_status: int
    adapter_version: str


class RunFailure(BaseModel):
    """A failure is data, not a silently dropped latency sample."""

    system: str
    qid: str
    error_type: str
    message: str
    fetched_at_utc: str
    elapsed_ms: float = Field(ge=0)
    retry_count: int = Field(ge=0)
