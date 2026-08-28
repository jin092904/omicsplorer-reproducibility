"""Write-disabled Sol4 feasibility-pilot execution with fail-closed guards."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import asyncpg
import httpx

from genofinder_eval.metadata_contract import (
    clean_product_commit,
    fetch_json,
    load_product_modules,
    select_model_entry,
    sha256_bytes,
    validate_contract,
)
from genofinder_eval.metadata_pilot import (
    manifest_record,
    sha256_json,
    validate_records,
)

DATASET_SQL = """
SELECT
  d.id,
  d.source_db,
  d.source_id,
  d.title,
  d.abstract,
  d.raw_metadata,
  d.n_samples,
  d.tissue_ids,
  d.cell_type_ids,
  d.disease_ids,
  d.cohort_design,
  d.extraction_version AS historical_extraction_version,
  d.extraction_lineage_id,
  d.build_stage,
  COALESCE((SELECT count(*) FROM samples sa WHERE sa.dataset_id = d.id), 0) AS sample_rows,
  COALESCE(st.sample_titles, ARRAY[]::text[]) AS sample_titles
FROM datasets d
LEFT JOIN LATERAL (
  SELECT array_agg(t.sample_title ORDER BY t.source_sample_id) AS sample_titles
  FROM (
    SELECT
      sa.source_sample_id,
      nullif(trim(COALESCE(
        sa.raw_attributes->>'title',
        sa.raw_attributes->>'Sample_title',
        sa.source_sample_id,
        ''
      )), '') AS sample_title
    FROM samples sa
    WHERE sa.dataset_id = d.id
    ORDER BY sa.source_sample_id
    LIMIT 30
  ) t
  WHERE t.sample_title IS NOT NULL
) st ON true
WHERE d.source_db = $1 AND d.source_id = $2
"""


STATE_SQL = """
WITH requested AS (
  SELECT source_db, source_id
  FROM jsonb_to_recordset($1::jsonb) AS x(source_db text, source_id text)
)
SELECT
  d.source_db,
  d.source_id,
  d.tissue_ids,
  d.cell_type_ids,
  d.disease_ids,
  d.cohort_design,
  d.raw_metadata,
  d.extraction_version,
  d.extraction_lineage_id,
  d.build_stage
