"""Offline contracts and integrity checks for a submission evaluation release.

This module never contacts OmicsPlorer or any external service.  A collection
runner supplies the observations; this module records the immutable inputs and
decides whether the resulting directory is technically eligible to support a
manuscript claim.

The contract is intentionally stricter than the historical evaluation scripts:

* a failed request is not an empty result set;
* document and query embeddings must use the same immutable vector-space model;
  any model-defined role-specific prefixes are recorded separately;
* every input and output is named by a relative path and SHA-256 digest; and
* a dirty Git tree, missing observation, hidden failure, or arm fallback makes
  a run submission-ineligible; transparently retained request failures remain
  reportable evidence rather than being selected away.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from genofinder_eval.external.provenance import (
    git_binary,
    git_value,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json,
)
from genofinder_eval.metrics.exclusion import exclusion_satisfaction_at_k
from genofinder_eval.metrics.facet_hard import facet_satisfaction_hard_at_k

CONFIG_SCHEMA_VERSION = "omicsplorer-frozen-eval-config-v1"
RUN_SCHEMA_VERSION = "omicsplorer-frozen-eval-run-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDERS = {
    "",
    "required",
    "todo",
    "tbd",
    "unknown",
    "replace_me",
    "review_required",
    "placeholder",
}
_SECRET_KEY_PARTS = ("password", "bearer", "api_key", "secret", "private_key")
_GPB_PROTOCOL_ID = "gpb-application-note-hard-facet-v1"
_GPB_PROTOCOL_CONTRACT: dict[str, Any] = {
    "query_sets": ["hard_queries"],
    "languages": ["en", "ko"],
    "modes": ["bm25_only", "dense_only", "rrf", "rrf_rerank"],
    "top_k": 20,
    "score_k": 10,
    "seed": 42,
    "timeout_s": 180.0,
    "warmup": "unscored_recorded",
    "failure_policy": "report_separately_no_imputation",
    "expected_query_count": 49,
    "primary_metrics": ["facet_present_macro", "facet_conjunctive_macro"],
}
_GPB_RETRIEVAL_CONTRACT: dict[str, Any] = {
    "corpus": "production",
    "lexical_candidate_count": 200,
    "dense_candidate_count": 200,
    "rrf_k": 60,
    "reranker_top_n": 20,
    "access_preference": "open_only",
    "auto_translate": True,
    "query_understanding_enabled": False,
    "effective_trace_required": True,
    "accession_shortcut_enabled": True,
    "cardinality_boost_enabled": True,
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CorpusConfig(_StrictModel):
    snapshot_id: str
    cutoff_utc: str
    accession_manifest_path: str
    accession_manifest_sha256: str
    stores_manifest_path: str
    stores_manifest_sha256: str
    row_count: int = Field(ge=1)
    deduplication_rule: str
    database_snapshot_id: str
    qdrant_snapshot_id: str
    opensearch_snapshot_id: str
    schema_revision: str


class MetadataStructuringConfig(_StrictModel):
    lineage_manifest_path: str
    lineage_manifest_sha256: str
    row_lineage_field: Literal["extraction_lineage_id"]
    row_extraction_version_field: Literal["extraction_version"]
    row_build_stage_field: Literal["build_stage"]
    mixed_history_policy: str


class EmbeddingConfig(_StrictModel):
    checkpoint: str
    revision: str
    digest_sha256: str
    quantization: str
    serving_engine: str
    instruction_prefix: str
    pooling: str
    truncation_dimension: int = Field(ge=1)


class AuxiliaryModelConfig(_StrictModel):
    checkpoint: str
    revision: str
    digest_sha256: str
    quantization: str
    serving_engine: str
    prompt_path: str
    prompt_sha256: str
    options_path: str
    options_sha256: str
    cache_policy: str


class ModelConfig(_StrictModel):
    metadata_structuring: MetadataStructuringConfig
    corpus_embedding: EmbeddingConfig
    query_embedding: EmbeddingConfig
    reranker_checkpoint: str
    reranker_revision: str
    reranker_digest_sha256: str
    reranker_quantization: str
    query_understanding: AuxiliaryModelConfig | None = None
    translation: AuxiliaryModelConfig | None = None


class RetrievalConfig(_StrictModel):
    corpus: Literal["production", "biocaddie_2016_eval"]
    lexical_index: str
    dense_collection: str
    lexical_candidate_count: int = Field(ge=1)
    dense_candidate_count: int = Field(ge=1)
    rrf_k: int = Field(ge=1)
    reranker_top_n: int = Field(ge=0)
    access_preference: Literal["any", "open_only"]
    auto_translate: bool
    query_understanding_enabled: bool
    effective_trace_required: bool
    effective_configuration_path: str
    effective_configuration_sha256: str
    fallback_policy: str
    accession_shortcut_enabled: bool
    cardinality_boost_enabled: bool


class EvaluationConfig(_StrictModel):
    query_sets: list[str]
    languages: list[Literal["en", "ko"]]
    modes: list[Literal["bm25_only", "dense_only", "rrf", "rrf_rerank"]]
    top_k: int = Field(ge=1, le=100)
    score_k: int = Field(ge=1)
    seed: int
    timeout_s: float = Field(gt=0)
    warmup: Literal["none", "unscored_recorded"]
    primary_metrics: list[str]
    failure_policy: Literal["report_separately_no_imputation", "zero_utility"]
    expected_query_count: int = Field(ge=1)


class RuntimeConfig(_StrictModel):
    dependency_lock_path: str
    dependency_lock_sha256: str
    container_image_digest: str
    hardware: str


class EffectiveRerankerEvidence(_StrictModel):
    checkpoint: str
    revision: str
    digest_sha256: str
    quantization: str
    top_n: int = Field(ge=0)


class EffectiveAuxiliaryEvidence(_StrictModel):
    enabled: bool
    model: AuxiliaryModelConfig | None


class EffectiveServerConfig(_StrictModel):
    """Canonical, deployed retrieval settings bound to every evaluation trace."""

    schema_version: Literal["omicsplorer-effective-server-config-v1"]
    corpus: Literal["production", "biocaddie_2016_eval"]
    lexical_index: str
    dense_collection: str
    lexical_candidate_count: int = Field(ge=1)
    dense_candidate_count: int = Field(ge=1)
    rrf_k: int = Field(ge=1)
    corpus_embedding: EmbeddingConfig
    query_embedding: EmbeddingConfig
    reranker: EffectiveRerankerEvidence
    translation: EffectiveAuxiliaryEvidence
    query_understanding: EffectiveAuxiliaryEvidence
    access_preference: Literal["any", "open_only"]
    fallback_policy: str
    accession_shortcut_enabled: bool
    cardinality_boost_enabled: bool
    container_image_digest: str


class FrozenEvalConfig(_StrictModel):
    schema_version: Literal["omicsplorer-frozen-eval-config-v1"]
    release_id: str
    protocol_id: str
    protocol_path: str
    protocol_sha256: str
    corpus: CorpusConfig
    models: ModelConfig
    retrieval: RetrievalConfig
    evaluation: EvaluationConfig
    runtime: RuntimeConfig


class DatabaseStoreEvidence(_StrictModel):
    snapshot_id: str
    row_count: int = Field(ge=1)
    accession_membership_count: int = Field(ge=1)
    dataset_id_set_sha256: str
    schema_revision: str


class QdrantStoreEvidence(_StrictModel):
    snapshot_id: str
    point_count: int = Field(ge=1)
    dataset_id_set_sha256: str
    collection_config_sha256: str


class OpenSearchStoreEvidence(_StrictModel):
    snapshot_id: str
    document_count: int = Field(ge=1)
    dataset_id_set_sha256: str
    mapping_sha256: str
    settings_sha256: str


class StoresManifest(_StrictModel):
    schema_version: Literal["omicsplorer-store-evidence-v1"]
    captured_at_utc: str
    database: DatabaseStoreEvidence
    qdrant: QdrantStoreEvidence
    opensearch: OpenSearchStoreEvidence
    cross_store_mismatch_count: int = Field(ge=0)


class StructuringLineage(_StrictModel):
    lineage_id: str
    extractor_kind: Literal["local_model", "non_model"]
    checkpoint: str | None
    revision: str | None
    weight_digest_sha256: str | None
    quantization: str | None
    serving_engine: str | None
    prompt_path: str | None
    prompt_sha256: str | None
    schema_path: str | None
    schema_sha256: str | None
    options_path: str | None
    options_sha256: str | None
    deterministic_postprocessing_revision: str
    limitations: str


class StructuringLineageManifest(_StrictModel):
    schema_version: Literal["omicsplorer-structuring-lineages-v1"]
    mixed_history_note: str
    lineages: list[StructuringLineage]


class FrozenConfigError(ValueError):
    """The author-supplied release configuration is incomplete or inconsistent."""


def _iter_values(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_iter_values(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_iter_values(item, f"{prefix}[{index}]"))
    else:
        rows.append((prefix, value))
    return rows


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower().strip("<>").strip()
    return normalized in _PLACEHOLDERS or bool(
        re.match(r"^(required|todo|tbd|placeholder)(?:[_:\s-]|$)", normalized)
    )


def _asset_placeholder_issues(path: Path, *, label: str) -> list[str]:
    """Reject renamed templates whose unresolved markers were merely re-hashed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read {label} for placeholder scan: {exc}"]
    issues: list[str] = []
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return [f"invalid JSON in {label}: {exc}"]

        def scan(value: Any, prefix: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    key_text = str(key)
                    child = f"{prefix}.{key_text}" if prefix else key_text
                    if _is_placeholder(key_text):
                        issues.append(f"unresolved placeholder key in {label}: {child}")
                    scan(item, child)
            elif isinstance(value, list):
                for item_index, item in enumerate(value):
                    scan(item, f"{prefix}[{item_index}]")
            elif isinstance(value, str) and _is_placeholder(value):
                issues.append(f"unresolved placeholder value in {label}: {prefix}")

        scan(parsed)
    else:
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _is_placeholder(line):
                issues.append(f"unresolved placeholder text in {label} at line {line_number}")
    return issues


def _json_exact_equal(left: Any, right: Any) -> bool:
    """Compare JSON-like values without Python's bool == int coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_exact_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_exact_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float):
        return math.isfinite(left) and math.isfinite(right) and left == right
    return bool(left == right)


def _validate_relative_file(
    *, config_path: Path, relative_path: str, expected_sha256: str, label: str
) -> list[str]:
    errors: list[str] = []
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return [f"{label} must be a relative path without '..': {relative_path!r}"]
    resolved = (config_path.parent / candidate).resolve()
    if not resolved.is_file():
        return [f"{label} does not exist: {relative_path!r}"]
    actual = sha256_file(resolved)
    if actual != expected_sha256:
        errors.append(f"{label} SHA-256 mismatch: expected {expected_sha256}, observed {actual}")
    return errors


def _canonical_set_sha256(values: set[str]) -> str:
    """Hash a set as sorted UTF-8 lines with one trailing newline."""
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    """Hash JSON after deterministic UTF-8 key ordering and compact encoding."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _expected_effective_server_config(config: FrozenEvalConfig) -> EffectiveServerConfig:
    return EffectiveServerConfig(
        schema_version="omicsplorer-effective-server-config-v1",
        corpus=config.retrieval.corpus,
        lexical_index=config.retrieval.lexical_index,
        dense_collection=config.retrieval.dense_collection,
        lexical_candidate_count=config.retrieval.lexical_candidate_count,
        dense_candidate_count=config.retrieval.dense_candidate_count,
        rrf_k=config.retrieval.rrf_k,
        corpus_embedding=config.models.corpus_embedding,
        query_embedding=config.models.query_embedding,
        reranker=EffectiveRerankerEvidence(
            checkpoint=config.models.reranker_checkpoint,
            revision=config.models.reranker_revision,
            digest_sha256=config.models.reranker_digest_sha256,
            quantization=config.models.reranker_quantization,
            top_n=config.retrieval.reranker_top_n,
        ),
        translation=EffectiveAuxiliaryEvidence(
            enabled=config.retrieval.auto_translate,
            model=config.models.translation,
        ),
        query_understanding=EffectiveAuxiliaryEvidence(
            enabled=config.retrieval.query_understanding_enabled,
            model=config.models.query_understanding,
        ),
        access_preference=config.retrieval.access_preference,
        fallback_policy=config.retrieval.fallback_policy,
        accession_shortcut_enabled=config.retrieval.accession_shortcut_enabled,
        cardinality_boost_enabled=config.retrieval.cardinality_boost_enabled,
        container_image_digest=config.runtime.container_image_digest,
    )


def _read_effective_server_config(
    path: Path,
    *,
    config: FrozenEvalConfig,
) -> tuple[EffectiveServerConfig | None, list[str]]:
    errors: list[str] = []
    try:
        effective = EffectiveServerConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"invalid effective server configuration: {exc}"]

    dumped = effective.model_dump(mode="json")
    for value_path, value in _iter_values(dumped):
        if isinstance(value, str) and _is_placeholder(value):
            errors.append(
                f"placeholder value is not allowed in effective server configuration: {value_path}"
            )
        leaf = value_path.rsplit(".", 1)[-1].lower()
        if any(part in leaf for part in _SECRET_KEY_PARTS):
            errors.append(
                "secret-bearing field is not allowed in effective server configuration: "
                f"{value_path}"
            )
        if value_path.endswith("sha256") and value is not None:
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                errors.append(
                    "full lowercase SHA-256 required in effective server configuration: "
                    f"{value_path}"
                )

    actual_digest = _canonical_json_sha256(dumped)
    if actual_digest != config.retrieval.effective_configuration_sha256:
        errors.append(
            "canonical effective server configuration SHA-256 differs from "
            "retrieval.effective_configuration_sha256"
        )

    expected = _expected_effective_server_config(config).model_dump(mode="json")
    observed_values = dict(_iter_values(dumped))
    expected_values = dict(_iter_values(expected))
    mismatched = sorted(
        path_name
        for path_name in expected_values.keys() | observed_values.keys()
        if expected_values.get(path_name) != observed_values.get(path_name)
    )
    if mismatched:
        errors.append(
            "effective server configuration differs from frozen config at: " + ", ".join(mismatched)
        )
    return effective, errors


