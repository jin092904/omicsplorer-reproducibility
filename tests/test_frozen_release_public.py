from __future__ import annotations

import json
from pathlib import Path

import pytest

from genofinder_eval.frozen_release_public import (
    PUBLIC_RESPONSE_SCHEMA_VERSION,
    PublicFrozenExportError,
    aggregate_public_observations,
    project_public_metric_observation,
    project_public_observation,
    validate_gdc_open_review,
    validate_public_observations,
)


def _private_observation() -> dict:
    return {
        "schema_version": "private-v1",
        "ordinal": 1,
        "call_id": "call-1",
        "outcome": "success",
        "key": {
            "set_name": "hard_queries",
            "qid": "q1",
            "lang": "en",
            "mode": "bm25_only",
            "axis": "example",
        },
        "query": {"text": "lung RNA", "sha256": "a" * 64},
        "effective_query": {
            "text": "lung RNA",
            "sha256": "a" * 64,
            "translation_applied": False,
        },
        "expected_facets": {
            "disease_ids": ["MONDO:1"],
            "tissue_ids": ["UBERON:1"],
            "modality": ["RNA-seq"],
            "organism_taxid": [9606],
        },
        "request": {
            "access_preference": "open_only",
            "auto_translate": True,
            "corpus": "production",
            "score_k": 10,
            "top_k": 20,
        },
        "response": {
            "http_status": 200,
            "client_attempts": 1,
            "latency_ms": 1250.0,
            "original_query": "lung RNA",
            "translated_query": None,
            "page": 1,
            "page_size": 20,
            "servable_total": 100,
            "total_estimated": 100,
            "response_body_sha256": "b" * 64,
            "query_id": "internal-query-id",
            "evaluation_request": {
                "access_preference": "open_only",
                "auto_translate": True,
                "corpus": "production",
                "lang": "en",
                "mode": "bm25_only",
                "page": 1,
                "page_size": 20,
                "query_text": "lung RNA",
            },
            "evaluation_trace": {
                "components": {"lexical": "used"},
                "configuration_sha256": "c" * 64,
                "effective_mode": "bm25_only",
                "fallbacks": [],
                "requested_mode": "bm25_only",
            },
            "results": [
                {
                    "source_db": "GEO",
                    "source_id": "GSE1",
                    "rank": 1,
                    "score": 2.0,
                    "score_breakdown": {
                        "lexical": 2.0,
                        "semantic": None,
                        "rrf": 2.0,
                        "rerank": None,
                    },
                    "disease_ids": ["MONDO:1"],
                    "tissue_ids": ["UBERON:1"],
                    "cell_type_ids": [],
                    "modality": ["RNA-seq"],
                    "organism_taxid": 9606,
                    "dataset_id": "internal-dataset-id",
                    "title": "third-party title",
                    "abstract_snippet": "third-party text",
                    "access_type": "open",
                    "has_processed_data": True,
                    "library_strategy": "RNA-Seq",
                    "n_samples": 1,
                    "platform": "test",
                    "sources": [],
                    "submission_date": "2026-01-01",
                }
            ],
        },
        "metrics": {
            "eligible": True,
            "facet": {
                "present_macro": 1.0,
                "conjunctive_macro": 1.0,
                "per_facet": {
                    "disease_ids": {"present": True, "conjunctive": True, "n_expected": 1},
                    "tissue_ids": {"present": True, "conjunctive": True, "n_expected": 1},
                    "modality": {"present": True, "conjunctive": True, "n_expected": 1},
                },
                "n_facets_evaluated": 3,
                "unscored_present": ["organism_taxid"],
            },
            "exclusion": {
                "applicable": False,
                "eligible": False,
                "clean_at_k": None,
                "first_violation_rank": None,
                "n_docs_evaluated": 1,
                "violation_count": 0,
                "ineligibility_reason": "none",
            },
        },
        "returned_count": 1,
        "scored_count": 1,
        "wall_ms": 1300.0,
    }


def test_projection_strips_private_and_third_party_fields() -> None:
    public = project_public_observation(_private_observation(), private_row_sha256="d" * 64)
    assert public["schema_version"] == PUBLIC_RESPONSE_SCHEMA_VERSION
    result = public["response"]["results"][0]
    assert result["source_id"] == "GSE1"
    assert "dataset_id" not in result
    assert "title" not in result
    assert "abstract_snippet" not in result
    assert "query_id" not in public["response"]
    validate_public_observations([public], expected_n=1)


def test_public_validation_recomputes_facet_metrics() -> None:
    public = project_public_observation(_private_observation(), private_row_sha256="d" * 64)
    public["metrics"]["facet"]["present_macro"] = 0.0
    with pytest.raises(PublicFrozenExportError, match=r"reproduce facet\.present_macro"):
        validate_public_observations([public], expected_n=1)


def test_public_metric_and_aggregate_rows_derive_from_projection() -> None:
    public = project_public_observation(_private_observation(), private_row_sha256="d" * 64)
    metric = project_public_metric_observation(public)
    assert metric["facet_present_macro"] == 1.0
    assert metric["facet_conjunctive_macro"] == 1.0
    aggregate = aggregate_public_observations([public])
    present = next(row for row in aggregate if row["metric"] == "facet_present_macro")
    assert present["mean"] == 1.0
    assert present["n_queries"] == 1


def test_public_validation_rejects_fallbacks() -> None:
    public = project_public_observation(_private_observation(), private_row_sha256="d" * 64)
    public["response"]["evaluation_trace"]["fallbacks"] = ["dense_to_lexical"]
    with pytest.raises(PublicFrozenExportError, match="fallback"):
        validate_public_observations([public], expected_n=1)


def test_gdc_open_review_requires_exact_open_study_set(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": "omicsplorer-gdc-open-review-v1",
                "records": [
                    {"accession": "GDC-1", "access_status": "open", "study_level_only": True}
                ],
            }
        ),
        encoding="utf-8",
    )
    validate_gdc_open_review(review, {"GDC-1"})
    with pytest.raises(PublicFrozenExportError, match="differ"):
        validate_gdc_open_review(review, {"GDC-1", "GDC-2"})


def test_gdc_open_review_rejects_controlled_record(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": "omicsplorer-gdc-open-review-v1",
                "records": [
                    {
                        "accession": "GDC-1",
                        "access_status": "controlled",
                        "study_level_only": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PublicFrozenExportError, match="not confirmed open"):
        validate_gdc_open_review(review, {"GDC-1"})
