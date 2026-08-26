"""Official-API adapters for the external service benchmark.

Only corpus constraints differ by service.  The user query is never rewritten or
expanded in an adapter, which is essential for a fair ranking comparison.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx

from genofinder_eval.external.models import QuerySpec, SearchHit, SearchResponse
from genofinder_eval.external.normalize import (
    canonical_geo_series,
    plain_text,
    unique_strings,
)

ADAPTER_VERSION = "external-services-v1.0.0"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OMICSDI_BASE = "https://www.omicsdi.org/ws"


class ExternalServiceError(RuntimeError):
    """A remote response could not be fetched or validated."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _raw_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class SearchClient(ABC):
    """Common async interface used by the run orchestrator."""

    system: str

    @abstractmethod
    async def search(self, query: QuerySpec, *, top_k: int) -> SearchResponse:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError

    async def __aenter__(self) -> SearchClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()


class OmicsPlorerClient(SearchClient):
    """OmicsPlorer production API adapter with GEO-only filtering."""

    system = "omicsplorer_geo"

    def __init__(self, base_url: str | None = None, timeout_s: float = 90.0) -> None:
        self._base = (
            base_url
            or os.environ.get("OMICSPLORER_API_BASE")
            or os.environ.get("GENOFINDER_API_BASE")
            or "http://127.0.0.1:8000"
        ).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: QuerySpec, *, top_k: int) -> SearchResponse:
        if query.corpus != "geo":
            raise ValueError(f"Unsupported corpus: {query.corpus}")
        body = {
            "query_text": query.text,
            "source_db": ["GEO"],
            "access_preference": "any",
            "auto_translate": False,
            "lang": "en",
            "mode": "rrf_rerank",
            "page": 1,
            "page_size": top_k,
            "corpus": "production",
        }
        started = time.perf_counter()
        response = await self._client.post(f"{self._base}/api/v1/search", json=body)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        raw = response.json()

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in raw.get("results", []):
            candidates = [str(item.get("source_id") or "")]
            candidates.extend(
                str(source.get("source_id") or "")
                for source in item.get("sources", [])
                if isinstance(source, dict)
            )
            canonical = next(
                (value for value in map(canonical_geo_series, candidates) if value),
                None,
            )
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            aliases = unique_strings(candidates)
            hits.append(
                SearchHit(
                    rank=len(hits) + 1,
                    canonical_id=canonical,
                    native_id=str(item.get("dataset_id") or canonical),
                    title=plain_text(item.get("title")),
                    description=plain_text(item.get("abstract_snippet")),
                    source="GEO",
                    url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={canonical}",
                    organism=[str(v) for v in item.get("organism_taxid", [])],
                    assay=unique_strings(list(item.get("modality", []))),
                    publication_date=item.get("submission_date"),
                    sample_count=item.get("n_samples"),
                    native_score=_to_float(item.get("score")),
                    aliases=aliases,
                    metadata={
                        "dataset_id": item.get("dataset_id"),
                        "disease_ids": item.get("disease_ids", []),
                        "tissue_ids": item.get("tissue_ids", []),
                        "cell_type_ids": item.get("cell_type_ids", []),
                        "score_breakdown": item.get("score_breakdown", {}),
                    },
                )
            )

        return SearchResponse(
            system=self.system,
            qid=query.qid,
            query_text=query.text,
            corpus=query.corpus,
            requested_top_k=top_k,
            total=_to_int(raw.get("total_estimated")),
            hits=hits,
            wall_latency_ms=elapsed_ms,
            service_latency_ms=_to_float(raw.get("latency_ms")),
            fetched_at_utc=_utc_now(),
            endpoint=f"{self._base}/api/v1/search",
            request_parameters=body,
            raw_sha256=_raw_hash(raw),
            raw_response=raw,
            http_status=response.status_code,
            adapter_version=ADAPTER_VERSION,
        )