def _metadata_asset_label(lineage_id: str, role: str) -> str:
    return f"metadata_structuring_{lineage_id}_{role}"


def _read_structuring_lineages(
    path: Path,
    *,
    verify_assets: bool,
) -> tuple[
    StructuringLineageManifest | None,
    dict[str, tuple[str, str]],
    list[str],
]:
    errors: list[str] = []
    expected_assets: dict[str, tuple[str, str]] = {}
    try:
        manifest = StructuringLineageManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, {}, [f"invalid metadata-structuring lineage manifest: {exc}"]

    dumped = manifest.model_dump(mode="json")
    for value_path, value in _iter_values(dumped):
        if isinstance(value, str) and _is_placeholder(value):
            errors.append(f"placeholder value is not allowed in structuring lineage: {value_path}")
        leaf = value_path.rsplit(".", 1)[-1].lower()
        if any(part in leaf for part in _SECRET_KEY_PARTS):
            errors.append(
                f"secret-bearing field is not allowed in structuring lineage: {value_path}"
            )

    if not manifest.lineages:
        errors.append("metadata-structuring lineage manifest is empty")
    lineage_ids = [lineage.lineage_id for lineage in manifest.lineages]
    if len(lineage_ids) != len(set(lineage_ids)):
        errors.append("metadata-structuring lineage IDs are duplicated")

    model_fields = (
        "checkpoint",
        "revision",
        "weight_digest_sha256",
        "quantization",
        "serving_engine",
        "prompt_path",
        "prompt_sha256",
        "schema_path",
        "schema_sha256",
        "options_path",
        "options_sha256",
    )
    for lineage in manifest.lineages:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", lineage.lineage_id):
            errors.append(f"unsafe metadata-structuring lineage_id: {lineage.lineage_id!r}")
            continue
        values = lineage.model_dump()
        if lineage.extractor_kind == "local_model":
            missing = [field for field in model_fields if values.get(field) is None]
            if missing:
                errors.append(
                    f"local-model lineage {lineage.lineage_id!r} is incomplete: {missing}"
                )
                continue
            for hash_field in (
                "weight_digest_sha256",
                "prompt_sha256",
                "schema_sha256",
                "options_sha256",
            ):
                digest = values[hash_field]
                if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                    errors.append(
                        f"full lowercase SHA-256 required for lineage "
                        f"{lineage.lineage_id!r} field {hash_field}"
                    )
            for role in ("prompt", "schema", "options"):
                relative = values[f"{role}_path"]
                digest = values[f"{role}_sha256"]
                if not isinstance(relative, str) or not isinstance(digest, str):
                    continue
                candidate = Path(relative)
                if candidate.is_absolute() or ".." in candidate.parts:
                    errors.append(f"unsafe {role} path for lineage {lineage.lineage_id!r}")
                    continue
                label = _metadata_asset_label(lineage.lineage_id, role)
                expected_assets[label] = (relative, digest)
                if verify_assets:
                    resolved = (path.parent / candidate).resolve()
                    if not resolved.is_file():
                        errors.append(
                            f"metadata-structuring {role} is missing for lineage "
                            f"{lineage.lineage_id!r}: {relative}"
                        )
                    elif sha256_file(resolved) != digest:
                        errors.append(
                            f"metadata-structuring {role} SHA-256 mismatch for lineage "
                            f"{lineage.lineage_id!r}"
                        )
                    else:
                        errors.extend(_asset_placeholder_issues(resolved, label=label))
        elif any(values.get(field) is not None for field in model_fields):
            errors.append(
                f"non-model lineage {lineage.lineage_id!r} must use explicit null for "
                "all model, prompt, schema, and options fields"
            )
    return manifest, expected_assets, errors


def _read_accession_evidence(
    path: Path,
    *,
    config: FrozenEvalConfig,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    expected_fields = [
        "source_db",
        "accession",
        "internal_dataset_id",
        "snapshot_id",
        "extraction_version",
        "extraction_lineage_id",
        "build_stage",
    ]
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != expected_fields:
                return None, [
                    "corpus accession manifest must have the exact columns and order: "
                    + ", ".join(expected_fields)
                ]
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        return None, [f"invalid corpus accession manifest: {exc}"]

    if not rows:
        errors.append("corpus accession manifest is empty")
    membership_keys: list[tuple[str, str, str, str]] = []
    response_memberships: set[tuple[str, str, str]] = set()
    dataset_ids: set[str] = set()
    lineage_ids: set[str] = set()
    per_dataset_lineage: dict[str, tuple[str, str, str]] = {}
    accession_to_dataset: dict[tuple[str, str], str] = {}
    for row_number, row in enumerate(rows, start=2):
        values = {field: str(row.get(field) or "").strip() for field in expected_fields}
        blank = [field for field, value in values.items() if not value]
        if blank:
            errors.append(f"corpus accession manifest row {row_number} has blank fields: {blank}")
            continue
        placeholders = [field for field, value in values.items() if _is_placeholder(value)]
        if placeholders:
            errors.append(
                f"corpus accession manifest row {row_number} has placeholder fields: {placeholders}"
            )
            continue
        source_accession = (values["source_db"], values["accession"])
        dataset_id = values["internal_dataset_id"]
        previous_dataset = accession_to_dataset.setdefault(source_accession, dataset_id)
        if previous_dataset != dataset_id:
            errors.append(
                f"one source/accession maps to multiple internal datasets: {source_accession!r}"
            )
        snapshot_id = values["snapshot_id"]
        lineage_id = values["extraction_lineage_id"]
        membership_keys.append(
            (
                values["source_db"],
                values["accession"],
                dataset_id,
                snapshot_id,
            )
        )
        response_memberships.add((dataset_id, values["source_db"], values["accession"]))
        if snapshot_id != config.corpus.snapshot_id:
            errors.append(
                f"corpus accession manifest row {row_number} snapshot_id differs from config"
            )
        dataset_ids.add(dataset_id)
        lineage_ids.add(lineage_id)
        lineage_tuple = (
            values["extraction_version"],
            lineage_id,
            values["build_stage"],
        )
        previous = per_dataset_lineage.setdefault(dataset_id, lineage_tuple)
        if previous != lineage_tuple:
            errors.append(f"conflicting extraction lineage for internal dataset {dataset_id!r}")
    if len(membership_keys) != len(set(membership_keys)):
        errors.append("duplicate source/accession/internal-dataset membership")
    if len(dataset_ids) != config.corpus.row_count:
        errors.append(
            "config corpus.row_count differs from unique internal_dataset_id count: "
            f"{config.corpus.row_count} != {len(dataset_ids)}"
        )
    return {
        "membership_count": len(rows),
        "dataset_ids": dataset_ids,
        "response_memberships": response_memberships,
        "dataset_id_set_sha256": _canonical_set_sha256(dataset_ids),
        "lineage_ids": lineage_ids,
    }, errors


def _read_store_evidence(path: Path) -> tuple[StoresManifest | None, list[str]]:
    errors: list[str] = []
    try:
        stores = StoresManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"invalid stores manifest: {exc}"]
    dumped = stores.model_dump(mode="json")
    for value_path, value in _iter_values(dumped):
        if isinstance(value, str) and _is_placeholder(value):
            errors.append(f"placeholder value is not allowed in stores manifest: {value_path}")
        if value_path.endswith("sha256") and (
            not isinstance(value, str) or not _SHA256_RE.fullmatch(value)
        ):
            errors.append(f"full lowercase SHA-256 required in stores manifest: {value_path}")
    try:
        captured = stores.captured_at_utc.replace("Z", "+00:00")
        parsed = __import__("datetime").datetime.fromisoformat(captured)
        if parsed.tzinfo is None:
            errors.append("stores captured_at_utc must include a UTC offset")
    except ValueError:
        errors.append("stores captured_at_utc must be an ISO-8601 timestamp")
    return stores, errors


