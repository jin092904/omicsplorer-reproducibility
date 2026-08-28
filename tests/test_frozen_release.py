"""Offline tests for the submission-release contract and hard-query runner."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from genofinder_eval.client.geno_finder import GenoFinderUnavailable
from genofinder_eval.frozen_release import (
    FrozenConfigError,
    frozen_response_path_issues,
    load_frozen_config,
    validate_release_directory,
)
from genofinder_eval.runners.run_hard_queries import run

_FIXTURE_EFFECTIVE_CONFIGURATION_SHA256 = ""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _canonical_set_sha(values: set[str]) -> str:
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _make_config(root: Path) -> Path:
    global _FIXTURE_EFFECTIVE_CONFIGURATION_SHA256
    protocol = root / "protocol.md"
    accessions = root / "accessions.tsv"
    stores = root / "stores.json"
    lineage_manifest = root / "structuring-lineages.json"
    structuring_prompt = root / "structuring-prompt.txt"
    structuring_schema = root / "structuring-schema.json"
    structuring_options = root / "structuring-options.json"
    translation_prompt = root / "translation-prompt.txt"
    translation_options = root / "translation-options.json"
    effective_server_config = root / "effective-server-config.json"
    lock = root / "uv.lock"
    protocol.write_text("# Fixed protocol\n", encoding="utf-8")
    accessions.write_text(
        "source_db\taccession\tinternal_dataset_id\tsnapshot_id\t"
        "extraction_version\textraction_lineage_id\tbuild_stage\n"
        "GEO\tGSE1\td1\tsnapshot-2026-08-25\tv1\tlocal-v1\tindexed\n",
        encoding="utf-8",
    )
    structuring_prompt.write_text("fixed extraction prompt\n", encoding="utf-8")
    _write_json(structuring_schema, {"type": "object", "additionalProperties": False})
    _write_json(structuring_options, {"temperature": 0, "parser": "strict"})
    _write_json(
        lineage_manifest,
        {
            "schema_version": "omicsplorer-structuring-lineages-v2",
            "mixed_history_note": "one local-model lineage in this fixture",
            "lineages": [
                {
                    "lineage_id": "local-v1",
                    "parent_lineage_ids": [],
                    "extractor_kind": "local_model",
                    "checkpoint": "example/metadata-extractor",
                    "revision": "7" * 40,
                    "weight_digest_sha256": "8" * 64,
                    "quantization": "Q4_K_M",
                    "serving_engine": "ollama-0.11.0",
                    "prompt_path": structuring_prompt.name,
                    "prompt_sha256": _sha(structuring_prompt),
                    "schema_path": structuring_schema.name,
                    "schema_sha256": _sha(structuring_schema),
                    "options_path": structuring_options.name,
                    "options_sha256": _sha(structuring_options),
                    "deterministic_postprocessing_revision": "9" * 40,
                    "limitations": "synthetic test lineage",
                }
            ],
        },
    )
    dataset_hash = _canonical_set_sha({"d1"})
    _write_json(
        stores,
        {
            "schema_version": "omicsplorer-store-evidence-v1",
            "captured_at_utc": "2026-08-25T00:00:00Z",
            "database": {
                "snapshot_id": "db-snapshot-1",
                "row_count": 1,
                "accession_membership_count": 1,
                "dataset_id_set_sha256": dataset_hash,
                "schema_revision": "alembic-head-1",
            },
            "qdrant": {
                "snapshot_id": "qdrant-snapshot-1",
                "point_count": 1,
                "dataset_id_set_sha256": dataset_hash,
                "collection_config_sha256": "a" * 64,
            },
            "opensearch": {
                "snapshot_id": "os-snapshot-1",
                "document_count": 1,
                "dataset_id_set_sha256": dataset_hash,
                "mapping_sha256": "b" * 64,
                "settings_sha256": "c" * 64,
            },
            "cross_store_mismatch_count": 0,
        },
    )
    translation_prompt.write_text("translate Korean to English\n", encoding="utf-8")
    _write_json(translation_options, {"temperature": 0, "seed": 42})
    lock.write_text("version = 1\n", encoding="utf-8")
    embedding = {
        "checkpoint": "example/embedding-model",
        "revision": "1" * 40,
        "digest_sha256": "2" * 64,
        "quantization": "Q4_K_M",
        "serving_engine": "ollama-0.11.0",
        "instruction_prefix": "<none>",
        "pooling": "model-native",
        "truncation_dimension": 1024,
    }
    translation = {
        "checkpoint": "example/translator",
        "revision": "d" * 40,
        "digest_sha256": "e" * 64,
        "quantization": "Q4_K_M",
        "serving_engine": "ollama-0.11.0",
        "prompt_path": translation_prompt.name,
        "prompt_sha256": _sha(translation_prompt),
        "options_path": translation_options.name,
        "options_sha256": _sha(translation_options),
        "cache_policy": "disabled for release collection",
    }
    effective = {
        "schema_version": "omicsplorer-effective-server-config-v1",
        "corpus": "production",
        "lexical_index": "datasets_v2@snapshot-1",
        "dense_collection": "datasets_v2@snapshot-1",
        "lexical_candidate_count": 200,
        "dense_candidate_count": 200,
        "rrf_k": 60,
        "corpus_embedding": embedding,
        "query_embedding": embedding,
        "reranker": {
            "checkpoint": "example/reranker",
            "revision": "3" * 40,
            "digest_sha256": "4" * 64,
            "quantization": "Q4_K_M",
            "top_n": 20,
        },
        "translation": {"enabled": True, "model": translation},
        "query_understanding": {"enabled": False, "model": None},
        "access_preference": "open_only",
        "fallback_policy": "fallback is recorded as an arm failure",
        "accession_shortcut_enabled": True,
        "cardinality_boost_enabled": True,
        "container_image_digest": "sha256:" + "5" * 64,
    }
    _write_json(effective_server_config, effective)
    _FIXTURE_EFFECTIVE_CONFIGURATION_SHA256 = _canonical_json_sha(effective)
    config = {
        "schema_version": "omicsplorer-frozen-eval-config-v1",
        "release_id": "gpb-appnote-test-v1",
        "protocol_id": "gpb-application-note-hard-facet-v1",
        "protocol_path": protocol.name,
        "protocol_sha256": _sha(protocol),
        "corpus": {
            "snapshot_id": "snapshot-2026-08-25",
            "cutoff_utc": "2026-08-25T00:00:00Z",
            "accession_manifest_path": accessions.name,
            "accession_manifest_sha256": _sha(accessions),
            "stores_manifest_path": stores.name,
            "stores_manifest_sha256": _sha(stores),
            "row_count": 1,
            "deduplication_rule": "one row per internal dataset identifier",
            "database_snapshot_id": "db-snapshot-1",
            "qdrant_snapshot_id": "qdrant-snapshot-1",
            "opensearch_snapshot_id": "os-snapshot-1",
            "schema_revision": "alembic-head-1",
        },
        "models": {
            "metadata_structuring": {
                "lineage_manifest_path": lineage_manifest.name,
                "lineage_manifest_sha256": _sha(lineage_manifest),
                "row_lineage_field": "extraction_lineage_id",
                "row_extraction_version_field": "extraction_version",
                "row_build_stage_field": "build_stage",
                "mixed_history_policy": "retain every row-level lineage",
            },
            "corpus_embedding": embedding,
            "query_embedding": embedding,
            "reranker_checkpoint": "example/reranker",
            "reranker_revision": "3" * 40,
            "reranker_digest_sha256": "4" * 64,
            "reranker_quantization": "Q4_K_M",
            "query_understanding": None,
            "translation": translation,
        },
        "retrieval": {
            "corpus": "production",
            "lexical_index": "datasets_v2@snapshot-1",
            "dense_collection": "datasets_v2@snapshot-1",
            "lexical_candidate_count": 200,
            "dense_candidate_count": 200,
            "rrf_k": 60,
            "reranker_top_n": 20,
            "access_preference": "open_only",
            "auto_translate": True,
            "query_understanding_enabled": False,
            "effective_trace_required": True,
            "effective_configuration_path": effective_server_config.name,
            "effective_configuration_sha256": (_FIXTURE_EFFECTIVE_CONFIGURATION_SHA256),
            "fallback_policy": "fallback is recorded as an arm failure",
            "accession_shortcut_enabled": True,
            "cardinality_boost_enabled": True,
        },
        "evaluation": {
            "query_sets": ["hard_queries"],
            "languages": ["en", "ko"],
            "modes": ["bm25_only", "dense_only", "rrf", "rrf_rerank"],
            "top_k": 20,
            "score_k": 10,
            "seed": 42,
            "timeout_s": 180.0,
            "warmup": "unscored_recorded",
            "primary_metrics": ["facet_present_macro", "facet_conjunctive_macro"],
            "failure_policy": "report_separately_no_imputation",
            "expected_query_count": 49,
        },
        "runtime": {
            "dependency_lock_path": lock.name,
            "dependency_lock_sha256": _sha(lock),
            "container_image_digest": "sha256:" + "5" * 64,
            "hardware": "test fixture; no accelerator",
        },
    }
    path = root / "freeze-config.json"
    _write_json(path, config)
    return path


def _make_query_data(root: Path) -> Path:
    data = root / "data" / "hard_queries"
    data.mkdir(parents=True)
    rows = [("q001", "success query 1", "성공 질의 1")]
    rows.append(("q002", "zero query", "빈 결과 질의"))
    rows.append(("q003", "failure query", "실패 질의"))
    rows.extend(
        (f"q{index:03d}", f"success query {index}", f"성공 질의 {index}") for index in range(4, 50)
    )
    for lang, index in (("en", 1), ("ko", 2)):
        path = data / f"queries_{lang}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for qid, en, ko in rows:
                handle.write(
                    json.dumps(
                        {
                            "_id": qid,
                            "category": "test",
                            "text": (en, ko)[index - 1],
                            "expected_facets": {
                                "modality": ["scRNA-seq"],
                                "must_not_contain": ["forbidden"],
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    with (data / "facet_judgments.jsonl").open("w", encoding="utf-8") as handle:
        for qid, _en, _ko in rows:
            handle.write(
                json.dumps(
                    {
                        "qid": qid,
                        "expected": {
                            "modality": ["scRNA-seq"],
                            "must_not_contain": ["forbidden"],
                        },
                    }
                )
                + "\n"
            )
    with (data / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["qid", "axis"])
        writer.writeheader()
        for qid, _en, _ko in rows:
            writer.writerow({"qid": qid, "axis": "test"})
    return data


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.payload


class _FakeClient:
    def __init__(self, *, timeout_s: float) -> None:
        self.timeout_s = timeout_s

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def search(self, query_text: str, **kwargs: Any) -> _FakeResponse:
        if "failure" in query_text or "실패" in query_text:
            raise GenoFinderUnavailable(
                "request failed token-for-test", attempts=3, status_code=503
            )
        mode_value = getattr(kwargs["mode"], "value", kwargs["mode"])
        lang = str(kwargs["lang"])
        results: list[dict[str, Any]] = []
        if "zero" not in query_text and "빈 결과" not in query_text:
            breakdown = {
                "semantic": 1.0 if mode_value != "bm25_only" else None,
                "lexical": 1.0 if mode_value != "dense_only" else None,
                "rrf": 1.0 if mode_value in {"rrf", "rrf_rerank"} else None,
                "rerank": 0.9 if mode_value == "rrf_rerank" else None,
            }
            results = [
                {
                    "dataset_id": "d1",
                    "source_db": "GEO",
                    "source_id": "GSE1",
                    "title": "scRNA-seq study",
                    "abstract_snippet": "clean text",
                    "score": 1.0,
                    "score_breakdown": breakdown,
                    "access_type": "open",
                    "modality": ["scRNA-seq"],
                    "disease_ids": [],
                    "tissue_ids": [],
                    "cell_type_ids": [],
                }
            ]
        response = {
            "results": results,
            "latency_ms": 10,
            "query_id": "service-query-id",
            "evaluation_request": {
                "query_text": query_text,
                "mode": mode_value,
                "corpus": kwargs["corpus"],
                "page": 1,
                "page_size": kwargs["top_k"],
                "lang": lang,
                "auto_translate": kwargs["auto_translate"],
                "access_preference": kwargs["access_preference"],
            },
            "evaluation_trace": {
                "requested_mode": mode_value,
                "effective_mode": mode_value,
                "fallbacks": [],
                "configuration_sha256": (_FIXTURE_EFFECTIVE_CONFIGURATION_SHA256),
                "components": {
                    "lexical": (
                        "used"
                        if mode_value in {"bm25_only", "rrf", "rrf_rerank"}
                        else "not_requested"
                    ),
                    "dense": (
                        "used"
                        if mode_value in {"dense_only", "rrf", "rrf_rerank"}
                        else "not_requested"
                    ),
                    "reranker": ("used" if mode_value == "rrf_rerank" else "not_requested"),
                    "translation": "used" if lang == "ko" else "not_needed",
                    "query_understanding": "disabled",
                    "accession_shortcut": {"enabled": True, "applied": False},
                    "cardinality_boost": {"enabled": True, "applied": False},
                },
            },
        }
        if lang == "ko":
            response["translated_query"] = f"translated: {query_text}"
        return _FakeResponse(response)


class _InvalidWarmupClient(_FakeClient):
    call_count = 0

    async def search(self, query_text: str, **kwargs: Any) -> _FakeResponse:
        type(self).call_count += 1
        response = await super().search(query_text, **kwargs)
        if query_text.startswith("warmup query"):
            response.payload["evaluation_trace"]["configuration_sha256"] = "0" * 64
        return response


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    subprocess.run(["git", "tag", "gpb-appnote-test-v1"], cwd=repo, check=True)


def test_config_rejects_embedding_vector_space_mismatch(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["query_embedding"]["digest_sha256"] = "9" * 64
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="vector-space settings differ"):
        load_frozen_config(config_path)


def test_config_rejects_weakened_protocol_contract(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["evaluation"]["modes"] = ["bm25_only"]
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="machine-readable protocol contract"):
        load_frozen_config(config_path)


def test_config_rejects_cross_store_content_mismatch(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    stores_path = tmp_path / "stores.json"
    stores = json.loads(stores_path.read_text(encoding="utf-8"))
    stores["qdrant"]["dataset_id_set_sha256"] = "0" * 64
    _write_json(stores_path, stores)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["corpus"]["stores_manifest_sha256"] = _sha(stores_path)
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="Qdrant dataset_id_set_sha256"):
        load_frozen_config(config_path)


def test_config_rejects_unmapped_row_extraction_lineage(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    accessions_path = tmp_path / "accessions.tsv"
    accessions_path.write_text(
        accessions_path.read_text(encoding="utf-8").replace("local-v1", "missing-v2"),
        encoding="utf-8",
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["corpus"]["accession_manifest_sha256"] = _sha(accessions_path)
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="lineage not declared"):
        load_frozen_config(config_path)


def _non_model_lineage(lineage_id: str, parents: list[str] | None = None) -> dict[str, Any]:
    return {
        "lineage_id": lineage_id,
        "parent_lineage_ids": parents or [],
        "extractor_kind": "non_model",
        "checkpoint": None,
        "revision": None,
        "weight_digest_sha256": None,
        "quantization": None,
        "serving_engine": None,
        "prompt_path": None,
        "prompt_sha256": None,
        "schema_path": None,
        "schema_sha256": None,
        "options_path": None,
        "options_sha256": None,
        "deterministic_postprocessing_revision": "6" * 40,
        "limitations": "synthetic deterministic parent lineage",
    }


def test_config_accepts_reachable_parent_lineage(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    lineages_path = tmp_path / "structuring-lineages.json"
    lineages = json.loads(lineages_path.read_text(encoding="utf-8"))
    lineages["lineages"][0]["parent_lineage_ids"] = ["source-v1"]
    lineages["lineages"].append(_non_model_lineage("source-v1"))
    _write_json(lineages_path, lineages)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["metadata_structuring"]["lineage_manifest_sha256"] = _sha(lineages_path)
    _write_json(config_path, raw)

    assert load_frozen_config(config_path).release_id == "gpb-appnote-test-v1"


def test_config_rejects_undeclared_parent_lineage(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    lineages_path = tmp_path / "structuring-lineages.json"
    lineages = json.loads(lineages_path.read_text(encoding="utf-8"))
    lineages["lineages"][0]["parent_lineage_ids"] = ["missing-parent"]
    _write_json(lineages_path, lineages)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["metadata_structuring"]["lineage_manifest_sha256"] = _sha(lineages_path)
    _write_json(config_path, raw)

    with pytest.raises(FrozenConfigError, match="undeclared parent"):
        load_frozen_config(config_path)


def test_config_rejects_lineage_cycle(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    lineages_path = tmp_path / "structuring-lineages.json"
    lineages = json.loads(lineages_path.read_text(encoding="utf-8"))
    lineages["lineages"][0]["parent_lineage_ids"] = ["source-v1"]
    lineages["lineages"].append(_non_model_lineage("source-v1", ["local-v1"]))
    _write_json(lineages_path, lineages)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["metadata_structuring"]["lineage_manifest_sha256"] = _sha(lineages_path)
    _write_json(config_path, raw)

    with pytest.raises(FrozenConfigError, match="lineage graph contains a cycle"):
        load_frozen_config(config_path)


def test_config_rejects_unreachable_lineage_declaration(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    lineages_path = tmp_path / "structuring-lineages.json"
    lineages = json.loads(lineages_path.read_text(encoding="utf-8"))
    lineages["lineages"].append(_non_model_lineage("unused-v1"))
    _write_json(lineages_path, lineages)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["metadata_structuring"]["lineage_manifest_sha256"] = _sha(lineages_path)
    _write_json(config_path, raw)

    with pytest.raises(FrozenConfigError, match="not reachable"):
        load_frozen_config(config_path)


def test_config_rejects_accession_placeholders_and_ambiguous_mapping(
    tmp_path: Path,
) -> None:
    config_path = _make_config(tmp_path)
    accessions_path = tmp_path / "accessions.tsv"
    original = accessions_path.read_text(encoding="utf-8")
    accessions_path.write_text(
        original.replace("GSE1", "TODO")
        + "GEO\tTODO\td2\tsnapshot-2026-08-25\tv1\tlocal-v1\tindexed\n",
        encoding="utf-8",
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["corpus"]["accession_manifest_sha256"] = _sha(accessions_path)
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError) as exc_info:
        load_frozen_config(config_path)
    message = str(exc_info.value)
    assert "placeholder fields" in message

    accessions_path.write_text(
        original + "GEO\tGSE1\td2\tsnapshot-2026-08-25\tv1\tlocal-v1\tindexed\n",
        encoding="utf-8",
    )
    raw["corpus"]["accession_manifest_sha256"] = _sha(accessions_path)
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="maps to multiple internal datasets"):
        load_frozen_config(config_path)


def test_config_binds_canonical_effective_server_configuration(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    effective_path = tmp_path / "effective-server-config.json"
    effective = json.loads(effective_path.read_text(encoding="utf-8"))
    effective["lexical_candidate_count"] = 199
    _write_json(effective_path, effective)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["retrieval"]["effective_configuration_sha256"] = _canonical_json_sha(effective)
    _write_json(config_path, raw)
    with pytest.raises(
        FrozenConfigError,
        match="effective server configuration differs from frozen config",
    ):
        load_frozen_config(config_path)


def test_config_rejects_rehashed_placeholder_asset_content(tmp_path: Path) -> None:
    config_path = _make_config(tmp_path)
    options_path = tmp_path / "translation-options.json"
    _write_json(
        options_path,
        {"temperature": 0, "decoding": "REQUIRED_EFFECTIVE_DECODING_POLICY"},
    )
    options_sha = _sha(options_path)
    effective_path = tmp_path / "effective-server-config.json"
    effective = json.loads(effective_path.read_text(encoding="utf-8"))
    effective["translation"]["model"]["options_sha256"] = options_sha
    _write_json(effective_path, effective)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["models"]["translation"]["options_sha256"] = options_sha
    raw["retrieval"]["effective_configuration_sha256"] = _canonical_json_sha(effective)
    _write_json(config_path, raw)
    with pytest.raises(FrozenConfigError, match="unresolved placeholder value"):
        load_frozen_config(config_path)


def test_effective_trace_rejects_failed_component_state(tmp_path: Path) -> None:
    config = load_frozen_config(_make_config(tmp_path))
    response = {
        "results": [],
        "evaluation_trace": {
            "requested_mode": "bm25_only",
            "effective_mode": "bm25_only",
            "fallbacks": [],
            "configuration_sha256": (config.retrieval.effective_configuration_sha256),
            "components": {
                "lexical": "failed",
                "dense": "not_requested",
                "reranker": "not_requested",
                "translation": "not_needed",
                "query_understanding": "disabled",
                "accession_shortcut": {"enabled": True, "applied": False},
                "cardinality_boost": {"enabled": True, "applied": False},
            },
        },
    }
    issues = frozen_response_path_issues(
        config=config,
        mode="bm25_only",
        lang="en",
        query_text="test query",
        response=response,
    )
    assert any("components.lexical" in issue for issue in issues)

    response["evaluation_trace"]["components"]["lexical"] = "used"
    response["evaluation_trace"]["components"]["translation"] = "used"
    translation_issues = frozen_response_path_issues(
        config=config,
        mode="bm25_only",
        lang="ko",
        query_text="한국어 질의",
        response=response,
    )
    assert any("translated_query is missing" in issue for issue in translation_issues)
    response["translated_query"] = "한국어 질의"
    echo_issues = frozen_response_path_issues(
        config=config,
        mode="bm25_only",
        lang="ko",
        query_text="한국어 질의",
        response=response,
    )
    assert any("echoes query_text" in issue for issue in echo_issues)


def test_effective_trace_rejects_partially_scored_rerank_results(
    tmp_path: Path,
) -> None:
    config = load_frozen_config(_make_config(tmp_path))
    scored = {
        "score": 0.9,
        "score_breakdown": {
            "semantic": 0.8,
            "lexical": 0.7,
            "rrf": 0.6,
            "rerank": 0.9,
        },
    }
    partial = {
        "score": 0.8,
        "score_breakdown": {
            "semantic": 0.7,
            "lexical": 0.6,
            "rrf": None,
            "rerank": None,
        },
    }
    scored["score"] = True
    scored["score_breakdown"]["rerank"] = True
    response = {
        "results": [scored, partial],
        "evaluation_trace": {
            "requested_mode": "rrf_rerank",
            "effective_mode": "rrf_rerank",
            "fallbacks": [],
            "configuration_sha256": (config.retrieval.effective_configuration_sha256),
            "components": {
                "lexical": "used",
                "dense": "used",
                "reranker": "used",
                "translation": "not_needed",
                "query_understanding": "disabled",
                "accession_shortcut": {"enabled": True, "applied": False},
                "cardinality_boost": {"enabled": True, "applied": False},
            },
        },
    }
    issues = frozen_response_path_issues(
        config=config,
        mode="rrf_rerank",
        lang="en",
        query_text="test query",
        response=response,
    )
    assert any("result 2 lacks its base RRF score" in issue for issue in issues)
    assert any("result 2 lacks a reranker score" in issue for issue in issues)
    assert any("nonnumeric rerank score" in issue for issue in issues)
    assert any("nonnumeric top-level score" in issue for issue in issues)


async def test_frozen_runner_aborts_after_invalid_warmup_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _make_query_data(tmp_path)
    config_path = _make_config(tmp_path)
    _commit_all(tmp_path)
    monkeypatch.setenv("GENOFINDER_BEARER_TOKEN", "token-for-test")
    _InvalidWarmupClient.call_count = 0

    release_dir = tmp_path / "release"
    with pytest.raises(ValueError, match="warmup effective path is invalid"):
        await run(
            set_name="hard_queries",
            data_dir=data_dir,
            top_k=20,
            score_k=10,
            modes=["bm25_only", "dense_only", "rrf", "rrf_rerank"],
            seed=42,
            release_dir=release_dir,
            freeze_config_path=config_path,
            repo=tmp_path,
            client_factory=_InvalidWarmupClient,
        )

    assert _InvalidWarmupClient.call_count == 1
    warmup = json.loads((release_dir / "warmup.json").read_text(encoding="utf-8"))
    assert warmup["outcome"] == "invalid_effective_path"
    assert warmup["trace_issues"] == ["evaluation_trace.configuration_sha256 mismatch"]
    manifest = json.loads((release_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    assert manifest["submission_eligible"] is False
    assert manifest["counts"]["attempted"] == 0


async def test_frozen_runner_separates_success_zero_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _make_query_data(tmp_path)
    config_path = _make_config(tmp_path)
    _commit_all(tmp_path)
    monkeypatch.setenv("GENOFINDER_BEARER_TOKEN", "token-for-test")

    release_dir = tmp_path / "release"
    await run(
        set_name="hard_queries",
        data_dir=data_dir,
        top_k=20,
        score_k=10,
        modes=["bm25_only", "dense_only", "rrf", "rrf_rerank"],
        seed=42,
        release_dir=release_dir,
        freeze_config_path=config_path,
        repo=tmp_path,
        client_factory=_FakeClient,
    )

    manifest = json.loads((release_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete_with_failures"
    assert manifest["submission_eligible"] is True
    assert manifest["counts"] == {
        "expected": 392,
        "attempted": 392,
        "success": 384,
        "failure": 8,
        "zero_result": 8,
        "missing": 0,
    }

    observations = [
        json.loads(line)
        for line in (release_dir / "per_query_responses.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(observations) == 392
    zero = next(row for row in observations if row["outcome"] == "zero_result")
    failure = next(row for row in observations if row["outcome"] == "failure")
    assert zero["metrics"]["facet"]["present_macro"] == 0.0
    assert zero["metrics"]["exclusion"]["clean_at_k"] is None
    assert failure["metrics"]["eligible"] is False
    assert failure["error"]["client_attempts"] == 3

    all_release_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in release_dir.rglob("*")
        if path.is_file()
    )
    assert "token-for-test" not in all_release_text
    report = validate_release_directory(release_dir)
    assert report["status"] == "GO", report

    def refresh_artifact(role: str, path: Path, record_count: int) -> None:
        descriptor = next(item for item in manifest["artifacts"] if item["role"] == role)
        descriptor["sha256"] = _sha(path)
        descriptor["bytes"] = path.stat().st_size
        descriptor["record_count"] = record_count

    raw_path = release_dir / "per_query_responses.jsonl"
    original_observations = json.loads(json.dumps(observations))

    failure_path = release_dir / "failures.jsonl"
    original_failures = [row for row in original_observations if row["outcome"] == "failure"]
    failure_tampered = json.loads(json.dumps(original_failures))
    failure_tampered[0]["error"]["message"] = "edited failure explanation"
    _write_jsonl(failure_path, failure_tampered)
    refresh_artifact("failures", failure_path, len(failure_tampered))
    manifest["errors"][0]["message"] = "edited failure explanation"
    _write_json(release_dir / "run_manifest.json", manifest)
    failure_report = validate_release_directory(release_dir)
    assert failure_report["status"] == "NO-GO"
    assert any("failure artifact row differs" in error for error in failure_report["errors"])
    assert any(
        "manifest errors do not exactly project" in error for error in failure_report["errors"]
    )
    _write_jsonl(failure_path, original_failures)
    refresh_artifact("failures", failure_path, len(original_failures))
    manifest["errors"] = [{"call_id": row["call_id"], **row["error"]} for row in original_failures]

    # Re-hashing an edited raw query must not detach it from the bundled query text.
    query_tampered = json.loads(json.dumps(original_observations))
    changed_query = next(row for row in query_tampered if row["outcome"] == "success")
    changed_query["query"] = {
        "text": "fabricated replacement query",
        "sha256": hashlib.sha256(b"fabricated replacement query").hexdigest(),
    }
    _write_jsonl(raw_path, query_tampered)
    refresh_artifact("raw_observations", raw_path, len(query_tampered))
    _write_json(release_dir / "run_manifest.json", manifest)
    query_report = validate_release_directory(release_dir)
    assert query_report["status"] == "NO-GO"
    assert any("query differs from bundled" in error for error in query_report["errors"])

    # Updating raw and projected metric artifacts together still cannot replace a
    # metric that the validator recomputes from response content and frozen labels.
    metric_tampered = json.loads(json.dumps(original_observations))
    changed_metric = next(row for row in metric_tampered if row["outcome"] == "success")
    changed_metric["metrics"]["facet"]["present_macro"] = 0.123
    _write_jsonl(raw_path, metric_tampered)
    refresh_artifact("raw_observations", raw_path, len(metric_tampered))
    metric_path = release_dir / "per_query_metrics.jsonl"
    projected_rows = [
        json.loads(line) for line in metric_path.read_text(encoding="utf-8").splitlines()
    ]
    projected = next(row for row in projected_rows if row["call_id"] == changed_metric["call_id"])
    projected["facet_present_macro"] = 0.123
    _write_jsonl(metric_path, projected_rows)
    refresh_artifact("per_query_metrics", metric_path, len(projected_rows))
    _write_json(release_dir / "run_manifest.json", manifest)
    metric_report = validate_release_directory(release_dir)
    assert metric_report["status"] == "NO-GO"
    assert any(
        "metrics differ from raw-derived metrics" in error for error in metric_report["errors"]
    )

    # Result identity, uniqueness, and access state must match the frozen corpus.
    dataset_tampered = json.loads(json.dumps(original_observations))
    changed_dataset = next(row for row in dataset_tampered if row["outcome"] == "success")
    changed_result = changed_dataset["response"]["results"][0]
    changed_result["source_id"] = "WRONG-ACCESSION"
    changed_result["access_type"] = "controlled"
    changed_dataset["response"]["results"].append(json.loads(json.dumps(changed_result)))
    _write_jsonl(raw_path, dataset_tampered)
    refresh_artifact("raw_observations", raw_path, len(dataset_tampered))
    _write_jsonl(
        metric_path,
        [
            json.loads(line)
            for line in (release_dir / "per_query_metrics.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ],
    )
    _write_json(release_dir / "run_manifest.json", manifest)
    dataset_report = validate_release_directory(release_dir)
    assert dataset_report["status"] == "NO-GO"
    assert any("source/accession does not match" in error for error in dataset_report["errors"])
    assert any("duplicate dataset_id" in error for error in dataset_report["errors"])
    assert any("violates open_only" in error for error in dataset_report["errors"])

    # Restore raw and projected evidence before testing aggregate and key tampering.
    _write_jsonl(raw_path, original_observations)
    refresh_artifact("raw_observations", raw_path, len(original_observations))
    clean_projected = [
        {
            "schema_version": "omicsplorer-hard-query-metric-v1",
            "ordinal": row["ordinal"],
            "call_id": row["call_id"],
            **row["key"],
            "outcome": row["outcome"],
            "metric_eligible": bool(row["metrics"].get("eligible")),
            "facet_present_macro": row["metrics"].get("facet", {}).get("present_macro"),
            "facet_conjunctive_macro": row["metrics"].get("facet", {}).get("conjunctive_macro"),
            "exclusion_applicable": row["metrics"].get("exclusion", {}).get("applicable"),
            "exclusion_eligible": row["metrics"].get("exclusion", {}).get("eligible"),
            "exclusion_clean_at_k": row["metrics"].get("exclusion", {}).get("clean_at_k"),
            "returned_count": row["returned_count"],
            "scored_count": row["scored_count"],
        }
        for row in original_observations
    ]
    _write_jsonl(metric_path, clean_projected)
    refresh_artifact("per_query_metrics", metric_path, len(clean_projected))

    aggregate_path = release_dir / "aggregate_metrics.csv"
    with aggregate_path.open(encoding="utf-8") as handle:
        aggregate_rows = list(csv.DictReader(handle))
    aggregate_rows[0]["mean"] = "nan"
    with aggregate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate_rows[0]))
        writer.writeheader()
        writer.writerows(aggregate_rows)
    refresh_artifact("aggregate_metrics", aggregate_path, len(aggregate_rows))
    _write_json(release_dir / "run_manifest.json", manifest)
    aggregate_report = validate_release_directory(release_dir)
    assert aggregate_report["status"] == "NO-GO"
    assert any("non-finite numeric mean" in error for error in aggregate_report["errors"])

    # Even if an edited manifest is made internally self-consistent, a duplicated
    # scheduled tuple must not pass the offline validator.
    first_success = next(row for row in observations if row["outcome"] == "success")
    with raw_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first_success, ensure_ascii=False, sort_keys=True) + "\n")
    manifest["counts"]["expected"] = 393
    manifest["counts"]["attempted"] = 393
    manifest["counts"]["success"] = 385
    raw_descriptor = next(
        item for item in manifest["artifacts"] if item["role"] == "raw_observations"
    )
    raw_descriptor["sha256"] = _sha(raw_path)
    raw_descriptor["bytes"] = raw_path.stat().st_size
    raw_descriptor["record_count"] = 393
    _write_json(release_dir / "run_manifest.json", manifest)
    tampered = validate_release_directory(release_dir)
    assert tampered["status"] == "NO-GO"
    assert any("duplicate (qid, lang, mode)" in error for error in tampered["errors"])
