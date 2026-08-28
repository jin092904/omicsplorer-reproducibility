"""Deterministic, read-only input selection for the metadata feasibility pilot."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import asyncpg

PILOT_SELECTION_SQL = """
WITH strata AS (
  SELECT label, source_db, historical_extraction_version, target_n
  FROM jsonb_to_recordset($1::jsonb) AS x(
    label text,
    source_db text,
    historical_extraction_version text,
    target_n integer
  )
), ranked AS (
  SELECT
    s.label,
    s.target_n,
    d.id,
    d.source_db,
    d.source_id,
    d.extraction_version AS historical_extraction_version,
    d.title,
    d.abstract,
    d.raw_metadata,
    d.n_samples,
    row_number() OVER (
      PARTITION BY s.label
      ORDER BY md5(d.source_db || ':' || d.source_id || ':' || $2), d.source_id
    ) AS selection_rank
  FROM strata s
  JOIN datasets d
    ON d.source_db = s.source_db
   AND d.extraction_version = s.historical_extraction_version
), picked AS (
  SELECT * FROM ranked WHERE selection_rank <= target_n
)
SELECT
  p.label,
  p.source_db,
  p.source_id,
  p.historical_extraction_version,
  p.selection_rank,
  p.title,
  p.abstract,
  p.raw_metadata,
  p.n_samples,
  COALESCE((SELECT count(*) FROM samples sa WHERE sa.dataset_id = p.id), 0) AS sample_rows,
  COALESCE(st.sample_titles, ARRAY[]::text[]) AS sample_titles
FROM picked p
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
    WHERE sa.dataset_id = p.id
    ORDER BY sa.source_sample_id
    LIMIT 30
  ) t
  WHERE t.sample_title IS NOT NULL
) st ON true
ORDER BY p.label, p.selection_rank
"""


class MetadataPilotError(ValueError):
    """Raised when the selection contract is incomplete or inconsistent."""


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_selection_spec(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MetadataPilotError("selection specification must be a JSON object")
    if raw.get("schema_version") != "omicsplorer-metadata-pilot-selection-v1":
        raise MetadataPilotError("unsupported selection schema_version")
    if not isinstance(raw.get("seed"), str) or not raw["seed"]:
        raise MetadataPilotError("selection seed must be a non-empty string")
    strata = raw.get("strata")
    if not isinstance(strata, list) or not strata:
        raise MetadataPilotError("selection strata must be a non-empty list")

    labels: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for stratum in strata:
        required = {
            "label",
            "source_db",
            "historical_extraction_version",
            "target_n",
        }
        if not isinstance(stratum, dict) or not required.issubset(stratum):
            raise MetadataPilotError("each stratum must define label, source, version, and target")
        label = str(stratum["label"])
        pair = (str(stratum["source_db"]), str(stratum["historical_extraction_version"]))
        if label in labels or pair in pairs:
            raise MetadataPilotError("stratum labels and source/version pairs must be unique")
        if not isinstance(stratum["target_n"], int) or stratum["target_n"] <= 0:
            raise MetadataPilotError("target_n must be a positive integer")
        labels.add(label)
        pairs.add(pair)
    return cast(dict[str, Any], raw)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def manifest_record(row: Mapping[str, Any], *, seed: str) -> dict[str, Any]:
    source_db = str(row["source_db"])
    source_id = str(row["source_id"])
    title = str(row.get("title") or "")
    abstract = str(row.get("abstract") or "")
    raw_metadata = _json_value(row.get("raw_metadata"))
    sample_titles = [str(value) for value in (row.get("sample_titles") or [])]
    n_samples = row.get("n_samples")
    source_input = {
        "title": title,
        "abstract": abstract,
        "raw_metadata": raw_metadata,
        "n_samples": n_samples,
        "sample_titles": sample_titles,
    }
    return {
        "schema_version": "omicsplorer-metadata-pilot-record-v1",
        "stratum": str(row["label"]),
        "source_db": source_db,
        "source_id": source_id,
        "historical_extraction_version": str(row["historical_extraction_version"]),
        "selection_rank": int(row["selection_rank"]),
        "selection_seed": seed,
        "record_key_sha256": hashlib.sha256(f"{source_db}:{source_id}".encode()).hexdigest(),
        "source_input_sha256": sha256_json(source_input),
        "input_presence": {
            "title": bool(title.strip()),
            "abstract": bool(abstract.strip()),
            "raw_metadata": raw_metadata not in (None, {}, [], ""),
            "n_samples_positive": isinstance(n_samples, int) and n_samples > 0,
            "sample_rows": int(row.get("sample_rows") or 0),
            "usable_sample_titles": len(sample_titles),
        },
    }


def validate_records(records: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> None:
    expected = {str(item["label"]): int(item["target_n"]) for item in spec["strata"]}
    observed = Counter(str(record["stratum"]) for record in records)
    if observed != Counter(expected):
        raise MetadataPilotError(f"stratum counts do not match target: {dict(observed)}")
    record_keys = [str(record["record_key_sha256"]) for record in records]
    if len(record_keys) != len(set(record_keys)):
        raise MetadataPilotError("selected records are not unique")


def public_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    spec: Mapping[str, Any],
    spec_sha256: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    strata: list[dict[str, Any]] = []
    for declared in spec["strata"]:
        label = str(declared["label"])
        chosen = [record for record in records if record["stratum"] == label]
        presence = [record["input_presence"] for record in chosen]
        strata.append(
            {
                "label": label,
                "selected_n": len(chosen),
                "title_present_n": sum(bool(item["title"]) for item in presence),
                "abstract_present_n": sum(bool(item["abstract"]) for item in presence),
                "raw_metadata_present_n": sum(bool(item["raw_metadata"]) for item in presence),
                "n_samples_positive_n": sum(bool(item["n_samples_positive"]) for item in presence),
                "records_with_sample_rows_n": sum(int(item["sample_rows"]) > 0 for item in presence),
                "records_with_usable_sample_titles_n": sum(
                    int(item["usable_sample_titles"]) > 0 for item in presence
                ),
            }
        )
    return {
        "schema_version": "omicsplorer-metadata-pilot-summary-v1",
        "protocol_version": spec["protocol_version"],
        "generated_at_utc": generated_at_utc,
        "selection_spec_sha256": spec_sha256,
        "interpretation": "input-availability feasibility only; no accuracy or effectiveness claim",
        "selected_total": len(records),
        "strata": strata,
    }


async def select_records(database_url: str, spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        async with connection.transaction(readonly=True):
            readonly = await connection.fetchval("SHOW transaction_read_only")
            if readonly != "on":
                raise MetadataPilotError("database transaction is not read-only")
            rows = await connection.fetch(
                PILOT_SELECTION_SQL,
                json.dumps(spec["strata"], ensure_ascii=False),
                spec["seed"],
            )
    finally:
        await connection.close()
    records = [manifest_record(dict(row), seed=str(spec["seed"])) for row in rows]
    validate_records(records, spec)
    return records


def write_private_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    path.chmod(0o600)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