def _cross_validate_corpus_evidence(
    *,
    config: FrozenEvalConfig,
    accessions: dict[str, Any] | None,
    stores: StoresManifest | None,
    lineages: StructuringLineageManifest | None,
) -> list[str]:
    errors: list[str] = []
    if accessions is None or stores is None or lineages is None:
        return errors
    declared_lineages = {lineage.lineage_id for lineage in lineages.lineages}
    observed_lineages = set(accessions["lineage_ids"])
    if observed_lineages != declared_lineages:
        errors.append(
            "accession extraction_lineage_id set differs from structuring lineage manifest"
        )

    expected_hash = str(accessions["dataset_id_set_sha256"])
    expected_rows = config.corpus.row_count
    expected_memberships = int(accessions["membership_count"])
    if stores.database.snapshot_id != config.corpus.database_snapshot_id:
        errors.append("database snapshot_id differs between config and stores manifest")
    if stores.qdrant.snapshot_id != config.corpus.qdrant_snapshot_id:
        errors.append("Qdrant snapshot_id differs between config and stores manifest")
    if stores.opensearch.snapshot_id != config.corpus.opensearch_snapshot_id:
        errors.append("OpenSearch snapshot_id differs between config and stores manifest")
    if stores.database.schema_revision != config.corpus.schema_revision:
        errors.append("database schema revision differs between config and stores manifest")
    if stores.database.row_count != expected_rows:
        errors.append("database row_count differs from frozen corpus row_count")
    if stores.database.accession_membership_count != expected_memberships:
        errors.append("database accession_membership_count differs from accession manifest rows")
    if stores.qdrant.point_count != expected_rows:
        errors.append("Qdrant point_count differs from frozen corpus row_count")
    if stores.opensearch.document_count != expected_rows:
        errors.append("OpenSearch document_count differs from frozen corpus row_count")
    for name, observed_hash in (
        ("database", stores.database.dataset_id_set_sha256),
        ("Qdrant", stores.qdrant.dataset_id_set_sha256),
        ("OpenSearch", stores.opensearch.dataset_id_set_sha256),
    ):
        if observed_hash != expected_hash:
            errors.append(f"{name} dataset_id_set_sha256 differs from accession manifest")
    if stores.cross_store_mismatch_count != 0:
        errors.append("cross_store_mismatch_count must be zero for a release run")
    return errors


def _validate_protocol_contract(config: FrozenEvalConfig) -> list[str]:
    if config.protocol_id != _GPB_PROTOCOL_ID:
        return [
            f"unsupported submission protocol_id {config.protocol_id!r}; "
            f"expected {_GPB_PROTOCOL_ID!r}"
        ]
    observed = config.evaluation.model_dump(mode="json")
    errors: list[str] = []
    for field, expected in _GPB_PROTOCOL_CONTRACT.items():
        if observed.get(field) != expected:
            errors.append(
                f"evaluation.{field} differs from machine-readable protocol contract: "
                f"{observed.get(field)!r} != {expected!r}"
            )
    retrieval = config.retrieval.model_dump(mode="json")
    for field, expected in _GPB_RETRIEVAL_CONTRACT.items():
        if retrieval.get(field) != expected:
            errors.append(
                f"retrieval.{field} differs from machine-readable protocol contract: "
                f"{retrieval.get(field)!r} != {expected!r}"
            )
    return errors


def frozen_response_path_issues(
    *,
    config: FrozenEvalConfig,
    mode: str,
    lang: str,
    query_text: str,
    response: dict[str, Any],
) -> list[str]:
    """Fail-closed checks for the effective retrieval path of one response."""
    errors: list[str] = []
    results = response.get("results")
    if not isinstance(results, list):
        errors.append("response results is not a list")
        results = []
    if len(results) > config.evaluation.top_k:
        errors.append("response returned more results than the frozen evaluation.top_k")
    breakdowns: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            errors.append(f"result {index} is not an object")
            continue
        top_level_score = result.get("score")
        if (
            not isinstance(top_level_score, (int, float))
            or isinstance(top_level_score, bool)
            or not math.isfinite(float(top_level_score))
        ):
            errors.append(f"result {index} has a non-finite or nonnumeric top-level score")
        breakdown = result.get("score_breakdown")
        if not isinstance(breakdown, dict):
            errors.append(f"result {index} lacks score_breakdown")
            continue
        breakdowns.append(breakdown)
        for score_name in ("semantic", "lexical", "rrf", "rerank"):
            score = breakdown.get(score_name)
            if score is not None and (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(float(score))
            ):
                errors.append(f"result {index} has a non-finite or nonnumeric {score_name} score")

    if mode == "bm25_only":
        if breakdowns and any(item.get("lexical") is None for item in breakdowns):
            errors.append("bm25-based response lacks lexical scores")
        if any(item.get("semantic") is not None for item in breakdowns):
            errors.append("bm25-based response contains semantic scores")
        if any(item.get("rerank") is not None for item in breakdowns):
            errors.append("bm25-based response contains reranker scores")
    elif mode == "dense_only":
        if breakdowns and any(item.get("semantic") is None for item in breakdowns):
            errors.append("dense-based response lacks semantic scores")
        if any(item.get("lexical") is not None for item in breakdowns):
            errors.append("dense-based response contains lexical scores")
        if any(item.get("rerank") is not None for item in breakdowns):
            errors.append("dense-based response contains reranker scores")
    elif mode == "rrf":
        if breakdowns and any(item.get("rrf") is None for item in breakdowns):
            errors.append("RRF response lacks fusion scores")
        if any(item.get("rerank") is not None for item in breakdowns):
            errors.append("RRF response contains reranker scores")
    elif mode == "rrf_rerank":
        expected_reranked = min(config.retrieval.reranker_top_n, len(results))
        for index, result in enumerate(results[:expected_reranked], start=1):
            if not isinstance(result, dict):
                continue
            breakdown = result.get("score_breakdown")
            if not isinstance(breakdown, dict):
                continue
            if breakdown.get("rrf") is None:
                errors.append(f"reranked response result {index} lacks its base RRF score")
            if breakdown.get("rerank") is None:
                errors.append(f"reranked response result {index} lacks a reranker score")
    else:
        errors.append(f"unknown requested mode in response validation: {mode!r}")

    trace = response.get("evaluation_trace")
    if not isinstance(trace, dict):
        return [*errors, "service response lacks an object evaluation_trace"]
    if trace.get("requested_mode") != mode:
        errors.append("evaluation_trace.requested_mode mismatch")
    if trace.get("effective_mode") != mode:
        errors.append("evaluation_trace.effective_mode mismatch")
    if trace.get("configuration_sha256") != (config.retrieval.effective_configuration_sha256):
        errors.append("evaluation_trace.configuration_sha256 mismatch")
    fallbacks = trace.get("fallbacks")
    if not isinstance(fallbacks, list):
        errors.append("evaluation_trace.fallbacks is missing")
    elif fallbacks:
        errors.append(f"evaluation arm fallback recorded: {fallbacks}")

    components = trace.get("components")
    required_components = {
        "lexical",
        "dense",
        "reranker",
        "translation",
        "query_understanding",
        "accession_shortcut",
        "cardinality_boost",
    }
    if not isinstance(components, dict) or not required_components.issubset(components):
        return [*errors, "evaluation_trace.components is incomplete"]
    primary_by_mode = {
        "bm25_only": ("used", "not_requested", "not_requested"),
        "dense_only": ("not_requested", "used", "not_requested"),
        "rrf": ("used", "used", "not_requested"),
        "rrf_rerank": ("used", "used", "used"),
    }
    expected_primary = primary_by_mode.get(mode)
    if expected_primary is not None:
        for name, expected_state in zip(
            ("lexical", "dense", "reranker"), expected_primary, strict=True
        ):
            if components.get(name) != expected_state:
                errors.append(
                    f"evaluation_trace.components.{name}={components.get(name)!r}; "
                    f"expected {expected_state!r}"
                )

    translation_expected = bool(
        config.retrieval.auto_translate
        and lang == "ko"
        and any(ord(character) > 127 for character in query_text)
    )
    expected_translation = (
        "used"
        if translation_expected
        else "not_needed"
        if config.retrieval.auto_translate
        else "disabled"
    )
    if components.get("translation") != expected_translation:
        errors.append(
            "evaluation_trace.components.translation differs from the requested "
            f"language/configuration: {components.get('translation')!r} != "
            f"{expected_translation!r}"
        )
    translated_query = response.get("translated_query")
    if translation_expected:
        if not isinstance(translated_query, str) or not translated_query.strip():
            errors.append("translation was marked used but translated_query is missing")
        elif translated_query == query_text:
            errors.append("translation was marked used but translated_query echoes query_text")
    elif isinstance(translated_query, str) and translated_query.strip():
        errors.append("translated_query is present when translation was not expected")
    expected_qu = "used" if config.retrieval.query_understanding_enabled else "disabled"
    if components.get("query_understanding") != expected_qu:
        errors.append(
            "evaluation_trace.components.query_understanding differs from config: "
            f"{components.get('query_understanding')!r} != {expected_qu!r}"
        )

    shortcut = components.get("accession_shortcut")
    if not isinstance(shortcut, dict):
        errors.append("evaluation_trace.components.accession_shortcut is not an object")
    else:
        if shortcut.get("enabled") is not config.retrieval.accession_shortcut_enabled:
            errors.append("accession-shortcut enabled state differs from config")
        if not isinstance(shortcut.get("applied"), bool):
            errors.append("accession-shortcut applied state is not boolean")
        elif shortcut.get("applied"):
            errors.append("accession shortcut was applied inside the hard-query mode comparison")

    cardinality = components.get("cardinality_boost")
    if not isinstance(cardinality, dict):
        errors.append("evaluation_trace.components.cardinality_boost is not an object")
    else:
        if cardinality.get("enabled") is not config.retrieval.cardinality_boost_enabled:
            errors.append("cardinality-boost enabled state differs from config")
        if not isinstance(cardinality.get("applied"), bool):
            errors.append("cardinality-boost applied state is not boolean")
    return errors


