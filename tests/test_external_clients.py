from __future__ import annotations

import json

import httpx
import pytest
import respx

from genofinder_eval.external.clients import (
    NCBI_BASE,
    OMICSDI_BASE,
    NCBIGeoClient,
    OmicsDIGeoClient,
    OmicsPlorerClient,
)
from genofinder_eval.external.models import QuerySpec

QUERY = QuerySpec(
    qid="q1",
    text="single-cell lung cancer",
    category="medium",
    provenance="unit-test",
)


@pytest.mark.asyncio
@respx.mock
async def test_ncbi_geo_adapter_preserves_rank_and_filters_non_gse() -> None:
    respx.get(f"{NCBI_BASE}/esearch.fcgi").mock(
        return_value=httpx.Response(
            200,
            json={
                "esearchresult": {
                    "count": "2",
                    "idlist": ["10", "11"],
                    "querytranslation": "translated by Entrez",
                }
            },
        )
    )
    respx.get(f"{NCBI_BASE}/esummary.fcgi").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["10", "11"],
                    "10": {
                        "entrytype": "GSE",
                        "accession": "GSE00123",
                        "title": "<b>Relevant</b> study",
                        "summary": "Description",
                        "taxon": "Homo sapiens",
                        "gdstype": "RNA sequencing",
                        "n_samples": 12,
                        "pdat": "2026/01/02",
                        "projects": [],
                    },
                    "11": {"entrytype": "GPL", "accession": "GPL99"},
                }
            },
        )
    )
    async with NCBIGeoClient(email="benchmark@example.org") as client:
        response = await client.search(QUERY, top_k=10)

    assert response.total == 2
    assert [hit.canonical_id for hit in response.hits] == ["GSE123"]
    assert response.hits[0].rank == 1
    assert response.hits[0].title == "Relevant study"
    assert response.request_parameters["api_key_used"] is False
    assert "api_key" not in response.request_parameters


@pytest.mark.asyncio
@respx.mock
async def test_omicsdi_geo_adapter_uses_repository_constraint() -> None:
    route = respx.get(f"{OMICSDI_BASE}/dataset/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "datasets": [
                    {
                        "id": "GSE42",
                        "source": "geo",
                        "title": "A study",
                        "description": "<p>Text</p>",
                        "organisms": [{"name": "Homo sapiens"}],
                        "omicsType": ["Transcriptomics"],
                        "publicationDate": "20260101",
                    }
                ],
                "facets": [],
            },
        )
    )
    async with OmicsDIGeoClient() as client:
        response = await client.search(QUERY, top_k=10)

    assert route.called
    assert response.hits[0].canonical_id == "GSE42"
    assert response.hits[0].description == "Text"
    assert response.hits[0].organism == ["Homo sapiens"]
    assert 'repository:"geo"' in response.request_parameters["query"]


@pytest.mark.asyncio
@respx.mock
async def test_omicsplorer_adapter_disables_translation_and_uses_any_access() -> None:
    route = respx.post("http://api.test/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "dataset_id": "d1",
                        "source_db": "GEO",
                        "source_id": "GSE77",
                        "title": "A study",
                        "abstract_snippet": "Description",
                        "score": 1.2,
                        "score_breakdown": {"rrf": 0.1},
                        "modality": ["scRNA-seq"],
                        "organism_taxid": [9606],
                        "disease_ids": [],
                        "tissue_ids": [],
                        "cell_type_ids": [],
                        "submission_date": "2026-01-01",
                        "n_samples": 4,
                        "sources": [],
                    }
                ],
                "total_estimated": 1,
                "latency_ms": 123,
            },
        )
    )
    async with OmicsPlorerClient(base_url="http://api.test") as client:
        response = await client.search(QUERY, top_k=10)

    body = json.loads(route.calls[0].request.content)
    assert body["auto_translate"] is False
    assert body["access_preference"] == "any"
    assert response.service_latency_ms == 123
    assert response.hits[0].canonical_id == "GSE77"
