"""Read-only deployment preflight for frozen-release evidence collection.

This module deliberately reports readiness only.  It does not create snapshots,
export corpus rows, calculate cross-store membership hashes, or contact the search
endpoint.  Connection strings and credentials are read from environment variables
and are never included in the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import asyncpg
import httpx

Status = Literal["ready", "blocked", "unreachable", "not_configured"]

REQUIRED_DATASET_COLUMNS = frozenset(
    {
        "id",
        "source_db",
        "source_id",
        "extraction_version",
        "extraction_lineage_id",
        "build_stage",
    }
)


@dataclass(frozen=True)
class ComponentResult:
    component: str
    status: Status
    checks: dict[str, bool]
    blockers: list[str]
    observations: dict[str, int] | None = None


def assess_dataset_columns(columns: set[str]) -> ComponentResult:
    """Assess whether PostgreSQL can supply the accession-lineage manifest."""

    missing = sorted(REQUIRED_DATASET_COLUMNS - columns)
    return ComponentResult(
        component="postgresql",
        status="ready" if not missing else "blocked",
        checks={
            "datasets_table_found": bool(columns),
            "required_accession_lineage_columns_found": not missing,
        },
        blockers=[f"missing datasets column: {name}" for name in missing],
    )


def assess_dataset_values(observations: dict[str, int]) -> ComponentResult:
    """Assess aggregate completeness without exposing any corpus row values."""

    total = observations["row_count"]
    blockers: list[str] = []
    if total == 0:
        blockers.append("datasets table is empty")
    labels = {
        "invalid_identity_count": "rows with a missing dataset identity",
        "missing_extraction_version_count": "rows missing extraction_version",
        "missing_extraction_lineage_id_count": "rows missing extraction_lineage_id",
        "missing_build_stage_count": "rows missing build_stage",
        "duplicate_accession_count": "duplicate source_db/source_id accessions",
    }
    for key, label in labels.items():
        count = observations[key]
        if count:
            blockers.append(f"{label}: {count}")
    return ComponentResult(
        component="postgresql",
        status="ready" if not blockers else "blocked",
        checks={
            "corpus_is_nonempty": total > 0,
            "row_identity_complete": observations["invalid_identity_count"] == 0,
            "row_lineage_complete": (
                observations["missing_extraction_version_count"] == 0
                and observations["missing_extraction_lineage_id_count"] == 0
                and observations["missing_build_stage_count"] == 0
            ),
            "accessions_are_unique": observations["duplicate_accession_count"] == 0,
        },
        blockers=blockers,
        observations=observations,
    )


def _not_configured(component: str, variable: str) -> ComponentResult:
    return ComponentResult(
        component=component,
        status="not_configured",
        checks={"connection_configured": False},
        blockers=[f"environment variable {variable} is not set"],
    )


def _unreachable(component: str, reason: str) -> ComponentResult:
    return ComponentResult(
        component=component,
        status="unreachable",
        checks={"connection_configured": True, "read_probe_succeeded": False},
        blockers=[reason],
    )


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def probe_postgresql(database_url: str | None) -> ComponentResult:
    if not database_url:
        return _not_configured("postgresql", "DATABASE_URL")
    connection: asyncpg.Connection[Any] | None = None
    try:
        connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=5)
        records = await connection.fetch(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'datasets'
            """
        )
        columns = {str(record["column_name"]) for record in records}
        assessed = assess_dataset_columns(columns)
        if assessed.status != "ready":
            return ComponentResult(
                component=assessed.component,
                status=assessed.status,
                checks={
                    "connection_configured": True,
                    "read_probe_succeeded": True,
                    **assessed.checks,
                },
                blockers=assessed.blockers,
            )
        row = await connection.fetchrow(
            """
            SELECT COUNT(*)::bigint AS row_count,
                   COUNT(*) FILTER (
                       WHERE id IS NULL
                          OR NULLIF(BTRIM(source_db), '') IS NULL
                          OR NULLIF(BTRIM(source_id), '') IS NULL
                   )::bigint AS invalid_identity_count,
                   COUNT(*) FILTER (
                       WHERE NULLIF(BTRIM(extraction_version), '') IS NULL
                   )::bigint AS missing_extraction_version_count,
                   COUNT(*) FILTER (
                       WHERE NULLIF(BTRIM(extraction_lineage_id), '') IS NULL
                   )::bigint AS missing_extraction_lineage_id_count,
                   COUNT(*) FILTER (
                       WHERE NULLIF(BTRIM(build_stage), '') IS NULL
                   )::bigint AS missing_build_stage_count,
                   (
                       COUNT(*) - COUNT(DISTINCT (source_db, source_id))
                   )::bigint AS duplicate_accession_count
              FROM datasets
            """
        )
        if row is None:
            return ComponentResult(
                component="postgresql",
                status="blocked",
                checks={"connection_configured": True, "read_probe_succeeded": False},
                blockers=["aggregate dataset completeness query returned no row"],
            )
        values = assess_dataset_values(
            {
                key: int(row[key])
                for key in (
                    "row_count",
                    "invalid_identity_count",
                    "missing_extraction_version_count",
                    "missing_extraction_lineage_id_count",
                    "missing_build_stage_count",
                    "duplicate_accession_count",
                )
            }
        )
        return ComponentResult(
            component=values.component,
            status=values.status,
            checks={
                "connection_configured": True,
                "read_probe_succeeded": True,
                **assessed.checks,
                **values.checks,
            },
            blockers=values.blockers,
            observations=values.observations,
        )
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        return _unreachable("postgresql", f"read probe failed: {type(exc).__name__}")
    finally:
        if connection is not None:
            await connection.close()