FROM requested r
JOIN datasets d USING (source_db, source_id)
ORDER BY d.source_db, d.source_id
"""


class PilotRunnerError(ValueError):
    """Raised before inference when a write-disabled pilot guard fails."""


def load_private_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise PilotRunnerError(f"selection manifest is missing: {path}")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PilotRunnerError("selection manifest must have mode 0600")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise PilotRunnerError(f"manifest line {line_number} is not a JSON object")
        records.append(cast(dict[str, Any], value))
    return records


def select_per_stratum(
    records: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    *,
    per_stratum: int,
) -> list[dict[str, Any]]:
    if per_stratum <= 0:
        raise PilotRunnerError("per_stratum must be positive")
    selected: list[dict[str, Any]] = []
    for stratum in spec["strata"]:
        label = str(stratum["label"])
        matches = [dict(record) for record in records if record.get("stratum") == label]
        if len(matches) < per_stratum:
            raise PilotRunnerError(f"stratum {label} has fewer than {per_stratum} records")
        selected.extend(matches[:per_stratum])
    return selected


def database_dsn(database_url: str) -> str:
    if not database_url:
        raise PilotRunnerError("DATABASE_URL is required")
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def activate_product_import_paths(product_root: Path) -> None:
    workers = product_root / "apps" / "workers"
    for path in (workers / "scripts", workers):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _state_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    normalized = []
    for row in rows:
        normalized.append(
            {
                key: _json_value(row.get(key))
                for key in (
                    "source_db",
                    "source_id",
                    "tissue_ids",
                    "cell_type_ids",
                    "disease_ids",
                    "cohort_design",
                    "raw_metadata",
                    "extraction_version",
                    "extraction_lineage_id",
                    "build_stage",
                )
            }
        )
    return sha256_json(normalized)


async def observe_stores(
    connection: asyncpg.Connection,
    selected: Sequence[Mapping[str, Any]],
    *,
    qdrant_url: str,
    opensearch_url: str,
) -> dict[str, Any]:
    keys = [
        {"source_db": record["source_db"], "source_id": record["source_id"]}
        for record in selected
    ]
    async with connection.transaction(readonly=True):
        readonly = await connection.fetchval("SHOW transaction_read_only")
        if readonly != "on":
            raise PilotRunnerError("store observation transaction is not read-only")
        dataset_count = int(await connection.fetchval("SELECT count(*) FROM datasets"))
        state_rows = await connection.fetch(STATE_SQL, json.dumps(keys))
    if len(state_rows) != len(selected):
        raise PilotRunnerError("selected-row state observation is incomplete")

    async with httpx.AsyncClient(timeout=20.0) as client:
        qdrant_response = await client.get(
            f"{qdrant_url.rstrip('/')}/collections/datasets_v2"
        )
        qdrant_response.raise_for_status()
        qdrant = qdrant_response.json()
        opensearch_response = await client.get(
            f"{opensearch_url.rstrip('/')}/datasets_v2/_count"
        )
        opensearch_response.raise_for_status()
        opensearch = opensearch_response.json()
    return {
        "postgresql_dataset_count": dataset_count,
        "selected_row_state_sha256": _state_digest([dict(row) for row in state_rows]),
        "qdrant_points_count": int(qdrant["result"]["points_count"]),
        "opensearch_document_count": int(opensearch["count"]),
    }


async def verify_selected_inputs(
    connection: asyncpg.Connection,
    selected: Sequence[Mapping[str, Any]],
) -> None:
    async with connection.transaction(readonly=True):
        readonly = await connection.fetchval("SHOW transaction_read_only")
        if readonly != "on":
            raise PilotRunnerError("input preflight transaction is not read-only")
        for selection_record in selected:
            raw_row = await connection.fetchrow(
                DATASET_SQL,
                str(selection_record["source_db"]),
                str(selection_record["source_id"]),
            )
            if raw_row is None:
                raise PilotRunnerError("selected dataset is missing during input preflight")
            observed = manifest_record(
                {
                    **dict(raw_row),
                    "label": selection_record["stratum"],
                    "selection_rank": selection_record["selection_rank"],
                },
                seed=str(selection_record["selection_seed"]),
            )
            if observed["source_input_sha256"] != selection_record["source_input_sha256"]:
                raise PilotRunnerError("selected source input hash has changed")


def verify_live_runtime(contract_dir: Path, *, ollama_url: str) -> dict[str, Any]:
    raw_runtime = json.loads(
        (contract_dir / "sol4-runtime.json").read_text(encoding="utf-8")
    )
    raw_options = json.loads(
        (contract_dir / "sol4-options.json").read_text(encoding="utf-8")
    )
    if not isinstance(raw_runtime, dict) or not isinstance(raw_options, dict):
        raise PilotRunnerError("frozen runtime and options must be JSON objects")
    runtime = cast(dict[str, Any], raw_runtime)
    options = cast(dict[str, Any], raw_options)
    version = fetch_json(f"{ollama_url.rstrip('/')}/api/version")
    model = select_model_entry(
        fetch_json(f"{ollama_url.rstrip('/')}/api/tags"),
        str(runtime["model_tag"]),
    )
    if version.get("version") != runtime.get("ollama_version"):
        raise PilotRunnerError("live Ollama version differs from frozen runtime")
    if model.get("digest") != runtime.get("weight_digest_sha256"):
        raise PilotRunnerError("live model digest differs from frozen runtime")
    expected_url = f"{ollama_url.rstrip('/')}/api/generate"
    for request_key in ("first_pass_request", "validation_retry_request"):
        if options.get(request_key, {}).get("url") != expected_url:
            raise PilotRunnerError(f"{request_key} endpoint differs from requested Ollama URL")
    return runtime


def observe_model_residency(ollama_url: str, model_tag: str) -> dict[str, Any]:
    value = fetch_json(f"{ollama_url.rstrip('/')}/api/ps")
    models = value.get("models")
    if not isinstance(models, list):
        raise PilotRunnerError("Ollama process response has no models list")
    matches = [item for item in models if isinstance(item, dict) and item.get("name") == model_tag]
    if len(matches) > 1:
        raise PilotRunnerError("Ollama reports the frozen model more than once")
    if not matches:
        return {"loaded": False, "model_tag": model_tag}
    model = cast(dict[str, Any], matches[0])
    return {
        "loaded": True,
        "model_tag": model_tag,
        "digest": model.get("digest"),
        "size_vram_bytes": model.get("size_vram"),
        "expires_at": model.get("expires_at"),
    }


class _CountingClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.http_attempts = 0
        self.response_diagnostics: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.http_attempts += 1
        response = await self._client.post(url, **kwargs)
        diagnostic: dict[str, Any] = {"http_status": response.status_code}
        try:
            payload = response.json()
            generated = payload.get("response", "") if isinstance(payload, dict) else ""
            diagnostic.update(
                {
                    "response_chars": len(generated) if isinstance(generated, str) else None,
                    "response_sha256": (
                        sha256_bytes(generated.encode("utf-8"))
                        if isinstance(generated, str)
                        else None
                    ),
                    "done_reason": payload.get("done_reason") if isinstance(payload, dict) else None,
                    "prompt_eval_count": (
                        payload.get("prompt_eval_count") if isinstance(payload, dict) else None
                    ),
                    "eval_count": payload.get("eval_count") if isinstance(payload, dict) else None,
                    "load_duration_ns": (
                        payload.get("load_duration") if isinstance(payload, dict) else None
                    ),
                    "total_duration_ns": (
                        payload.get("total_duration") if isinstance(payload, dict) else None
                    ),
                }
            )
        except (json.JSONDecodeError, ValueError):
            diagnostic["response_json_decodable"] = False
        self.response_diagnostics.append(diagnostic)
        return response


def _validation_error_category(error: str) -> str:
    if error.startswith("jsonschema:"):
        return "jsonschema"
    if "contains CURIE-like" in error:
        return "curie_like_label"
    return "semantic_other"


def smoke_status(*, preflight_only: bool, unchanged: bool, results: Sequence[Mapping[str, Any]]) -> str:
    if not unchanged:
        return "failed_write_guard"
    if preflight_only:
        return "preflight_complete"
    if all(result.get("outcome") == "success" for result in results):
        return "complete"
    return "complete_with_failures"


async def _run_one(
    connection: asyncpg.Connection,
    product_module: ModuleType,
    selection_record: Mapping[str, Any],
    *,
    ollama_url: str,
    model_tag: str,
) -> dict[str, Any]:
    product: Any = product_module
    product.OLLAMA_URL = ollama_url.rstrip("/")
    product.OLLAMA_MODEL = model_tag
    product.log.disabled = True
    logging.getLogger("src.ontology.mapper").setLevel(logging.ERROR)

    started = time.perf_counter()
    validation_temperatures: list[float] = []
    generation_events: list[dict[str, Any]] = []
    validation_events: list[dict[str, Any]] = []
    original_generate = product._ollama_generate
    original_validate = product._semantic_validate

    async def observed_generate(
        client: Any,
        prompt: str,
        *,
        temperature: float,
        max_retries: int = product.CB_MAX_RETRIES,
    ) -> Any:
        validation_temperatures.append(temperature)
        parsed = await original_generate(
            client,
            prompt,
            temperature=temperature,
            max_retries=max_retries,
        )
        generation_events.append(
            {
                "json_parsed": parsed is not None,
                "parsed_type": type(parsed).__name__ if parsed is not None else None,
            }
        )
        return parsed

    def observed_validate(
        parsed: dict[str, Any],
        sample_titles: list[str],
        raw_metadata: str,
    ) -> tuple[bool, str]:
        ok, error = original_validate(parsed, sample_titles, raw_metadata)
        validation_events.append(
            {
                "ok": ok,
                "error_category": None if ok else _validation_error_category(error),
                "error_sha256": None if ok else sha256_bytes(error.encode("utf-8")),
            }
        )
        return ok, error

    async with connection.transaction(readonly=True):
        readonly = await connection.fetchval("SHOW transaction_read_only")
        if readonly != "on":
            raise PilotRunnerError("dataset transaction is not read-only")
        raw_row = await connection.fetchrow(
            DATASET_SQL,
            str(selection_record["source_db"]),
            str(selection_record["source_id"]),
        )
        if raw_row is None:
            raise PilotRunnerError("selected dataset is missing")
        row = dict(raw_row)
        observed_manifest = manifest_record(
            {
                **row,
                "label": selection_record["stratum"],
                "selection_rank": selection_record["selection_rank"],
            },
            seed=str(selection_record["selection_seed"]),
        )
        if observed_manifest["source_input_sha256"] != selection_record["source_input_sha256"]:
            raise PilotRunnerError("selected source input hash has changed")

        sample_titles = [str(value) for value in row.get("sample_titles") or []]
        raw_metadata = row.get("raw_metadata") or ""
        raw_meta_text = (
            json.dumps(raw_metadata)
            if isinstance(raw_metadata, (dict, list))
            else str(raw_metadata)
        )
        prompt = product._build_prompt(
            title=row.get("title") or "",
            abstract=row.get("abstract") or "",
            raw_metadata=raw_meta_text,
            sample_titles=sample_titles,
        )

        product._ollama_generate = observed_generate
        product._semantic_validate = observed_validate
        llm_started = time.perf_counter()
        async with httpx.AsyncClient(timeout=float(product.OLLAMA_TIMEOUT)) as client:
            counting_client = _CountingClient(client)
            try:
                extract = await product.llm_extract_sol4(
                    counting_client,
                    prompt,
                    sample_titles,
                    raw_meta_text,
                )
            finally:
                product._ollama_generate = original_generate
                product._semantic_validate = original_validate
        llm_ms = (time.perf_counter() - llm_started) * 1000

        result: dict[str, Any] = {
            "schema_version": "omicsplorer-metadata-pilot-smoke-result-v1",
            "record_key_sha256": selection_record["record_key_sha256"],
            "stratum": selection_record["stratum"],
            "input_sha256": selection_record["source_input_sha256"],
            "llm_ms": llm_ms,
            "llm_http_attempts": counting_client.http_attempts,
            "ollama_responses": counting_client.response_diagnostics,
            "generation_events": generation_events,
            "validation_events": validation_events,
            "validation_temperatures": validation_temperatures,
            "validation_retry_used": len(validation_temperatures) > 1,
        }
        if extract is None:
            result.update(
                {
                    "outcome": "model_or_validation_error",
                    "schema_valid_after_policy": False,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                }
            )
            return result

        normalize_started = time.perf_counter()
        try:
            changed, new_curies = await product.apply_extraction_auto(
                connection,
                row,
                extract,
                shadow=True,
            )
        except Exception as error:
            result.update(
                {
                    "outcome": "normalization_error",
                    "schema_valid_after_policy": True,
                    "prediction_sha256": sha256_json(extract),
                    "normalization_error_type": type(error).__name__,
                    "normalization_ms": (time.perf_counter() - normalize_started) * 1000,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                }
            )
            return result

        result.update(
            {
                "outcome": "success",
                "schema_valid_after_policy": True,
                "prediction_sha256": sha256_json(extract),
                "shadow_would_change": bool(changed),
                "shadow_new_curies": int(new_curies),
                "normalization_ms": (time.perf_counter() - normalize_started) * 1000,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            }
        )
        return result


def write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


async def run_smoke(
    *,
    database_url: str,
    selection_manifest: Path,
    selection_spec: Mapping[str, Any],
    contract_dir: Path,
    product_root: Path,
    output_path: Path,
    ollama_url: str,
    qdrant_url: str,
    opensearch_url: str,
    per_stratum: int,
    preflight_only: bool = False,
) -> dict[str, Any]:
    if output_path.exists():
        raise PilotRunnerError("output already exists; refusing to overwrite pilot evidence")
    contract = validate_contract(contract_dir)
    product_commit = clean_product_commit(product_root)
    if product_commit != contract.get("product_git_commit"):
        raise PilotRunnerError("product checkout does not match the frozen contract commit")
    runtime = verify_live_runtime(contract_dir, ollama_url=ollama_url)

    all_records = load_private_manifest(selection_manifest)
    validate_records(all_records, selection_spec)
    selected = select_per_stratum(all_records, selection_spec, per_stratum=per_stratum)
    activate_product_import_paths(product_root)
    prompt_module, product_module = load_product_modules(product_root)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    prompt = cast(str, prompt_module.SOL4_PROMPT_TEMPLATE)
    frozen_prompt = (contract_dir / "sol4-prompt.txt").read_text(encoding="utf-8")
    if prompt != frozen_prompt:
        raise PilotRunnerError("loaded product prompt differs from frozen prompt")
    frozen_schema = json.loads(
        (contract_dir / "sol4-schema.json").read_text(encoding="utf-8")
    )
    if product_module.SOL4_OUTPUT_SCHEMA != frozen_schema:
        raise PilotRunnerError("loaded product schema differs from frozen schema")

    connection = await asyncpg.connect(database_dsn(database_url))
    run_started = time.perf_counter()
    results: list[dict[str, Any]] = []
    try:
        await verify_selected_inputs(connection, selected)
        model_before = observe_model_residency(ollama_url, str(runtime["model_tag"]))
        before = await observe_stores(
            connection,
            selected,
            qdrant_url=qdrant_url,
            opensearch_url=opensearch_url,
        )
        if not preflight_only:
            for record in selected:
                try:
                    result = await _run_one(
                        connection,
                        product_module,
                        record,
                        ollama_url=ollama_url,
                        model_tag=str(runtime["model_tag"]),
                    )
                except Exception as error:
                    result = {
                        "schema_version": "omicsplorer-metadata-pilot-smoke-result-v1",
                        "record_key_sha256": record["record_key_sha256"],
                        "stratum": record["stratum"],
                        "input_sha256": record["source_input_sha256"],
                        "outcome": "runner_error",
                        "error_type": type(error).__name__,
                    }
                results.append(result)
        after = await observe_stores(
            connection,
            selected,
            qdrant_url=qdrant_url,
            opensearch_url=opensearch_url,
        )
        model_after = observe_model_residency(ollama_url, str(runtime["model_tag"]))
    finally:
        await connection.close()

    unchanged = before == after
    summary = {
        "schema_version": "omicsplorer-metadata-pilot-smoke-run-v1",
        "status": smoke_status(
            preflight_only=preflight_only,
            unchanged=unchanged,
            results=results,
        ),
        "mode": "preflight_only" if preflight_only else "five_record_smoke",
        "interpretation": (
            "write-disabled feasibility smoke only; no metadata-accuracy or effectiveness claim"
        ),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "product_git_commit": product_commit,
        "contract_manifest_sha256": sha256_bytes(
            (contract_dir / "contract-manifest.json").read_bytes()
        ),
        "selection_manifest_sha256": sha256_bytes(selection_manifest.read_bytes()),
        "selected_n": len(selected),
        "per_stratum": per_stratum,
        "store_observation_before": before,
        "store_observation_after": after,
        "model_residency_before": model_before,
        "model_residency_after": model_after,
        "write_guard_passed": unchanged,
        "outcome_counts": {
            outcome: sum(result.get("outcome") == outcome for result in results)
            for outcome in sorted({str(result.get("outcome")) for result in results})
        },
        "elapsed_seconds": time.perf_counter() - run_started,
        "results": results,
    }
    write_private_json(output_path, summary)
    return summary