def validate_frozen_config(
    config: FrozenEvalConfig,
    *,
    config_path: Path,
    set_name: str | None = None,
    languages: list[str] | None = None,
    modes: list[str] | None = None,
    top_k: int | None = None,
    score_k: int | None = None,
    seed: int | None = None,
    verify_referenced_files: bool = True,
) -> list[str]:
    """Return all strict-validation errors without performing network access."""
    errors: list[str] = []
    dumped = config.model_dump(mode="json")

    for path, value in _iter_values(dumped):
        if isinstance(value, str) and _is_placeholder(value):
            errors.append(f"placeholder value is not allowed at {path}")
        key = path.rsplit(".", 1)[-1].lower()
        if any(part in key for part in _SECRET_KEY_PARTS):
            errors.append(f"secret-bearing field is not allowed in a release config: {path}")
        if key.endswith("_path") and isinstance(value, str):
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                errors.append(f"path must be relative and may not contain '..': {path}")

    for path, value in _iter_values(dumped):
        if path.endswith("sha256") and value is not None:
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                errors.append(f"full lowercase SHA-256 required at {path}")

    corpus_embedding = config.models.corpus_embedding.model_dump()
    query_embedding = config.models.query_embedding.model_dump()
    # Some retrieval models prescribe different document/query role prefixes.  Those
    # prefixes must be recorded, but they need not be textually identical.  Everything
    # defining the shared vector space and numerical encoding must match.
    comparable_fields = set(corpus_embedding) - {"instruction_prefix"}
    mismatched = sorted(
        field for field in comparable_fields if corpus_embedding[field] != query_embedding[field]
    )
    if mismatched:
        errors.append(
            "document/query embedding vector-space settings differ: "
            + ", ".join(mismatched)
            + "; equal dimensionality alone is not sufficient"
        )

    if config.evaluation.score_k > config.evaluation.top_k:
        errors.append("evaluation.score_k may not exceed evaluation.top_k")
    if len(config.evaluation.query_sets) != len(set(config.evaluation.query_sets)):
        errors.append("evaluation.query_sets contains duplicates")
    if len(config.evaluation.languages) != len(set(config.evaluation.languages)):
        errors.append("evaluation.languages contains duplicates")
    if len(config.evaluation.modes) != len(set(config.evaluation.modes)):
        errors.append("evaluation.modes contains duplicates")
    if not config.evaluation.primary_metrics:
        errors.append("evaluation.primary_metrics must be prespecified")
    if not config.retrieval.effective_trace_required:
        errors.append(
            "retrieval.effective_trace_required must be true for a submission run; "
            "static intended settings cannot prove the effective per-request path"
        )

    if config.retrieval.query_understanding_enabled:
        if config.models.query_understanding is None:
            errors.append("enabled query understanding requires a complete model/prompt record")
    if config.retrieval.auto_translate and config.models.translation is None:
        errors.append("enabled auto-translation requires a complete model/prompt record")

    errors.extend(_validate_protocol_contract(config))

    if verify_referenced_files:
        errors.extend(
            _validate_relative_file(
                config_path=config_path,
                relative_path=config.corpus.accession_manifest_path,
                expected_sha256=config.corpus.accession_manifest_sha256,
                label="corpus.accession_manifest_path",
            )
        )
        errors.extend(
            _validate_relative_file(
                config_path=config_path,
                relative_path=config.corpus.stores_manifest_path,
                expected_sha256=config.corpus.stores_manifest_sha256,
                label="corpus.stores_manifest_path",
            )
        )
        errors.extend(
            _validate_relative_file(
                config_path=config_path,
                relative_path=config.models.metadata_structuring.lineage_manifest_path,
                expected_sha256=(config.models.metadata_structuring.lineage_manifest_sha256),
                label="models.metadata_structuring.lineage_manifest_path",
            )
        )
        errors.extend(
            _validate_relative_file(
                config_path=config_path,
                relative_path=config.protocol_path,
                expected_sha256=config.protocol_sha256,
                label="protocol_path",
            )
        )
        errors.extend(
            _validate_relative_file(
                config_path=config_path,
                relative_path=config.runtime.dependency_lock_path,
                expected_sha256=config.runtime.dependency_lock_sha256,
                label="runtime.dependency_lock_path",
            )
        )
        effective_configuration_path = (
            config_path.parent / config.retrieval.effective_configuration_path
        ).resolve()
        if not effective_configuration_path.is_file():
            errors.append(
                "retrieval.effective_configuration_path does not exist: "
                f"{config.retrieval.effective_configuration_path!r}"
            )
        else:
            _effective, evidence_errors = _read_effective_server_config(
                effective_configuration_path,
                config=config,
            )
            errors.extend(evidence_errors)
        for label, auxiliary in (
            ("models.query_understanding", config.models.query_understanding),
            ("models.translation", config.models.translation),
        ):
            if auxiliary is None:
                continue
            for role, relative_path, digest in (
                ("prompt", auxiliary.prompt_path, auxiliary.prompt_sha256),
                ("options", auxiliary.options_path, auxiliary.options_sha256),
            ):
                errors.extend(
                    _validate_relative_file(
                        config_path=config_path,
                        relative_path=relative_path,
                        expected_sha256=digest,
                        label=f"{label}.{role}_path",
                    )
                )
                resolved_asset = (config_path.parent / relative_path).resolve()
                if resolved_asset.is_file():
                    errors.extend(
                        _asset_placeholder_issues(
                            resolved_asset,
                            label=f"{label}.{role}",
                        )
                    )

        accession_path = (config_path.parent / config.corpus.accession_manifest_path).resolve()
        stores_path = (config_path.parent / config.corpus.stores_manifest_path).resolve()
        lineages_path = (
            config_path.parent / config.models.metadata_structuring.lineage_manifest_path
        ).resolve()
        accessions: dict[str, Any] | None = None
        stores: StoresManifest | None = None
        lineages: StructuringLineageManifest | None = None
        if accession_path.is_file():
            accessions, evidence_errors = _read_accession_evidence(accession_path, config=config)
            errors.extend(evidence_errors)
        if stores_path.is_file():
            stores, evidence_errors = _read_store_evidence(stores_path)
            errors.extend(evidence_errors)
        if lineages_path.is_file():
            lineages, _expected_assets, evidence_errors = _read_structuring_lineages(
                lineages_path, verify_assets=True
            )
            errors.extend(evidence_errors)
        errors.extend(
            _cross_validate_corpus_evidence(
                config=config,
                accessions=accessions,
                stores=stores,
                lineages=lineages,
            )
        )

    try:
        cutoff = config.corpus.cutoff_utc.replace("Z", "+00:00")
        parsed_cutoff = __import__("datetime").datetime.fromisoformat(cutoff)
        if parsed_cutoff.tzinfo is None:
            errors.append("corpus.cutoff_utc must include a UTC offset")
    except ValueError:
        errors.append("corpus.cutoff_utc must be an ISO-8601 timestamp")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", config.runtime.container_image_digest):
        errors.append("runtime.container_image_digest must be a full sha256:<64 hex> digest")

    if set_name is not None and set_name not in config.evaluation.query_sets:
        errors.append(f"query set {set_name!r} is not prespecified")
    if languages is not None and languages != list(config.evaluation.languages):
        errors.append(
            f"invoked languages {languages!r} do not exactly match prespecified languages "
            f"{list(config.evaluation.languages)!r}"
        )
    if modes is not None and modes != list(config.evaluation.modes):
        errors.append(
            f"invoked modes {modes!r} do not exactly match prespecified modes "
            f"{list(config.evaluation.modes)!r}"
        )
    if top_k is not None and top_k != config.evaluation.top_k:
        errors.append(f"invoked top_k={top_k} differs from prespecified {config.evaluation.top_k}")
    if score_k is not None and score_k != config.evaluation.score_k:
        errors.append(
            f"invoked score_k={score_k} differs from prespecified {config.evaluation.score_k}"
        )
    if seed is not None and seed != config.evaluation.seed:
        errors.append(f"invoked seed={seed} differs from prespecified {config.evaluation.seed}")
    return errors


def load_frozen_config(
    path: Path,
    *,
    set_name: str | None = None,
    languages: list[str] | None = None,
    modes: list[str] | None = None,
    top_k: int | None = None,
    score_k: int | None = None,
    seed: int | None = None,
) -> FrozenEvalConfig:
    try:
        config = FrozenEvalConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FrozenConfigError(f"invalid frozen config {path}: {exc}") from exc
    errors = validate_frozen_config(
        config,
        config_path=path,
        set_name=set_name,
        languages=languages,
        modes=modes,
        top_k=top_k,
        score_k=score_k,
        seed=seed,
    )
    if errors:
        raise FrozenConfigError("frozen config is not release-ready:\n- " + "\n- ".join(errors))
    return config