class NCBIGeoClient(SearchClient):
    """NCBI GEO Series adapter using ESearch followed by ESummary."""

    system = "ncbi_geo"

    def __init__(
        self,
        *,
        email: str | None = None,
        tool: str = "omicsplorer_benchmark",
        api_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._email = email or os.environ.get("NCBI_EMAIL", "")
        if not self._email:
            raise ValueError("NCBI_EMAIL or email is required by the NCBI usage policy")
        self._tool = tool
        self._api_key = api_key if api_key is not None else os.environ.get("NCBI_API_KEY", "")
        self._client = httpx.AsyncClient(timeout=timeout_s)
        self._interval = 0.11 if self._api_key else 0.34
        self._last_request = 0.0
        self._rate_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _rate_limited_get(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        full_params = dict(params)
        full_params.update({"tool": self._tool, "email": self._email})
        if self._api_key:
            full_params["api_key"] = self._api_key

        async with self._rate_lock:
            now = time.monotonic()
            wait_s = self._interval - (now - self._last_request)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            response = await self._client.get(f"{NCBI_BASE}/{endpoint}", params=full_params)
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    async def search(self, query: QuerySpec, *, top_k: int) -> SearchResponse:
        if query.corpus != "geo":
            raise ValueError(f"Unsupported corpus: {query.corpus}")
        entrez_term = f"({query.text}) AND gse[Entry Type]"
        safe_search_params = {
            "db": "gds",
            "term": entrez_term,
            "retmode": "json",
            "retmax": top_k,
            "retstart": 0,
            "sort": "relevance",
        }
        started = time.perf_counter()
        esearch_response = await self._rate_limited_get("esearch.fcgi", safe_search_params)
        esearch = esearch_response.json()
        result = esearch.get("esearchresult", {})
        ids = [str(value) for value in result.get("idlist", [])]

        summary: dict[str, Any] = {"result": {"uids": []}}
        summary_status = 200
        if ids:
            summary_params = {"db": "gds", "id": ",".join(ids), "retmode": "json"}
            summary_response = await self._rate_limited_get("esummary.fcgi", summary_params)
            summary_status = summary_response.status_code
            summary = summary_response.json()
        elapsed_ms = (time.perf_counter() - started) * 1000

        summary_result = summary.get("result", {})
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for uid in ids:
            item = summary_result.get(uid, {})
            if str(item.get("entrytype", "")).upper() != "GSE":
                continue
            canonical = canonical_geo_series(str(item.get("accession") or item.get("gse") or ""))
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            projects = item.get("projects", [])
            project_aliases = [
                value
                for project in projects
                if isinstance(project, dict)
                for value in project.values()
                if isinstance(value, (str, int))
            ]
            hits.append(
                SearchHit(
                    rank=len(hits) + 1,
                    canonical_id=canonical,
                    native_id=uid,
                    title=plain_text(item.get("title")),
                    description=plain_text(item.get("summary")),
                    source="NCBI GEO DataSets",
                    url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={canonical}",
                    organism=unique_strings(
                        [item.get("taxon"), item.get("platformtaxa"), item.get("samplestaxa")]
                    ),
                    assay=unique_strings([item.get("gdstype"), item.get("ptechtype")]),
                    publication_date=plain_text(item.get("pdat")) or None,
                    sample_count=_to_int(item.get("n_samples")),
                    aliases=unique_strings(
                        [item.get("accession"), item.get("bioproject"), *project_aliases]
                    ),
                    metadata={
                        "uid": uid,
                        "entrytype": item.get("entrytype"),
                        "pubmedids": item.get("pubmedids", []),
                        "suppfile": item.get("suppfile"),
                        "querytranslation": result.get("querytranslation"),
                    },
                )
            )

        raw = {"esearch": esearch, "esummary": summary}
        return SearchResponse(
            system=self.system,
            qid=query.qid,
            query_text=query.text,
            corpus=query.corpus,
            requested_top_k=top_k,
            total=_to_int(result.get("count")),
            hits=hits,
            wall_latency_ms=elapsed_ms,
            fetched_at_utc=_utc_now(),
            endpoint=f"{NCBI_BASE}/esearch.fcgi + esummary.fcgi",
            request_parameters={
                **safe_search_params,
                "tool": self._tool,
                "email": self._email,
                "api_key_used": bool(self._api_key),
            },
            raw_sha256=_raw_hash(raw),
            raw_response=raw,
            http_status=max(esearch_response.status_code, summary_status),
            adapter_version=ADAPTER_VERSION,
        )


class OmicsDIGeoClient(SearchClient):
    """OmicsDI v1 search adapter restricted to its GEO repository facet."""

    system = "omicsdi_geo"

    def __init__(self, base_url: str = OMICSDI_BASE, timeout_s: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: QuerySpec, *, top_k: int) -> SearchResponse:
        if query.corpus != "geo":
            raise ValueError(f"Unsupported corpus: {query.corpus}")
        omicsdi_query = f'({query.text}) AND repository:"geo"'
        params: dict[str, str | int] = {"query": omicsdi_query, "start": 0, "size": top_k}
        started = time.perf_counter()
        response = await self._client.get(f"{self._base}/dataset/search", params=params)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        raw = response.json()

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in raw.get("datasets", []):
            canonical = canonical_geo_series(str(item.get("id") or ""))
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            organisms = item.get("organisms") or []
            if isinstance(organisms, dict):
                organisms = list(organisms.values())
            elif not isinstance(organisms, list):
                organisms = [organisms]
            organisms = [
                organism.get("name") or organism.get("acc") or ""
                if isinstance(organism, dict)
                else organism
                for organism in organisms
            ]
            omics_types = item.get("omicsType") or []
            if not isinstance(omics_types, list):
                omics_types = [omics_types]
            hits.append(
                SearchHit(
                    rank=len(hits) + 1,
                    canonical_id=canonical,
                    native_id=str(item.get("id") or canonical),
                    title=plain_text(item.get("title")),
                    description=plain_text(item.get("description")),
                    source=plain_text(item.get("source")) or "OmicsDI GEO",
                    url=f"https://www.omicsdi.org/dataset/{item.get('source')}/{canonical}",
                    organism=unique_strings(organisms),
                    assay=unique_strings(omics_types),
                    publication_date=plain_text(item.get("publicationDate")) or None,
                    native_score=_to_float(item.get("score")),
                    aliases=[canonical],
                    metadata={
                        "citations_count": item.get("citationsCount"),
                        "connections_count": item.get("connectionsCount"),
                        "reanalysis_count": item.get("reanalysisCount"),
                    },
                )
            )

        return SearchResponse(
            system=self.system,
            qid=query.qid,
            query_text=query.text,
            corpus=query.corpus,
            requested_top_k=top_k,
            total=_to_int(raw.get("count")),
            hits=hits,
            wall_latency_ms=elapsed_ms,
            fetched_at_utc=_utc_now(),
            endpoint=f"{self._base}/dataset/search",
            request_parameters=params,
            raw_sha256=_raw_hash(raw),
            raw_response=raw,
            http_status=response.status_code,
            adapter_version=ADAPTER_VERSION,
        )


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
