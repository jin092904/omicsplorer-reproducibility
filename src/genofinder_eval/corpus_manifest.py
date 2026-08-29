"""Export a hash-bound frozen corpus TSV and three-store evidence manifest."""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx

from genofinder_eval.cross_store_snapshot import (
    SCHEMA_VERSION as AUDIT_SCHEMA_VERSION,
)
from genofinder_eval.cross_store_snapshot import (
    canonical_json_sha256,
)

MANIFEST_SCHEMA_VERSION = "omicsplorer-store-evidence-v2"
ACKNOWLEDGEMENT = "I_CONFIRM_THE_AUDIT_IS_ZERO_MISMATCH_AND_PRE_EVALUATION"
TSV_FIELDS = (
    "source_db",
    "accession",
    "internal_dataset_id",
    "snapshot_id",
    "extraction_version",
    "extraction_lineage_id",
    "build_stage",
)
_DATABASE_RE = re.compile(r"^omicsplorer_frozen_[a-z0-9_]+_intersection$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,160}$")


class CorpusManifestError(RuntimeError):
    """Raised when frozen corpus evidence cannot be established."""


@dataclass(frozen=True)
class CorpusExport:
    row_count: int
    accession_membership_count: int
    dataset_id_set_sha256: str
    accession_membership_sha256: str
    tsv_sha256: str
    tsv_size_bytes: int
    schema_revision: str
    server_version: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusManifestError(f"{label} must be an object")
    return value