async def probe_qdrant(url: str | None, collection: str) -> ComponentResult:
    if not url:
        return _not_configured("qdrant", "QDRANT_URL")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{url.rstrip('/')}/collections/{collection}")
        if response.status_code != 200:
            return ComponentResult(
                component="qdrant",
                status="blocked",
                checks={"connection_configured": True, "collection_found": False},
                blockers=[f"configured collection was not readable (HTTP {response.status_code})"],
            )
        body = response.json()
        found = isinstance(body, dict) and isinstance(body.get("result"), dict)
        return ComponentResult(
            component="qdrant",
            status="ready" if found else "blocked",
            checks={"connection_configured": True, "collection_found": found},
            blockers=[] if found else ["collection response did not contain a result object"],
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _unreachable("qdrant", f"read probe failed: {type(exc).__name__}")


async def probe_opensearch(
    url: str | None,
    index: str,
    username: str | None,
    password: str | None,
) -> ComponentResult:
    if not url:
        return _not_configured("opensearch", "OPENSEARCH_URL")
    auth = (username or "admin", password) if password else None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{url.rstrip('/')}/{index}/_count", auth=auth)
        if response.status_code != 200:
            return ComponentResult(
                component="opensearch",
                status="blocked",
                checks={"connection_configured": True, "index_found": False},
                blockers=[f"configured index was not readable (HTTP {response.status_code})"],
            )
        body = response.json()
        found = isinstance(body, dict) and isinstance(body.get("count"), int)
        return ComponentResult(
            component="opensearch",
            status="ready" if found else "blocked",
            checks={"connection_configured": True, "index_found": found},
            blockers=[] if found else ["index response did not contain an integer count"],
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _unreachable("opensearch", f"read probe failed: {type(exc).__name__}")


def build_report(results: list[ComponentResult]) -> dict[str, Any]:
    blockers = [
        f"{result.component}: {blocker}" for result in results for blocker in result.blockers
    ]
    return {
        "schema_version": "omicsplorer-evidence-preflight-v1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "ready_for_evidence_collection": all(result.status == "ready" for result in results),
        "components": [asdict(result) for result in results],
        "blocking_reasons": blockers,
        "evidence_boundary": (
            "This read-only preflight is not corpus, snapshot, model, cross-store, "
            "retrieval-quality, latency, or RELEASE GO evidence."
        ),
        "next_required_artifacts": [
            "corpus-accessions.tsv with row-level extraction lineage",
            "immutable PostgreSQL, Qdrant, and OpenSearch snapshot identifiers",
            "cross-store canonical dataset-ID hashes and zero mismatch count",
            "metadata-structuring lineage assets and immutable model digests",
            "canonical effective-server-config.json and eligible per-request traces",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether a deployment can begin frozen evidence collection."
    )
    parser.add_argument("--qdrant-collection", default="datasets_v2")
    parser.add_argument("--opensearch-index", default="datasets_v2")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    results = await asyncio.gather(
        probe_postgresql(os.getenv("DATABASE_URL")),
        probe_qdrant(os.getenv("QDRANT_URL"), args.qdrant_collection),
        probe_opensearch(
            os.getenv("OPENSEARCH_URL"),
            args.opensearch_index,
            os.getenv("OPENSEARCH_USERNAME"),
            os.getenv("OPENSEARCH_PASSWORD"),
        ),
    )
    report = build_report(list(results))
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["ready_for_evidence_collection"] else 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
