"""Audit dataset identity across isolated PostgreSQL, Qdrant, and OpenSearch stores."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx

SCHEMA_VERSION = "omicsplorer-cross-store-snapshot-audit-v1"
PRIVATE_SCHEMA_VERSION = "omicsplorer-cross-store-private-mismatches-v1"
ACKNOWLEDGEMENT = "I_CONFIRM_THESE_ARE_ISOLATED_FROZEN_STORES"
_DATABASE_RE = re.compile(r"^omicsplorer_frozen_[a-z0-9_]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
_MEMBERSHIP_FIELDS = ("dataset_id", "source_db", "source_id")


class CrossStoreAuditError(RuntimeError):
    """Raised when the audit cannot establish its declared read-only boundary."""


@dataclass
class StoreSnapshot:
    """In-memory identity view for one store; values remain private."""

    name: str
    native_count: int
    scanned_count: int = 0
    ids: set[str] = field(default_factory=set)
    memberships: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    missing_identity_count: int = 0
    duplicate_dataset_id_count: int = 0
    conflicting_membership_count: int = 0
    native_id_mismatch_count: int = 0

    def add(
        self,
        *,
        native_id: object,
        dataset_id: object,
        source_db: object,
        source_id: object,
    ) -> None:
        self.scanned_count += 1
        native = _clean(native_id)
        dataset = _clean(dataset_id)
        source = _clean(source_db)
        accession = _clean(source_id)
        if not dataset or not source or not accession:
            self.missing_identity_count += 1
            return
        if native and native != dataset:
            self.native_id_mismatch_count += 1
        membership = (source, accession, dataset)
        if dataset in self.ids:
            self.duplicate_dataset_id_count += 1
            if self.memberships.get(dataset) != membership:
                self.conflicting_membership_count += 1
            return
        self.ids.add(dataset)
        self.memberships[dataset] = membership


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def canonical_lines_sha256(lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for line in sorted(lines):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def canonical_membership_sha256(values: Iterable[tuple[str, str, str]]) -> str:
    return canonical_lines_sha256("\t".join(value) for value in values)


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _validate_loopback_url(url: str, *, label: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise CrossStoreAuditError(f"{label} URL must use a loopback HTTP(S) host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CrossStoreAuditError(f"{label} URL must not embed credentials, query, or fragment")
    return url.rstrip("/")


def _validate_snapshot_identity(database_name: str, marker: str, snapshot_id: str) -> None:
    if not _DATABASE_RE.fullmatch(database_name):
        raise CrossStoreAuditError("database name does not identify an isolated frozen database")
    if not _SAFE_ID_RE.fullmatch(snapshot_id):
        raise CrossStoreAuditError("snapshot_id must be a safe identifier of 8-128 characters")
    if marker != snapshot_id:
        raise CrossStoreAuditError("database-local snapshot marker differs from snapshot_id")


async def load_postgresql(
    database_url: str, *, snapshot_id: str
) -> tuple[StoreSnapshot, dict[str, Any]]:
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            identity = await connection.fetchrow(
                """
                SELECT current_database() AS database_name,
                       COALESCE(
                           (
                               SELECT SPLIT_PART(config.setting, '=', 2)
                                 FROM pg_db_role_setting AS settings
                                 JOIN pg_database AS database
                                   ON database.oid = settings.setdatabase
                                CROSS JOIN LATERAL UNNEST(settings.setconfig)
                                   AS config(setting)
                                WHERE database.datname = current_database()
                                  AND settings.setrole = 0
                                  AND config.setting LIKE
                                      'omicsplorer.evidence_snapshot_id=%'
                                LIMIT 1
                           ),
                           ''
                       ) AS snapshot_marker
                """
            )
            if identity is None:
                raise CrossStoreAuditError("PostgreSQL identity query returned no row")
            _validate_snapshot_identity(
                str(identity["database_name"]),
                str(identity["snapshot_marker"]),
                snapshot_id,
            )
            server_version = str(await connection.fetchval("SHOW server_version"))
            native_count = int(await connection.fetchval("SELECT COUNT(*) FROM datasets"))
            snapshot = StoreSnapshot("postgresql", native_count)
            query = """
                SELECT id::text AS native_id, id::text AS dataset_id, source_db, source_id
                  FROM datasets
                 ORDER BY id::text
            """
            async for row in connection.cursor(query, prefetch=5000):
                snapshot.add(
                    native_id=row["native_id"],
                    dataset_id=row["dataset_id"],
                    source_db=row["source_db"],
                    source_id=row["source_id"],
                )
            return snapshot, {
                "database_name": str(identity["database_name"]),
                "database_local_snapshot_marker": str(identity["snapshot_marker"]),
                "server_version": server_version,
            }
    finally:
        await connection.close()


async def load_qdrant(
    url: str,
    *,
    collection: str,
    expected_version: str,
    page_size: int,
) -> tuple[StoreSnapshot, dict[str, Any]]:
    base_url = _validate_loopback_url(url, label="Qdrant")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        root_response = await client.get(f"{base_url}/")
        root_response.raise_for_status()
        root = root_response.json()
        version = str(root.get("version") or "")
        if version != expected_version:
            raise CrossStoreAuditError(
                f"Qdrant version {version!r} differs from expected {expected_version!r}"
            )
        info_response = await client.get(f"{base_url}/collections/{collection}")
        info_response.raise_for_status()
        info = info_response.json()["result"]
        if str(info["status"]) != "green":
            raise CrossStoreAuditError("Qdrant collection status is not green")
        count_response = await client.post(
            f"{base_url}/collections/{collection}/points/count",
            json={"exact": True},
        )
        count_response.raise_for_status()
        native_count = int(count_response.json()["result"]["count"])
        snapshot = StoreSnapshot("qdrant", native_count)
        offset: object | None = None
        seen_offsets: set[str] = set()
        while True:
            payload: dict[str, Any] = {
                "limit": page_size,
                "with_payload": list(_MEMBERSHIP_FIELDS),
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = await client.post(
                f"{base_url}/collections/{collection}/points/scroll",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()["result"]
            points = result["points"]
            for point in points:
                values = point.get("payload") or {}
                snapshot.add(
                    native_id=point.get("id"),
                    dataset_id=values.get("dataset_id"),
                    source_db=values.get("source_db"),
                    source_id=values.get("source_id"),
                )
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                break
            key = json.dumps(next_offset, sort_keys=True)
            if key in seen_offsets:
                raise CrossStoreAuditError("Qdrant scroll repeated an offset")
            seen_offsets.add(key)
            offset = next_offset
        metadata = {
            "version": version,
            "collection": collection,
            "status": str(info["status"]),
            "reported_points_count": int(info["points_count"]),
            "vector_configuration_sha256": canonical_json_sha256(
                info["config"]["params"]["vectors"]
            ),
        }
        return snapshot, metadata


async def load_opensearch(
    url: str,
    *,
    index: str,
    expected_version: str,
    page_size: int,
) -> tuple[StoreSnapshot, dict[str, Any]]:
    base_url = _validate_loopback_url(url, label="OpenSearch")
    scroll_id: str | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        root_response = await client.get(f"{base_url}/")
        root_response.raise_for_status()
        root = root_response.json()
        version = str(root.get("version", {}).get("number") or "")
        if version != expected_version:
            raise CrossStoreAuditError(
                f"OpenSearch version {version!r} differs from expected {expected_version!r}"
            )
        count_response = await client.get(f"{base_url}/{index}/_count")
        count_response.raise_for_status()
        count_body = count_response.json()
        if int(count_body.get("_shards", {}).get("failed", 0)):
            raise CrossStoreAuditError("OpenSearch count reported a failed shard")
        native_count = int(count_body["count"])
        health_response = await client.get(f"{base_url}/_cluster/health/{index}")
        health_response.raise_for_status()
        health = health_response.json()
        mapping_response = await client.get(f"{base_url}/{index}/_mapping")
        mapping_response.raise_for_status()
        mapping = mapping_response.json()
        snapshot = StoreSnapshot("opensearch", native_count)
        try:
            response = await client.post(
                f"{base_url}/{index}/_search",
                params={"scroll": "5m"},
                json={
                    "size": page_size,
                    "sort": ["_doc"],
                    "track_total_hits": True,
                    "_source": list(_MEMBERSHIP_FIELDS),
                    "query": {"match_all": {}},
                },
            )
            response.raise_for_status()
            while True:
                body = response.json()
                scroll_id = str(body.get("_scroll_id") or scroll_id or "") or None
                if int(body.get("_shards", {}).get("failed", 0)):
                    raise CrossStoreAuditError("OpenSearch scroll reported a failed shard")
                hits = body["hits"]["hits"]
                if not hits:
                    break
                for hit in hits:
                    values = hit.get("_source") or {}
                    snapshot.add(
                        native_id=hit.get("_id"),
                        dataset_id=values.get("dataset_id"),
                        source_db=values.get("source_db"),
                        source_id=values.get("source_id"),
                    )
                if not scroll_id:
                    raise CrossStoreAuditError("OpenSearch scroll response omitted _scroll_id")
                response = await client.post(
                    f"{base_url}/_search/scroll",
                    json={"scroll": "5m", "scroll_id": scroll_id},
                )
                response.raise_for_status()
        finally:
            if scroll_id:
                cleanup = await client.request(
                    "DELETE",
                    f"{base_url}/_search/scroll",
                    json={"scroll_id": [scroll_id]},
                )
                cleanup.raise_for_status()
        metadata = {
            "version": version,
            "distribution": str(root.get("version", {}).get("distribution") or ""),
            "lucene_version": str(root.get("version", {}).get("lucene_version") or ""),
            "cluster_uuid": str(root.get("cluster_uuid") or ""),
            "index": index,
            "index_health": str(health.get("status") or ""),
            "active_primary_shards": int(health.get("active_primary_shards", 0)),
            "unassigned_shards": int(health.get("unassigned_shards", 0)),
            "mapping_sha256": canonical_json_sha256(mapping),
        }
        return snapshot, metadata


def _store_evidence(snapshot: StoreSnapshot, metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(metadata),
        "native_count": snapshot.native_count,
        "scanned_count": snapshot.scanned_count,
        "unique_dataset_id_count": len(snapshot.ids),
        "dataset_id_set_sha256": canonical_lines_sha256(snapshot.ids),
        "accession_membership_sha256": canonical_membership_sha256(
            snapshot.memberships.values()
        ),
        "missing_identity_count": snapshot.missing_identity_count,
        "duplicate_dataset_id_count": snapshot.duplicate_dataset_id_count,
        "conflicting_membership_count": snapshot.conflicting_membership_count,
        "native_id_mismatch_count": snapshot.native_id_mismatch_count,
    }


def _pairwise(left: StoreSnapshot, right: StoreSnapshot) -> dict[str, int]:
    return {
        f"{left.name}_only_count": len(left.ids - right.ids),
        f"{right.name}_only_count": len(right.ids - left.ids),
        "symmetric_difference_count": len(left.ids ^ right.ids),
    }


def build_report(
    *,
    snapshot_id: str,
    postgresql: StoreSnapshot,
    qdrant: StoreSnapshot,
    opensearch: StoreSnapshot,
    postgresql_metadata: Mapping[str, Any] | None = None,
    qdrant_metadata: Mapping[str, Any] | None = None,
    opensearch_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stores = (postgresql, qdrant, opensearch)
    blockers: list[str] = []
    for store in stores:
        if store.scanned_count != store.native_count:
            blockers.append(f"{store.name} scanned_count differs from native_count")
        for field_name in (
            "missing_identity_count",
            "duplicate_dataset_id_count",
            "conflicting_membership_count",
            "native_id_mismatch_count",
        ):
            if getattr(store, field_name):
                blockers.append(f"{store.name} {field_name} is nonzero")

    union = set().union(*(store.ids for store in stores))
    intersection = set.intersection(*(store.ids for store in stores))
    cross_store_mismatch_count = len(union - intersection)
    if cross_store_mismatch_count:
        blockers.append("dataset-ID sets differ across stores")
    membership_mismatch_ids = {
        dataset_id
        for dataset_id in intersection
        if len({store.memberships[dataset_id] for store in stores}) != 1
    }
    if membership_mismatch_ids:
        blockers.append("accession memberships differ across stores")

    report = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "ready_for_frozen_corpus": not blockers,
        "stores": {
            "postgresql": _store_evidence(postgresql, postgresql_metadata or {}),
            "qdrant": _store_evidence(qdrant, qdrant_metadata or {}),
            "opensearch": _store_evidence(opensearch, opensearch_metadata or {}),
        },
        "comparisons": {
            "postgresql_vs_qdrant": _pairwise(postgresql, qdrant),
            "postgresql_vs_opensearch": _pairwise(postgresql, opensearch),
            "qdrant_vs_opensearch": _pairwise(qdrant, opensearch),
            "cross_store_mismatch_count": cross_store_mismatch_count,
            "membership_mismatch_id_count": len(membership_mismatch_ids),
        },
        "blocking_reasons": blockers,
        "evidence_boundary": (
            "This read-only audit checks identity and accession membership in isolated stores. "
            "It does not establish metadata accuracy, retrieval quality, latency, or superiority."
        ),
    }
    private = {
        "schema_version": PRIVATE_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "do_not_publish_without_review": True,
        "dataset_id_differences": {
            "postgresql_not_qdrant": sorted(postgresql.ids - qdrant.ids),
            "qdrant_not_postgresql": sorted(qdrant.ids - postgresql.ids),
            "postgresql_not_opensearch": sorted(postgresql.ids - opensearch.ids),
            "opensearch_not_postgresql": sorted(opensearch.ids - postgresql.ids),
            "qdrant_not_opensearch": sorted(qdrant.ids - opensearch.ids),
            "opensearch_not_qdrant": sorted(opensearch.ids - qdrant.ids),
        },
        "membership_mismatches": {
            dataset_id: {
                store.name: list(store.memberships[dataset_id]) for store in stores
            }
            for dataset_id in sorted(membership_mismatch_ids)
        },
    }
    return report, private


def _write_json(path: Path, value: Mapping[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private:
        path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--qdrant-collection", default="datasets_v2")
    parser.add_argument("--qdrant-version", required=True)
    parser.add_argument("--opensearch-url", required=True)
    parser.add_argument("--opensearch-index", default="datasets_v2")
    parser.add_argument("--opensearch-version", required=True)
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-mismatches", type=Path, required=True)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    if args.acknowledgement != ACKNOWLEDGEMENT:
        raise CrossStoreAuditError(f"--acknowledgement must equal {ACKNOWLEDGEMENT!r}")
    if not 1 <= args.page_size <= 10_000:
        raise CrossStoreAuditError("--page-size must be between 1 and 10000")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise CrossStoreAuditError("DATABASE_URL is not set")
    postgresql, postgresql_metadata = await load_postgresql(
        database_url, snapshot_id=args.snapshot_id
    )
    qdrant, qdrant_metadata = await load_qdrant(
        args.qdrant_url,
        collection=args.qdrant_collection,
        expected_version=args.qdrant_version,
        page_size=args.page_size,
    )
    opensearch, opensearch_metadata = await load_opensearch(
        args.opensearch_url,
        index=args.opensearch_index,
        expected_version=args.opensearch_version,
        page_size=args.page_size,
    )
    report, private = build_report(
        snapshot_id=args.snapshot_id,
        postgresql=postgresql,
        qdrant=qdrant,
        opensearch=opensearch,
        postgresql_metadata=postgresql_metadata,
        qdrant_metadata=qdrant_metadata,
        opensearch_metadata=opensearch_metadata,
    )
    _write_json(args.output, report, private=True)
    _write_json(args.private_mismatches, private, private=True)
    print(f"postgresql_rows={postgresql.scanned_count}")
    print(f"qdrant_points={qdrant.scanned_count}")
    print(f"opensearch_documents={opensearch.scanned_count}")
    print(f"cross_store_mismatch_count={report['comparisons']['cross_store_mismatch_count']}")
    print(f"ready_for_frozen_corpus={str(report['ready_for_frozen_corpus']).lower()}")
    return 0 if report["ready_for_frozen_corpus"] else 2


def main() -> int:
    return asyncio.run(async_main())