def file_artifact(path: Path, *, base: Path, record_count: int | None = None) -> dict[str, Any]:
    """Describe an existing artifact without leaking an absolute host path."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(base.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact is outside release directory: {resolved}") from exc
    item: dict[str, Any] = {
        "path": relative,
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }
    if record_count is not None:
        item["record_count"] = record_count
    return item


def new_run_manifest(
    *,
    repo: Path,
    release_dir: Path,
    config_path: Path,
    config: FrozenEvalConfig,
    input_files: dict[str, Path],
    set_name: str,
    expected_observations: int,
) -> dict[str, Any]:
    """Create a running manifest and a normalized copy of the validated config."""
    # Capture provenance before creating an in-repository output directory; otherwise
    # the release's own untracked files would falsely make the starting tree dirty.
    status = git_binary(repo, "status", "--porcelain=v1", "--untracked-files=all")
    diff = git_binary(repo, "diff", "--binary", "HEAD")
    tags_value = git_value(repo, "tag", "--points-at", "HEAD") or ""
    release_dir.mkdir(parents=True, exist_ok=True)
    normalized_config_path = release_dir / "freeze_config.json"
    write_json(normalized_config_path, config.model_dump(mode="json"))

    bundled_inputs = dict(input_files)
    bundled_inputs["freeze_config_source"] = config_path
    referenced = {
        "protocol": config.protocol_path,
        "corpus_accessions": config.corpus.accession_manifest_path,
        "corpus_stores": config.corpus.stores_manifest_path,
        "effective_server_configuration": (config.retrieval.effective_configuration_path),
        "metadata_structuring_lineages": (config.models.metadata_structuring.lineage_manifest_path),
        "dependency_lock": config.runtime.dependency_lock_path,
    }
    if config.models.query_understanding is not None:
        referenced["query_understanding_prompt"] = config.models.query_understanding.prompt_path
        referenced["query_understanding_options"] = config.models.query_understanding.options_path
    if config.models.translation is not None:
        referenced["translation_prompt"] = config.models.translation.prompt_path
        referenced["translation_options"] = config.models.translation.options_path
    lineage_path = (
        config_path.parent / config.models.metadata_structuring.lineage_manifest_path
    ).resolve()
    _lineage_manifest, lineage_assets, lineage_errors = _read_structuring_lineages(
        lineage_path, verify_assets=True
    )
    if lineage_errors:
        raise FrozenConfigError(
            "metadata-structuring evidence changed after config validation:\n- "
            + "\n- ".join(lineage_errors)
        )
    for label, (relative_path, _digest) in lineage_assets.items():
        referenced[label] = relative_path
    for label, relative_path in referenced.items():
        base = (
            lineage_path.parent
            if label.startswith("metadata_structuring_")
            and (label != "metadata_structuring_lineages")
            else config_path.parent
        )
        bundled_inputs[label] = (base / relative_path).resolve()

    inputs: dict[str, Any] = {}
    input_dir = release_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    for label, path in sorted(bundled_inputs.items()):
        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label)
        target = input_dir / f"{safe_label}{path.suffix}"
        shutil.copyfile(path, target)
        record_count: int | None = None
        if label in {"queries_en", "queries_ko", "facet_judgments"}:
            record_count = sum(
                1 for line in target.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        elif label == "query_manifest":
            with target.open(encoding="utf-8") as handle:
                record_count = sum(1 for _row in csv.DictReader(handle))
        elif label == "corpus_accessions":
            with target.open(encoding="utf-8") as handle:
                record_count = sum(1 for _row in csv.DictReader(handle, delimiter="\t"))
        elif label == "metadata_structuring_lineages":
            parsed_lineages, _assets, _errors = _read_structuring_lineages(
                target, verify_assets=False
            )
            if parsed_lineages is not None:
                record_count = len(parsed_lineages.lineages)
        inputs[label] = file_artifact(target, base=release_dir, record_count=record_count)

    manifest: dict[str, Any] = {
        "schema_version": RUN_SCHEMA_VERSION,
        "release_id": config.release_id,
        "protocol_id": config.protocol_id,
        "status": "running",
        "submission_eligible": False,
        "started_at_utc": utc_now(),
        "completed_at_utc": None,
        "git": {
            "commit": git_value(repo, "rev-parse", "HEAD"),
            "branch": git_value(repo, "branch", "--show-current"),
            "tags": [tag for tag in tags_value.splitlines() if tag],
            "status_sha256": sha256_bytes(status),
            "tracked_diff_sha256": sha256_bytes(diff),
            "dirty": bool(status),
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "bearer_token_present": bool(os.environ.get("GENOFINDER_BEARER_TOKEN")),
        },
        "config": {
            "source_sha256": sha256_file(config_path),
            "normalized": file_artifact(normalized_config_path, base=release_dir),
        },
        "query_set": set_name,
        "inputs": inputs,
        "counts": {
            "expected": expected_observations,
            "attempted": 0,
            "success": 0,
            "failure": 0,
            "zero_result": 0,
            "missing": expected_observations,
        },
        "artifacts": [],
        "errors": [],
        "deviations": [],
        "credential_handling": "No credentials, authorization headers, or full environment dumps.",
    }
    write_json(release_dir / "run_manifest.json", manifest)
    return manifest


def update_run_counts(
    *,
    release_dir: Path,
    manifest: dict[str, Any],
    outcome: str,
    error: dict[str, str] | None,
    deviation: dict[str, str] | None = None,
) -> None:
    if outcome not in {"success", "zero_result", "failure"}:
        raise ValueError(f"unknown observation outcome: {outcome!r}")
    counts = manifest["counts"]
    counts["attempted"] += 1
    if outcome == "failure":
        counts["failure"] += 1
        if error is not None:
            manifest["errors"].append(error)
    else:
        counts["success"] += 1
        if outcome == "zero_result":
            counts["zero_result"] += 1
    counts["missing"] = max(0, counts["expected"] - counts["attempted"])
    if deviation is not None:
        manifest["deviations"].append(deviation)
    write_json(release_dir / "run_manifest.json", manifest)


def finalize_run_manifest(
    *,
    release_dir: Path,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
    aborted: bool = False,
) -> dict[str, Any]:
    counts = manifest["counts"]
    if aborted:
        status = "aborted"
    elif counts["failure"] or counts["missing"]:
        status = "complete_with_failures"
    else:
        status = "complete"
    manifest["status"] = status
    manifest["completed_at_utc"] = utc_now()
    manifest["artifacts"] = artifacts
    commit = manifest.get("git", {}).get("commit")
    tags = manifest.get("git", {}).get("tags")
    manifest["submission_eligible"] = bool(
        status in {"complete", "complete_with_failures"}
        and isinstance(commit, str)
        and re.fullmatch(r"[0-9a-f]{40,64}", commit)
        and isinstance(tags, list)
        and manifest.get("release_id") in tags
        and not manifest["git"]["dirty"]
        and counts["attempted"] == counts["expected"]
        and counts["missing"] == 0
        and not manifest["deviations"]
    )
    write_json(release_dir / "run_manifest.json", manifest)
    return manifest


def _project_metric_observation(observation: dict[str, Any]) -> dict[str, Any]:
    metrics = observation.get("metrics") or {}
    facet = metrics.get("facet") or {}
    exclusion = metrics.get("exclusion") or {}
    return {
        "schema_version": "omicsplorer-hard-query-metric-v1",
        "ordinal": observation.get("ordinal"),
        "call_id": observation.get("call_id"),
        **(observation.get("key") or {}),
        "outcome": observation.get("outcome"),
        "metric_eligible": bool(metrics.get("eligible")),
        "facet_present_macro": facet.get("present_macro"),
        "facet_conjunctive_macro": facet.get("conjunctive_macro"),
        "exclusion_applicable": exclusion.get("applicable"),
        "exclusion_eligible": exclusion.get("eligible"),
        "exclusion_clean_at_k": exclusion.get("clean_at_k"),
        "returned_count": observation.get("returned_count", 0),
        "scored_count": observation.get("scored_count", 0),
    }


def derive_hard_query_metrics(
    *,
    expected_facets: dict[str, Any],
    response: dict[str, Any],
    score_k: int,
    trace_issues: list[str],
) -> dict[str, Any]:
    """Derive the complete metric payload from response content and frozen labels."""
    results = response.get("results")
    if not isinstance(results, list):
        results = []
    docs = [
        {
            "title": result.get("title"),
            "abstract_snippet": result.get("abstract_snippet"),
            "disease_ids": result.get("disease_ids") or [],
            "tissue_ids": result.get("tissue_ids") or [],
            "cell_type_ids": result.get("cell_type_ids") or [],
            "modality": result.get("modality") or [],
        }
        for result in results[:score_k]
        if isinstance(result, dict)
    ]
    facet = facet_satisfaction_hard_at_k(expected_facets, docs, k=score_k)
    exclusion_raw = exclusion_satisfaction_at_k(
        expected_facets.get("must_not_contain", []), docs, k=score_k
    )
    exclusion = dict(exclusion_raw)
    exclusion["eligible"] = bool(
        exclusion_raw["applicable"] and exclusion_raw["n_docs_evaluated"] > 0 and not trace_issues
    )
    if not exclusion["eligible"]:
        exclusion["clean_at_k"] = None
        if not exclusion_raw["applicable"]:
            reason = "no prespecified exclusion terms"
        elif not docs:
            reason = "no returned documents"
        else:
            reason = "effective retrieval path was not verified"
        exclusion["ineligibility_reason"] = reason
    metric_eligible = not trace_issues
    return {
        "eligible": metric_eligible,
        "facet": facet if metric_eligible else {},
        "exclusion": exclusion,
    }


def _aggregate_metric_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        key = observation.get("key") or {}
        grouped[(str(key.get("mode")), str(key.get("lang")))].append(observation)
    rows: list[dict[str, Any]] = []
    for (mode, lang), group in sorted(grouped.items()):
        axes = ["ALL", *sorted({str(item["key"]["axis"]) for item in group})]
        for axis in axes:
            subset = (
                group
                if axis == "ALL"
                else [item for item in group if str(item["key"]["axis"]) == axis]
            )
            for metric_name in (
                "facet_present_macro",
                "facet_conjunctive_macro",
                "exclusion_clean_at_k",
            ):
                values = [
                    float(value)
                    for item in subset
                    if isinstance(
                        (value := _project_metric_observation(item).get(metric_name)),
                        (int, float),
                    )
                ]
                if not values and metric_name == "exclusion_clean_at_k":
                    continue
                rows.append(
                    {
                        "dataset": str(subset[0]["key"]["set_name"]),
                        "mode": mode,
                        "lang": lang,
                        "axis": axis,
                        "metric": metric_name,
                        "mean": statistics.fmean(values) if values else "",
                        "median": statistics.median(values) if values else "",
                        "std": statistics.pstdev(values) if values else "",
                        "n_queries": len(values),
                        "n_planned": len(subset),
                        "n_success": sum(item.get("outcome") != "failure" for item in subset),
                        "n_failure": sum(item.get("outcome") == "failure" for item in subset),
                        "n_zero_result": sum(
                            item.get("outcome") == "zero_result" for item in subset
                        ),
                    }
                )
    return rows


def validate_release_directory(release_dir: Path) -> dict[str, Any]:
    """Strictly validate an already collected release using local files only.

    Counts are recomputed from the raw observation file.  The function does not
    import a search client and cannot perform network I/O.
    """
    errors: list[str] = []
    release_dir = release_dir.resolve()

    def check_descriptor(value: Any, label: str) -> Path | None:
        if not isinstance(value, dict):
            errors.append(f"{label} descriptor is missing")
            return None
        relative = value.get("path")
        expected_hash = value.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            errors.append(f"{label} has an unsafe path")
            return None
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            errors.append(f"{label} has an invalid SHA-256")
        path = release_dir / relative
        if not path.is_file():
            errors.append(f"{label} is missing: {relative}")
            return None
        if sha256_file(path) != expected_hash:
            errors.append(f"{label} SHA-256 mismatch: {relative}")
        if path.stat().st_size != value.get("bytes"):
            errors.append(f"{label} byte count mismatch: {relative}")
        return path

    def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid {label} JSON at line {line_number}: {exc}")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"{label} line {line_number} is not an object")
                    continue
                rows.append(row)
        return rows

    manifest_path = release_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return {"status": "NO-GO", "errors": ["run_manifest.json is missing"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "NO-GO", "errors": [f"invalid run_manifest.json: {exc}"]}

    if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        errors.append("unsupported run manifest schema_version")
    if manifest.get("status") not in {"complete", "complete_with_failures"}:
        errors.append(f"run status is {manifest.get('status')!r}, not a completed status")
    if not manifest.get("submission_eligible"):
        errors.append("manifest marks the run submission_eligible=false")
    if manifest.get("git", {}).get("dirty"):
        errors.append("Git worktree was dirty at collection start")
    commit = manifest.get("git", {}).get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        errors.append("a full immutable Git commit is required")
    tags = manifest.get("git", {}).get("tags")
    if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) for tag in tags):
        errors.append("at least one Git tag pointing at the run commit is required")
    elif manifest.get("release_id") not in tags:
        errors.append("release_id must equal a Git tag pointing at the run commit")
    if manifest.get("deviations"):
        errors.append("the run contains protocol deviations")

    inputs = manifest.get("inputs")
    input_paths: dict[str, Path] = {}
    required_inputs = {
        "queries_en",
        "queries_ko",
        "facet_judgments",
        "query_manifest",
        "freeze_config_source",
        "protocol",
        "corpus_accessions",
        "corpus_stores",
        "effective_server_configuration",
        "metadata_structuring_lineages",
        "dependency_lock",
    }
    if not isinstance(inputs, dict):
        errors.append("input inventory is missing")
        inputs = {}
    for label, descriptor in inputs.items():
        path = check_descriptor(descriptor, f"input {label}")
        if path is not None:
            input_paths[label] = path
    missing_inputs = sorted(required_inputs - set(inputs))
    if missing_inputs:
        errors.append(f"required inputs are missing: {missing_inputs}")

    config: FrozenEvalConfig | None = None
    config_source_path = input_paths.get("freeze_config_source")
    if config_source_path is not None:
        if manifest.get("config", {}).get("source_sha256") != sha256_file(config_source_path):
            errors.append("config source SHA-256 disagrees with bundled input")
        try:
            config = FrozenEvalConfig.model_validate_json(
                config_source_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            errors.append(f"bundled frozen config is invalid: {exc}")
        else:
            errors.extend(
                validate_frozen_config(
                    config,
                    config_path=config_source_path,
                    set_name=manifest.get("query_set"),
                    verify_referenced_files=False,
                )
            )
            if config.release_id != manifest.get("release_id"):
                errors.append("release_id differs between config and manifest")
            if config.protocol_id != manifest.get("protocol_id"):
                errors.append("protocol_id differs between config and manifest")

    normalized_path = check_descriptor(
        manifest.get("config", {}).get("normalized"), "normalized config"
    )
    if normalized_path is not None and config is not None:
        try:
            normalized = FrozenEvalConfig.model_validate_json(
                normalized_path.read_text(encoding="utf-8")
            )
            if normalized != config:
                errors.append("normalized config differs from bundled source config")
        except Exception as exc:
            errors.append(f"normalized config is invalid: {exc}")

    accession_dataset_ids: set[str] = set()
    accession_response_memberships: set[tuple[str, str, str]] = set()
    if config is not None:
        evidence_hashes = {
            "protocol": config.protocol_sha256,
            "corpus_accessions": config.corpus.accession_manifest_sha256,
            "corpus_stores": config.corpus.stores_manifest_sha256,
            "metadata_structuring_lineages": (
                config.models.metadata_structuring.lineage_manifest_sha256
            ),
            "dependency_lock": config.runtime.dependency_lock_sha256,
        }
        if config.models.query_understanding is not None:
            required_inputs.add("query_understanding_prompt")
            required_inputs.add("query_understanding_options")
            evidence_hashes["query_understanding_prompt"] = (
                config.models.query_understanding.prompt_sha256
            )
            evidence_hashes["query_understanding_options"] = (
                config.models.query_understanding.options_sha256
            )
        if config.models.translation is not None:
            required_inputs.add("translation_prompt")
            required_inputs.add("translation_options")
            evidence_hashes["translation_prompt"] = config.models.translation.prompt_sha256
            evidence_hashes["translation_options"] = config.models.translation.options_sha256
        for label, expected_hash in evidence_hashes.items():
            path = input_paths.get(label)
            if path is None:
                errors.append(f"config evidence input is missing: {label}")
            elif sha256_file(path) != expected_hash:
                errors.append(f"config evidence SHA-256 mismatch: {label}")
            elif label.endswith(("_prompt", "_options")):
                errors.extend(_asset_placeholder_issues(path, label=label))

        effective_path = input_paths.get("effective_server_configuration")
        if effective_path is None:
            errors.append("config evidence input is missing: effective_server_configuration")
        else:
            _effective, evidence_errors = _read_effective_server_config(
                effective_path,
                config=config,
            )
            errors.extend(evidence_errors)

        accessions: dict[str, Any] | None = None
        stores: StoresManifest | None = None
        lineages: StructuringLineageManifest | None = None
        accession_path = input_paths.get("corpus_accessions")
        if accession_path is not None:
            accessions, evidence_errors = _read_accession_evidence(accession_path, config=config)
            errors.extend(evidence_errors)
            expected_records = inputs.get("corpus_accessions", {}).get("record_count")
            if accessions is not None and expected_records != accessions["membership_count"]:
                errors.append("input record_count mismatch: corpus_accessions")
            if accessions is not None:
                accession_dataset_ids = set(accessions["dataset_ids"])
                accession_response_memberships = set(accessions["response_memberships"])
        stores_path = input_paths.get("corpus_stores")
        if stores_path is not None:
            stores, evidence_errors = _read_store_evidence(stores_path)
            errors.extend(evidence_errors)
        lineages_path = input_paths.get("metadata_structuring_lineages")
        lineage_assets: dict[str, tuple[str, str]] = {}
        if lineages_path is not None:
            lineages, lineage_assets, evidence_errors = _read_structuring_lineages(
                lineages_path, verify_assets=False
            )
            errors.extend(evidence_errors)
            expected_records = inputs.get("metadata_structuring_lineages", {}).get("record_count")
            if lineages is not None and expected_records != len(lineages.lineages):
                errors.append("input record_count mismatch: metadata_structuring_lineages")
        for label, (_relative_path, expected_hash) in lineage_assets.items():
            asset_path = input_paths.get(label)
            if asset_path is None:
                errors.append(f"metadata-structuring evidence input is missing: {label}")
            elif sha256_file(asset_path) != expected_hash:
                errors.append(f"metadata-structuring evidence SHA-256 mismatch: {label}")
            else:
                errors.extend(_asset_placeholder_issues(asset_path, label=label))
        errors.extend(
            _cross_validate_corpus_evidence(
                config=config,
                accessions=accessions,
                stores=stores,
                lineages=lineages,
            )
        )

    query_qids: set[str] = set()
    query_order: list[str] = []
    query_sets: list[set[str]] = []
    query_texts: dict[tuple[str, str], str] = {}
    query_embedded_facets: dict[tuple[str, str], dict[str, Any]] = {}
    facet_by_qid: dict[str, dict[str, Any]] = {}
    axis_by_qid: dict[str, str] = {}
    for label in ("queries_en", "queries_ko", "facet_judgments"):
        path = input_paths.get(label)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8")
        for blocker in ("<TODO>", "REVIEW_REQUIRED"):
            if blocker in text:
                errors.append(f"unresolved marker {blocker!r} in {label}")
        rows = read_jsonl(path, label)
        if inputs.get(label, {}).get("record_count") != len(rows):
            errors.append(f"input record_count mismatch: {label}")
        ids = [str(row.get("_id") or row.get("qid") or "") for row in rows]
        if "" in ids:
            errors.append(f"missing qid in {label}")
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate qid in {label}")
        query_sets.append(set(ids))
        if label in {"queries_en", "queries_ko"}:
            lang = label.rsplit("_", 1)[-1]
            for row_number, row in enumerate(rows, start=1):
                qid = str(row.get("_id") or "")
                query_text = row.get("text")
                embedded_facets = row.get("expected_facets")
                if not isinstance(query_text, str) or not query_text.strip():
                    errors.append(f"{label} row {row_number} has invalid query text")
                else:
                    query_texts[(qid, lang)] = query_text
                if not isinstance(embedded_facets, dict):
                    errors.append(f"{label} row {row_number} has invalid expected_facets")
                else:
                    query_embedded_facets[(qid, lang)] = embedded_facets
            if label == "queries_en":
                query_qids = set(ids)
                query_order = ids
        else:
            for row_number, row in enumerate(rows, start=1):
                qid = str(row.get("qid") or "")
                expected_facets = row.get("expected")
                if not isinstance(expected_facets, dict):
                    errors.append(f"facet_judgments row {row_number} has invalid expected facets")
                else:
                    facet_by_qid[qid] = expected_facets
    manifest_input_path = input_paths.get("query_manifest")
    if manifest_input_path is not None:
        text = manifest_input_path.read_text(encoding="utf-8")
        if "REVIEW_REQUIRED" in text or "<TODO>" in text:
            errors.append("unresolved marker in query_manifest")
        with manifest_input_path.open(encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle))
        ids = [str(row.get("qid") or "") for row in manifest_rows]
        if inputs.get("query_manifest", {}).get("record_count") != len(ids):
            errors.append("input record_count mismatch: query_manifest")
        for row_number, row in enumerate(manifest_rows, start=2):
            qid = str(row.get("qid") or "")
            axis = str(row.get("axis") or "").strip()
            if not axis or _is_placeholder(axis):
                errors.append(f"query_manifest row {row_number} has invalid diagnostic axis")
            else:
                axis_by_qid[qid] = axis
        if len(ids) != len(set(ids)):
            errors.append("duplicate qid in query_manifest")
        query_sets.append(set(ids))
    if query_sets and any(qids != query_sets[0] for qids in query_sets[1:]):
        errors.append("qid sets differ across bundled query inputs")
    if config is not None and len(query_qids) != config.evaluation.expected_query_count:
        errors.append(
            "query count differs from machine-readable protocol contract: "
            f"{len(query_qids)} != {config.evaluation.expected_query_count}"
        )
    for key, embedded_facets in query_embedded_facets.items():
        authoritative = facet_by_qid.get(key[0])
        if authoritative is not None and embedded_facets != authoritative:
            errors.append(
                "query embedded expected_facets differ from facet_judgments for "
                f"qid={key[0]!r}, lang={key[1]!r}"
            )

    counts = manifest.get("counts", {})
    expected = counts.get("expected")
    attempted = counts.get("attempted")
    success = counts.get("success")
    failure = counts.get("failure")
    missing = counts.get("missing")
    if not all(type(value) is int for value in (expected, attempted, success, failure, missing)):
        errors.append("observation counts are missing or invalid")
    else:
        if expected != attempted or attempted != success + failure:
            errors.append("expected/attempted/success/failure counts are inconsistent")
        if missing != 0:
            errors.append("a submission release may not contain missing observations")

    artifacts = manifest.get("artifacts")
    artifact_by_role: dict[str, dict[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifact inventory is empty")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifact[{index}] is not an object")
                continue
            role = artifact.get("role")
            if not isinstance(role, str) or not role:
                errors.append(f"artifact[{index}] has no role")
                continue
            if role in artifact_by_role:
                errors.append(f"duplicate artifact role: {role}")
            artifact_by_role[role] = artifact
            path = check_descriptor(artifact, f"artifact {role}")
            if path is not None:
                artifact_paths[role] = path

    required_roles = {
        "raw_observations",
        "per_query_metrics",
        "failures",
        "aggregate_metrics",
    }
    if config is not None and config.evaluation.warmup == "unscored_recorded":
        required_roles.add("warmup")
    missing_roles = sorted(required_roles - set(artifact_by_role))
    if missing_roles:
        errors.append(f"required artifact roles are missing: {missing_roles}")

    warmup_path = artifact_paths.get("warmup")
    if warmup_path is not None:
        try:
            warmup = json.loads(warmup_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid warmup artifact: {exc}")
        else:
            if not isinstance(warmup, dict) or warmup.get("outcome") not in {
                "success",
                "failure",
            }:
                errors.append("warmup artifact has an invalid outcome")
            warmup_wall_ms = warmup.get("wall_ms")
            if (
                not isinstance(warmup_wall_ms, (int, float))
                or isinstance(warmup_wall_ms, bool)
                or not math.isfinite(float(warmup_wall_ms))
                or warmup_wall_ms < 0
            ):
                errors.append("warmup artifact has no numeric wall_ms")
            for value_path, value in _iter_values(warmup):
                leaf = value_path.rsplit(".", 1)[-1].lower()
                if any(part in leaf for part in _SECRET_KEY_PARTS):
                    errors.append(f"secret-bearing field found in warmup: {value_path}")
                if isinstance(value, str) and re.search(r"\bBearer\s+\S+", value, re.I):
                    errors.append(f"bearer credential-like value found in warmup: {value_path}")

    raw_rows = (
        read_jsonl(artifact_paths["raw_observations"], "raw observations")
        if "raw_observations" in artifact_paths
        else []
    )
    raw_ids: list[str] = []
    raw_keys: list[tuple[str, str, str]] = []
    raw_ordinals: list[int] = []
    expected_ordinal_by_key: dict[tuple[str, str, str], int] = {}
    if config is not None:
        ordinal = 0
        for mode in config.evaluation.modes:
            for lang in config.evaluation.languages:
                for qid in query_order:
                    ordinal += 1
                    expected_ordinal_by_key[(qid, lang, mode)] = ordinal
    observed_counts = {"attempted": 0, "success": 0, "failure": 0, "zero_result": 0}
    for index, row in enumerate(raw_rows, start=1):
        if row.get("schema_version") != "omicsplorer-hard-query-observation-v1":
            errors.append(f"raw observation {index} has an unsupported schema")
        row_ordinal = row.get("ordinal")
        if not isinstance(row_ordinal, int) or isinstance(row_ordinal, bool):
            errors.append(f"raw observation {index} has an invalid ordinal")
        else:
            raw_ordinals.append(row_ordinal)
        call_id = row.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            errors.append(f"raw observation {index} has no call_id")
        else:
            raw_ids.append(call_id)
        row_key_record = row.get("key")
        if not isinstance(row_key_record, dict):
            errors.append(f"raw observation {index} has an invalid key")
            row_key_record = {}
        row_qid = str(row_key_record.get("qid") or "")
        row_lang = str(row_key_record.get("lang") or "")
        row_mode = str(row_key_record.get("mode") or "")
        raw_key = (row_qid, row_lang, row_mode)
        raw_keys.append(raw_key)
        if config is not None:
            expected_key = {
                "set_name": manifest.get("query_set"),
                "qid": row_qid,
                "axis": axis_by_qid.get(row_qid),
                "lang": row_lang,
                "mode": row_mode,
            }
            if not _json_exact_equal(row_key_record, expected_key):
                errors.append(f"raw observation {index} key differs from bundled inputs/config")
            expected_call_id = hashlib.sha256(
                f"{manifest.get('query_set')}\0{row_qid}\0{row_lang}\0{row_mode}".encode()
            ).hexdigest()[:20]
            if call_id != expected_call_id:
                errors.append(f"raw observation {index} call_id is not deterministic")
            if row_ordinal != expected_ordinal_by_key.get(raw_key):
                errors.append(f"raw observation {index} ordinal differs from frozen schedule")

        expected_query_text = query_texts.get((row_qid, row_lang))
        query = row.get("query")
        if not isinstance(query, dict):
            errors.append(f"raw observation {index} query is not an object")
            query = {}
        query_text = query.get("text")
        expected_query_record = (
            {
                "text": expected_query_text,
                "sha256": hashlib.sha256(expected_query_text.encode("utf-8")).hexdigest(),
            }
            if isinstance(expected_query_text, str)
            else None
        )
        if not _json_exact_equal(query, expected_query_record):
            errors.append(f"raw observation {index} query differs from bundled {row_lang} query")
        expected_facets = facet_by_qid.get(row_qid)
        if not _json_exact_equal(row.get("expected_facets"), expected_facets):
            errors.append(f"raw observation {index} expected_facets differ from bundled judgments")
        if config is not None:
            expected_request = {
                "corpus": config.retrieval.corpus,
                "top_k": config.evaluation.top_k,
                "score_k": config.evaluation.score_k,
                "auto_translate": config.retrieval.auto_translate,
                "access_preference": config.retrieval.access_preference,
            }
            if not _json_exact_equal(row.get("request"), expected_request):
                errors.append(f"raw observation {index} request differs from frozen config")

        wall_ms = row.get("wall_ms")
        if (
            not isinstance(wall_ms, (int, float))
            or isinstance(wall_ms, bool)
            or not math.isfinite(float(wall_ms))
            or wall_ms < 0
        ):
            errors.append(f"raw observation {index} has invalid wall_ms")
        outcome = row.get("outcome")
        if outcome not in {"success", "zero_result", "failure"}:
            errors.append(f"raw observation {index} has invalid outcome {outcome!r}")
        else:
            observed_counts["attempted"] += 1
        if outcome == "failure":
            observed_counts["failure"] += 1
            if not isinstance(row.get("error"), dict):
                errors.append(f"failure observation {index} has no error record")
            if row.get("response") is not None or row.get("effective_query") is not None:
                errors.append(f"failure observation {index} retains a response/effective query")
            if not _json_exact_equal(row.get("returned_count"), 0) or not _json_exact_equal(
                row.get("scored_count"), 0
            ):
                errors.append(f"failure observation {index} has nonzero result counts")
            if not _json_exact_equal(row.get("metrics"), {"eligible": False}):
                errors.append(f"failure observation {index} contains imputed or derived metrics")
            if row.get("deviation") is not None:
                errors.append(f"failure observation {index} has an unexpected deviation")
        else:
            if outcome in {"success", "zero_result"}:
                observed_counts["success"] += 1
                if outcome == "zero_result":
                    observed_counts["zero_result"] += 1
            response = row.get("response")
            if not isinstance(response, dict):
                errors.append(f"nonfailure observation {index} has no response object")
                response = {}
            results = response.get("results")
            result_count = len(results) if isinstance(results, list) else 0
            if isinstance(results, list):
                response_dataset_ids: list[str] = []
                for result_number, result in enumerate(results, start=1):
                    dataset_id = result.get("dataset_id") if isinstance(result, dict) else None
                    source_db = result.get("source_db") if isinstance(result, dict) else None
                    source_id = result.get("source_id") if isinstance(result, dict) else None
                    if dataset_id not in accession_dataset_ids:
                        errors.append(
                            "raw observation "
                            f"{index} result {result_number} dataset_id is absent from "
                            "the frozen accession manifest"
                        )
                    elif (dataset_id, source_db, source_id) not in (accession_response_memberships):
                        errors.append(
                            "raw observation "
                            f"{index} result {result_number} source/accession does not "
                            "match its frozen dataset membership"
                        )
                    if isinstance(dataset_id, str):
                        response_dataset_ids.append(dataset_id)
                    if (
                        config is not None
                        and config.retrieval.access_preference == "open_only"
                        and (not isinstance(result, dict) or result.get("access_type") != "open")
                    ):
                        errors.append(
                            "raw observation "
                            f"{index} result {result_number} violates open_only access"
                        )
                if len(response_dataset_ids) != len(set(response_dataset_ids)):
                    errors.append(f"raw observation {index} contains duplicate dataset_id results")
            if not _json_exact_equal(row.get("returned_count"), result_count):
                errors.append(f"raw observation {index} returned_count differs from response")
            expected_scored_count = (
                min(config.evaluation.score_k, result_count) if config is not None else result_count
            )
            if not _json_exact_equal(row.get("scored_count"), expected_scored_count):
                errors.append(f"raw observation {index} scored_count differs from response/config")
            expected_outcome = "zero_result" if result_count == 0 else "success"
            if outcome != expected_outcome:
                errors.append(f"raw observation {index} outcome differs from response result count")
            if row.get("error") is not None:
                errors.append(f"nonfailure observation {index} has an error record")
            effective_query = row.get("effective_query")
            effective_text = response.get("translated_query") or query_text
            expected_effective_query = (
                {
                    "text": effective_text,
                    "sha256": hashlib.sha256(effective_text.encode("utf-8")).hexdigest(),
                    "translation_applied": bool(response.get("translated_query")),
                }
                if isinstance(effective_text, str)
                else None
            )
            if not _json_exact_equal(effective_query, expected_effective_query):
                errors.append(f"raw observation {index} effective query differs from response")
            expected_effective = response.get("translated_query") or query_text
            if (
                not isinstance(effective_query, dict)
                or effective_query.get("text") != expected_effective
            ):
                errors.append(f"raw observation {index} effective-query text mismatch")
            trace_issues: list[str] = []
            if config is not None and isinstance(query_text, str):
                path_issues = frozen_response_path_issues(
                    config=config,
                    mode=row_mode,
                    lang=row_lang,
                    query_text=query_text,
                    response=response,
                )
                trace_issues.extend(path_issues)
                errors.extend(
                    f"raw observation {index} effective path: {issue}" for issue in path_issues
                )
                expected_evaluation_request = {
                    "query_text": query_text,
                    "mode": row_mode,
                    "corpus": config.retrieval.corpus,
                    "page": 1,
                    "page_size": config.evaluation.top_k,
                    "lang": row_lang,
                    "auto_translate": config.retrieval.auto_translate,
                    "access_preference": config.retrieval.access_preference,
                }
                if not _json_exact_equal(
                    response.get("evaluation_request"), expected_evaluation_request
                ):
                    errors.append(
                        f"raw observation {index} client request evidence differs from schedule"
                    )
            if isinstance(expected_facets, dict) and config is not None:
                expected_metrics = derive_hard_query_metrics(
                    expected_facets=expected_facets,
                    response=response,
                    score_k=config.evaluation.score_k,
                    trace_issues=trace_issues,
                )
                if not _json_exact_equal(row.get("metrics"), expected_metrics):
                    errors.append(
                        f"raw observation {index} metrics differ from raw-derived metrics"
                    )
            expected_deviation = bool(trace_issues)
            if expected_deviation != isinstance(row.get("deviation"), dict):
                errors.append(f"raw observation {index} deviation state differs from path checks")
        for value_path, value in _iter_values(row):
            leaf = value_path.rsplit(".", 1)[-1].lower()
            if any(part in leaf for part in _SECRET_KEY_PARTS):
                errors.append(f"secret-bearing field found in raw observation: {value_path}")
            if isinstance(value, str) and re.search(r"\bBearer\s+\S+", value, re.I):
                errors.append(
                    f"bearer credential-like value found in raw observation: {value_path}"
                )
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(f"non-finite numeric value found in raw observation: {value_path}")

    if len(raw_ids) != len(set(raw_ids)):
        errors.append("duplicate call_id in raw observations")
    if len(raw_keys) != len(set(raw_keys)):
        errors.append("duplicate (qid, lang, mode) tuple in raw observations")
    if len(raw_ordinals) != len(set(raw_ordinals)) or set(raw_ordinals) != set(
        range(1, len(raw_rows) + 1)
    ):
        errors.append("raw observation ordinals are duplicate or non-contiguous")
    if config is not None and query_qids:
        expected_keys = {
            (qid, lang, mode)
            for qid in query_qids
            for lang in config.evaluation.languages
            for mode in config.evaluation.modes
        }
        if set(raw_keys) != expected_keys:
            errors.append("raw observation keys do not match the prespecified Cartesian product")

    if isinstance(counts, dict):
        for name, observed in observed_counts.items():
            if counts.get(name) != observed:
                errors.append(
                    f"manifest count {name}={counts.get(name)!r} differs from raw {observed}"
                )
        expected_from_raw = len(raw_rows)
        if counts.get("expected") != expected_from_raw or counts.get("missing") != 0:
            errors.append("manifest expected/missing counts disagree with raw observations")

    metric_rows = (
        read_jsonl(artifact_paths["per_query_metrics"], "per-query metrics")
        if "per_query_metrics" in artifact_paths
        else []
    )
    metric_ids = [str(row.get("call_id") or "") for row in metric_rows]
    if len(metric_ids) != len(set(metric_ids)) or set(metric_ids) != set(raw_ids):
        errors.append("per-query metric call_ids are duplicate or differ from raw observations")
    expected_metrics = {
        str(row.get("call_id") or ""): _project_metric_observation(row) for row in raw_rows
    }
    actual_metrics = {str(row.get("call_id") or ""): row for row in metric_rows}
    for call_id, expected_metric in expected_metrics.items():
        if not _json_exact_equal(actual_metrics.get(call_id), expected_metric):
            errors.append(f"per-query metric differs from raw observation: {call_id}")
    failure_rows = (
        read_jsonl(artifact_paths["failures"], "failures") if "failures" in artifact_paths else []
    )
    failure_ids = {str(row.get("call_id") or "") for row in failure_rows}
    expected_failure_ids = {
        str(row.get("call_id") or "") for row in raw_rows if row.get("outcome") == "failure"
    }
    if failure_ids != expected_failure_ids or len(failure_rows) != len(expected_failure_ids):
        errors.append("failure artifact does not exactly match raw failure observations")
    else:
        raw_failure_by_id = {
            str(row.get("call_id") or ""): row
            for row in raw_rows
            if row.get("outcome") == "failure"
        }
        artifact_failure_by_id = {str(row.get("call_id") or ""): row for row in failure_rows}
        for call_id, expected_failure in raw_failure_by_id.items():
            if not _json_exact_equal(artifact_failure_by_id.get(call_id), expected_failure):
                errors.append(f"failure artifact row differs from raw observation: {call_id}")

    expected_manifest_errors = [
        {"call_id": str(row.get("call_id") or ""), **row["error"]}
        for row in raw_rows
        if row.get("outcome") == "failure" and isinstance(row.get("error"), dict)
    ]
    if not _json_exact_equal(manifest.get("errors"), expected_manifest_errors):
        errors.append("manifest errors do not exactly project raw failure observations")
    expected_manifest_deviations = [
        row["deviation"] for row in raw_rows if isinstance(row.get("deviation"), dict)
    ]
    if not _json_exact_equal(manifest.get("deviations"), expected_manifest_deviations):
        errors.append("manifest deviations do not exactly project raw observations")

    for role, rows in (
        ("raw_observations", raw_rows),
        ("per_query_metrics", metric_rows),
        ("failures", failure_rows),
    ):
        descriptor = artifact_by_role.get(role, {})
        if descriptor.get("record_count") != len(rows):
            errors.append(f"artifact record_count mismatch: {role}")

    aggregate_path = artifact_paths.get("aggregate_metrics")
    if aggregate_path is not None:
        with aggregate_path.open(encoding="utf-8") as handle:
            aggregate_rows = list(csv.DictReader(handle))
        if artifact_by_role["aggregate_metrics"].get("record_count") != len(aggregate_rows):
            errors.append("artifact record_count mismatch: aggregate_metrics")
        identity_fields = ("dataset", "mode", "lang", "axis", "metric")
        expected_aggregates = _aggregate_metric_observations(raw_rows)
        expected_by_key = {
            tuple(str(row[field]) for field in identity_fields): row for row in expected_aggregates
        }
        actual_by_key: dict[tuple[str, ...], dict[str, str]] = {}
        for row in aggregate_rows:
            aggregate_key = tuple(str(row.get(field, "")) for field in identity_fields)
            if aggregate_key in actual_by_key:
                errors.append(f"duplicate aggregate row: {aggregate_key}")
            actual_by_key[aggregate_key] = row
        if set(actual_by_key) != set(expected_by_key):
            errors.append("aggregate row keys differ from raw-derived aggregates")
        for aggregate_key, expected_row in expected_by_key.items():
            actual_row = actual_by_key.get(aggregate_key)
            if actual_row is None:
                continue
            for field in ("n_queries", "n_planned", "n_success", "n_failure", "n_zero_result"):
                try:
                    observed_value = int(actual_row.get(field, ""))
                except ValueError:
                    errors.append(f"aggregate {aggregate_key} has invalid integer {field}")
                    continue
                if observed_value != expected_row[field]:
                    errors.append(f"aggregate {aggregate_key} differs from raw for {field}")
            for field in ("mean", "median", "std"):
                expected_value = expected_row[field]
                observed_text = actual_row.get(field, "")
                if expected_value == "":
                    if observed_text != "":
                        errors.append(f"aggregate {aggregate_key} should have blank {field}")
                    continue
                try:
                    observed_float = float(observed_text)
                except ValueError:
                    errors.append(f"aggregate {aggregate_key} has invalid numeric {field}")
                    continue
                if not math.isfinite(observed_float):
                    errors.append(f"aggregate {aggregate_key} has non-finite numeric {field}")
                    continue
                if abs(observed_float - float(expected_value)) > 1e-12:
                    errors.append(f"aggregate {aggregate_key} differs from raw for {field}")

    return {
        "status": "GO" if not errors else "NO-GO",
        "checked_at_utc": utc_now(),
        "release_id": manifest.get("release_id"),
        "errors": errors,
    }