def _require_sha256(value: object, label: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise CorpusManifestError(f"{label} must be a full lowercase SHA-256")
    return text


def _validate_safe_id(value: str, label: str) -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise CorpusManifestError(f"{label} must be a safe immutable identifier")
    return value


def _validate_loopback_url(url: str, label: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise CorpusManifestError(f"{label} URL must use loopback HTTP(S)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CorpusManifestError(f"{label} URL must not contain credentials or parameters")
    return url.rstrip("/")


def validate_zero_mismatch_audit(audit: Mapping[str, Any], snapshot_id: str) -> None:
    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise CorpusManifestError("unsupported cross-store audit schema_version")
    if audit.get("snapshot_id") != snapshot_id:
        raise CorpusManifestError("audit snapshot_id differs from export snapshot_id")
    if audit.get("ready_for_frozen_corpus") is not True:
        raise CorpusManifestError("audit is not ready_for_frozen_corpus")
    if audit.get("blocking_reasons") != []:
        raise CorpusManifestError("audit contains blocking reasons")
    comparisons = _require_mapping(audit.get("comparisons"), "comparisons")
    if int(comparisons.get("cross_store_mismatch_count", -1)) != 0:
        raise CorpusManifestError("cross-store dataset-ID mismatch count is nonzero")
    if int(comparisons.get("membership_mismatch_id_count", -1)) != 0:
        raise CorpusManifestError("cross-store accession-membership mismatch count is nonzero")
    stores = _require_mapping(audit.get("stores"), "stores")
    parsed = [
        _require_mapping(stores.get(name), f"stores.{name}")
        for name in ("postgresql", "qdrant", "opensearch")
    ]
    counts = {int(store.get("unique_dataset_id_count", -1)) for store in parsed}
    id_hashes = {
        _require_sha256(store.get("dataset_id_set_sha256"), "dataset_id_set_sha256")
        for store in parsed
    }
    membership_hashes = {
        _require_sha256(
            store.get("accession_membership_sha256"),
            "accession_membership_sha256",
        )
        for store in parsed
    }
    if len(counts) != 1 or next(iter(counts)) < 1:
        raise CorpusManifestError("store unique-dataset counts differ or are empty")
    if len(id_hashes) != 1:
        raise CorpusManifestError("store dataset-ID hashes differ")
    if len(membership_hashes) != 1:
        raise CorpusManifestError("store accession-membership hashes differ")
    for name, store in zip(("postgresql", "qdrant", "opensearch"), parsed, strict=True):
        if int(store.get("native_count", -1)) != next(iter(counts)):
            raise CorpusManifestError(f"{name} native_count differs from unique count")
        for field in (
            "missing_identity_count",
            "duplicate_dataset_id_count",
            "conflicting_membership_count",
            "native_id_mismatch_count",
        ):
            if int(store.get(field, -1)) != 0:
                raise CorpusManifestError(f"{name} {field} is nonzero")


def _safe_tsv_value(value: object, label: str) -> str:
    text = "" if value is None else str(value)
    if not text or text.strip() != text or any(character in text for character in "\t\r\n"):
        raise CorpusManifestError(f"{label} is blank or unsafe for canonical TSV")
    return text


async def _database_identity(
    connection: asyncpg.Connection[Any], snapshot_id: str
) -> tuple[str, str, str]:
    row = await connection.fetchrow(
        """
        SELECT current_database() AS database_name,
               current_setting('server_version') AS server_version,
               COALESCE(
                   (
                       SELECT SPLIT_PART(config.setting, '=', 2)
                         FROM pg_db_role_setting AS settings
                         JOIN pg_database AS database ON database.oid = settings.setdatabase
                        CROSS JOIN LATERAL UNNEST(settings.setconfig) AS config(setting)
                        WHERE database.datname = current_database()
                          AND settings.setrole = 0
                          AND config.setting LIKE 'omicsplorer.evidence_snapshot_id=%'
                        LIMIT 1
                   ),
                   ''
               ) AS snapshot_marker
        """
    )
    if row is None:
        raise CorpusManifestError("database identity query returned no row")
    database_name = str(row["database_name"])
    marker = str(row["snapshot_marker"] or "")
    if not _DATABASE_RE.fullmatch(database_name):
        raise CorpusManifestError("database is not a named frozen intersection derivative")
    if marker != snapshot_id:
        raise CorpusManifestError("database-local snapshot marker differs from snapshot_id")
    return database_name, marker, str(row["server_version"])


async def export_corpus_tsv(
    connection: asyncpg.Connection[Any],
    output: Path,
    *,
    snapshot_id: str,
    schema_revision: str,
) -> CorpusExport:
    """Stream a canonical TSV and verify its identities inside one read-only snapshot."""

    _, _, server_version = await _database_identity(connection, snapshot_id)
    _validate_safe_id(schema_revision, "schema_revision")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    membership_digest = hashlib.sha256()
    row_count = 0
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_FIELDS)
            query = """
                SELECT source_db, source_id AS accession, id::text AS internal_dataset_id,
                       extraction_version, extraction_lineage_id, build_stage
                  FROM datasets
                 ORDER BY source_db, source_id, id::text
            """
            async for row in connection.cursor(query, prefetch=5000):
                values = (
                    _safe_tsv_value(row["source_db"], "source_db"),
                    _safe_tsv_value(row["accession"], "accession"),
                    _safe_tsv_value(row["internal_dataset_id"], "internal_dataset_id"),
                    snapshot_id,
                    _safe_tsv_value(row["extraction_version"], "extraction_version"),
                    _safe_tsv_value(row["extraction_lineage_id"], "extraction_lineage_id"),
                    _safe_tsv_value(row["build_stage"], "build_stage"),
                )
                writer.writerow(values)
                membership_digest.update("\t".join(values[:3]).encode("utf-8"))
                membership_digest.update(b"\n")
                row_count += 1
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    id_digest = hashlib.sha256()
    id_count = 0
    async for row in connection.cursor(
        "SELECT id::text AS dataset_id FROM datasets ORDER BY id::text", prefetch=5000
    ):
        dataset_id = _safe_tsv_value(row["dataset_id"], "dataset_id")
        id_digest.update(dataset_id.encode("utf-8"))
        id_digest.update(b"\n")
        id_count += 1
    unique_accessions = int(
        await connection.fetchval("SELECT COUNT(DISTINCT (source_db, source_id)) FROM datasets")
    )
    if id_count != row_count or unique_accessions != row_count:
        raise CorpusManifestError("dataset rows, IDs, and unique accessions are not one-to-one")
    output.chmod(0o600)
    return CorpusExport(
        row_count=row_count,
        accession_membership_count=row_count,
        dataset_id_set_sha256=id_digest.hexdigest(),
        accession_membership_sha256=membership_digest.hexdigest(),
        tsv_sha256=sha256_file(output),
        tsv_size_bytes=output.stat().st_size,
        schema_revision=schema_revision,
        server_version=server_version,
    )


def validate_export_against_audit(export: CorpusExport, audit: Mapping[str, Any]) -> None:
    stores = _require_mapping(audit.get("stores"), "stores")
    database = _require_mapping(stores.get("postgresql"), "stores.postgresql")
    expected = {
        "row_count": int(database["unique_dataset_id_count"]),
        "dataset_id_set_sha256": str(database["dataset_id_set_sha256"]),
        "accession_membership_sha256": str(database["accession_membership_sha256"]),
    }
    observed = {
        "row_count": export.row_count,
        "dataset_id_set_sha256": export.dataset_id_set_sha256,
        "accession_membership_sha256": export.accession_membership_sha256,
    }
    if observed != expected:
        raise CorpusManifestError("exported TSV identities differ from the zero-mismatch audit")


async def load_search_store_evidence(
    *,
    audit: Mapping[str, Any],
    qdrant_url: str,
    opensearch_url: str,
) -> dict[str, dict[str, Any]]:
    stores = _require_mapping(audit.get("stores"), "stores")
    audit_qdrant = _require_mapping(stores.get("qdrant"), "stores.qdrant")
    audit_opensearch = _require_mapping(stores.get("opensearch"), "stores.opensearch")
    qdrant_base = _validate_loopback_url(qdrant_url, "Qdrant")
    opensearch_base = _validate_loopback_url(opensearch_url, "OpenSearch")
    collection = str(audit_qdrant.get("collection") or "")
    index = str(audit_opensearch.get("index") or "")
    if not collection or not index:
        raise CorpusManifestError("audit collection or index is blank")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        q_root = (await client.get(f"{qdrant_base}/")).raise_for_status().json()
        q_info = (
            (await client.get(f"{qdrant_base}/collections/{collection}"))
            .raise_for_status()
            .json()["result"]
        )
        q_count = (
            (
                await client.post(
                    f"{qdrant_base}/collections/{collection}/points/count",
                    json={"exact": True},
                )
            )
            .raise_for_status()
            .json()["result"]["count"]
        )
        os_root = (await client.get(f"{opensearch_base}/")).raise_for_status().json()
        os_count = (await client.get(f"{opensearch_base}/{index}/_count")).raise_for_status().json()
        os_mapping = (
            (await client.get(f"{opensearch_base}/{index}/_mapping")).raise_for_status().json()
        )
        os_settings = (
            (
                await client.get(
                    f"{opensearch_base}/{index}/_settings",
                    params={"flat_settings": "true", "include_defaults": "false"},
                )
            )
            .raise_for_status()
            .json()
        )
    q_version = str(q_root.get("version") or "")
    os_version = str(os_root.get("version", {}).get("number") or "")
    if q_version != str(audit_qdrant.get("version") or ""):
        raise CorpusManifestError("live Qdrant version differs from audit")
    if os_version != str(audit_opensearch.get("version") or ""):
        raise CorpusManifestError("live OpenSearch version differs from audit")
    if str(q_info.get("status") or "") != "green":
        raise CorpusManifestError("Qdrant collection is not green")
    if int(q_count) != int(audit_qdrant["native_count"]):
        raise CorpusManifestError("live Qdrant exact count differs from audit")
    if int(os_count["count"]) != int(audit_opensearch["native_count"]):
        raise CorpusManifestError("live OpenSearch count differs from audit")
    if int(os_count.get("_shards", {}).get("failed", 0)) != 0:
        raise CorpusManifestError("OpenSearch count reports a failed shard")
    vector_hash = canonical_json_sha256(q_info["config"]["params"]["vectors"])
    if vector_hash != audit_qdrant.get("vector_configuration_sha256"):
        raise CorpusManifestError("live Qdrant vector configuration differs from audit")
    mapping_hash = canonical_json_sha256(os_mapping)
    if mapping_hash != audit_opensearch.get("mapping_sha256"):
        raise CorpusManifestError("live OpenSearch mapping differs from audit")
    return {
        "qdrant": {
            "version": q_version,
            "collection": collection,
            "point_count": int(q_count),
            "collection_config_sha256": canonical_json_sha256(q_info["config"]),
        },
        "opensearch": {
            "version": os_version,
            "index": index,
            "document_count": int(os_count["count"]),
            "mapping_sha256": mapping_hash,
            "settings_sha256": canonical_json_sha256(os_settings),
        },
    }


def build_stores_manifest(
    *,
    snapshot_id: str,
    qdrant_snapshot_id: str,
    opensearch_snapshot_id: str,
    audit: Mapping[str, Any],
    audit_sha256: str,
    export: CorpusExport,
    search_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    validate_zero_mismatch_audit(audit, snapshot_id)
    validate_export_against_audit(export, audit)
    _validate_safe_id(qdrant_snapshot_id, "qdrant_snapshot_id")
    _validate_safe_id(opensearch_snapshot_id, "opensearch_snapshot_id")
    audit_stores = _require_mapping(audit.get("stores"), "stores")
    q_audit = _require_mapping(audit_stores.get("qdrant"), "stores.qdrant")
    os_audit = _require_mapping(audit_stores.get("opensearch"), "stores.opensearch")
    q_live = _require_mapping(search_evidence.get("qdrant"), "search_evidence.qdrant")
    os_live = _require_mapping(search_evidence.get("opensearch"), "search_evidence.opensearch")
    common = {
        "dataset_id_set_sha256": export.dataset_id_set_sha256,
        "accession_membership_sha256": export.accession_membership_sha256,
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "source_cross_store_audit_sha256": _require_sha256(
            audit_sha256, "source_cross_store_audit_sha256"
        ),
        "database": {
            "snapshot_id": snapshot_id,
            "server_version": export.server_version,
            "row_count": export.row_count,
            "accession_membership_count": export.accession_membership_count,
            **common,
            "schema_revision": export.schema_revision,
        },
        "qdrant": {
            "snapshot_id": qdrant_snapshot_id,
            "version": str(q_live["version"]),
            "collection": str(q_live["collection"]),
            "point_count": int(q_live["point_count"]),
            "dataset_id_set_sha256": str(q_audit["dataset_id_set_sha256"]),
            "accession_membership_sha256": str(q_audit["accession_membership_sha256"]),
            "collection_config_sha256": _require_sha256(
                q_live["collection_config_sha256"], "collection_config_sha256"
            ),
        },
        "opensearch": {
            "snapshot_id": opensearch_snapshot_id,
            "version": str(os_live["version"]),
            "index": str(os_live["index"]),
            "document_count": int(os_live["document_count"]),
            "dataset_id_set_sha256": str(os_audit["dataset_id_set_sha256"]),
            "accession_membership_sha256": str(os_audit["accession_membership_sha256"]),
            "mapping_sha256": _require_sha256(os_live["mapping_sha256"], "mapping_sha256"),
            "settings_sha256": _require_sha256(os_live["settings_sha256"], "settings_sha256"),
        },
        "cross_store_mismatch_count": 0,
        "accession_membership_mismatch_count": 0,
        "evidence_boundary": (
            "This manifest establishes identity consistency for one frozen derivative. "
            "It does not establish metadata accuracy, retrieval quality, latency, or superiority."
        ),
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def write_deterministic_gzip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as archive:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    archive.write(chunk)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    output.chmod(0o600)


def _read_object(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CorpusManifestError("audit must be a JSON object")
    return raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--schema-revision", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--qdrant-snapshot-id", required=True)
    parser.add_argument("--opensearch-url", required=True)
    parser.add_argument("--opensearch-snapshot-id", required=True)
    parser.add_argument("--accessions-output", type=Path, required=True)
    parser.add_argument("--gzip-output", type=Path, required=True)
    parser.add_argument("--stores-output", type=Path, required=True)
    parser.add_argument("--acknowledgement", required=True)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    if args.acknowledgement != ACKNOWLEDGEMENT:
        raise CorpusManifestError(f"--acknowledgement must equal {ACKNOWLEDGEMENT!r}")
    snapshot_id = _validate_safe_id(args.snapshot_id, "snapshot_id")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise CorpusManifestError("DATABASE_URL is not set")
    audit = _read_object(args.audit)
    validate_zero_mismatch_audit(audit, snapshot_id)
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            export = await export_corpus_tsv(
                connection,
                args.accessions_output,
                snapshot_id=snapshot_id,
                schema_revision=args.schema_revision,
            )
    finally:
        await connection.close()
    validate_export_against_audit(export, audit)
    search_evidence = await load_search_store_evidence(
        audit=audit,
        qdrant_url=args.qdrant_url,
        opensearch_url=args.opensearch_url,
    )
    manifest = build_stores_manifest(
        snapshot_id=snapshot_id,
        qdrant_snapshot_id=args.qdrant_snapshot_id,
        opensearch_snapshot_id=args.opensearch_snapshot_id,
        audit=audit,
        audit_sha256=sha256_file(args.audit),
        export=export,
        search_evidence=search_evidence,
    )
    write_json(args.stores_output, manifest)
    write_deterministic_gzip(args.accessions_output, args.gzip_output)
    print(f"corpus_rows={export.row_count}")
    print(f"corpus_tsv_sha256={export.tsv_sha256}")
    print(f"corpus_tsv_size_bytes={export.tsv_size_bytes}")
    print(f"corpus_gzip_sha256={sha256_file(args.gzip_output)}")
    print(f"corpus_gzip_size_bytes={args.gzip_output.stat().st_size}")
    print(f"stores_manifest_sha256={sha256_file(args.stores_output)}")
    print("cross_store_mismatch_count=0")
    print("accession_membership_mismatch_count=0")
    return 0


def main() -> int:
    return asyncio.run(async_main())
