"""Plan and apply a common-store corpus derivative in an isolated database.

The source PostgreSQL snapshot is never modified.  Operators first clone it to
an isolated database whose name ends in ``_intersection`` and give that clone a
distinct database-local marker.  Planning is read-only.  Applying a reviewed,
hash-bound plan removes only PostgreSQL rows proven absent from both frozen
search stores.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from genofinder_eval.cross_store_snapshot import (
    PRIVATE_SCHEMA_VERSION,
    canonical_lines_sha256,
    canonical_membership_sha256,
)
from genofinder_eval.cross_store_snapshot import (
    SCHEMA_VERSION as AUDIT_SCHEMA_VERSION,
)

PLAN_SCHEMA_VERSION = "omicsplorer-intersection-derivative-plan-v1"
REPORT_SCHEMA_VERSION = "omicsplorer-intersection-derivative-report-v1"
ACKNOWLEDGEMENT = "I_CONFIRM_THIS_IS_A_DERIVATIVE_INTERSECTION_DATABASE"
INCLUSION_RULE = (
    "Retain a dataset only when its internal dataset ID and accession membership "
    "were present in PostgreSQL, Qdrant, and OpenSearch in the pre-evaluation audit."
)
_DATABASE_RE = re.compile(r"^omicsplorer_frozen_[a-z0-9_]+_intersection$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class IntersectionDerivativeError(RuntimeError):
    """Raised when an intersection-derivative safety condition fails."""


@dataclass(frozen=True)
class DatasetObservation:
    database_name: str
    snapshot_marker: str
    row_count: int
    dataset_id_set_sha256: str
    accession_membership_sha256: str
    ids: frozenset[str]
    memberships: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class ReferenceEffect:
    child_table: str
    child_column: str
    on_delete: str
    affected_rows: int


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntersectionDerivativeError(f"{label} must be an object")
    return value


def _require_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IntersectionDerivativeError(f"{label} must be a string list")
    return value


def _validated_uuid_set(values: Sequence[str]) -> frozenset[str]:
    normalized: list[str] = []
    for value in values:
        try:
            parsed = uuid.UUID(value)
        except ValueError as exc:
            raise IntersectionDerivativeError(
                "private mismatch file contains a non-UUID ID"
            ) from exc
        normalized.append(str(parsed))
    if len(set(normalized)) != len(normalized):
        raise IntersectionDerivativeError("private mismatch file contains duplicate IDs")
    return frozenset(normalized)


def validate_audit_inputs(audit: Mapping[str, Any], private: Mapping[str, Any]) -> frozenset[str]:
    """Return the only allowed exclusion set after validating both audit files."""

    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise IntersectionDerivativeError("unsupported cross-store audit schema_version")
    if private.get("schema_version") != PRIVATE_SCHEMA_VERSION:
        raise IntersectionDerivativeError("unsupported private mismatch schema_version")
    source_snapshot_id = str(audit.get("snapshot_id") or "")
    if private.get("snapshot_id") != source_snapshot_id:
        raise IntersectionDerivativeError("audit and private mismatch snapshot IDs differ")

    differences = _require_mapping(private.get("dataset_id_differences"), "dataset_id_differences")
    pg_qdrant = _require_string_list(
        differences.get("postgresql_not_qdrant"), "postgresql_not_qdrant"
    )
    pg_opensearch = _require_string_list(
        differences.get("postgresql_not_opensearch"), "postgresql_not_opensearch"
    )
    if sorted(pg_qdrant) != sorted(pg_opensearch):
        raise IntersectionDerivativeError(
            "PostgreSQL-only IDs are not identical for Qdrant and OpenSearch"
        )
    for key in (
        "qdrant_not_postgresql",
        "opensearch_not_postgresql",
        "qdrant_not_opensearch",
        "opensearch_not_qdrant",
    ):
        if _require_string_list(differences.get(key), key):
            raise IntersectionDerivativeError(f"{key} must be empty")
    membership = _require_mapping(private.get("membership_mismatches"), "membership_mismatches")
    if membership:
        raise IntersectionDerivativeError("membership mismatches must be empty")

    exclusions = _validated_uuid_set(pg_qdrant)
    stores = _require_mapping(audit.get("stores"), "stores")
    postgres = _require_mapping(stores.get("postgresql"), "stores.postgresql")
    qdrant = _require_mapping(stores.get("qdrant"), "stores.qdrant")
    opensearch = _require_mapping(stores.get("opensearch"), "stores.opensearch")
    if qdrant.get("dataset_id_set_sha256") != opensearch.get("dataset_id_set_sha256"):
        raise IntersectionDerivativeError("Qdrant and OpenSearch dataset-ID hashes differ")
    if qdrant.get("accession_membership_sha256") != opensearch.get("accession_membership_sha256"):
        raise IntersectionDerivativeError("Qdrant and OpenSearch membership hashes differ")
    if int(postgres.get("unique_dataset_id_count", -1)) - len(exclusions) != int(
        qdrant.get("unique_dataset_id_count", -2)
    ):
        raise IntersectionDerivativeError("audit counts do not match the proposed exclusion")

    comparisons = _require_mapping(audit.get("comparisons"), "comparisons")
    if int(comparisons.get("cross_store_mismatch_count", -1)) != len(exclusions):
        raise IntersectionDerivativeError("audit mismatch count differs from private IDs")
    if int(comparisons.get("membership_mismatch_id_count", -1)) != 0:
        raise IntersectionDerivativeError("audit reports membership mismatches")
    q_os = _require_mapping(comparisons.get("qdrant_vs_opensearch"), "qdrant_vs_opensearch")
    if any(int(q_os.get(key, -1)) != 0 for key in q_os):
        raise IntersectionDerivativeError("Qdrant and OpenSearch are not identical")
    return exclusions


def _validate_derivative_identity(
    database_name: str, snapshot_marker: str, snapshot_id: str
) -> None:
    if not _DATABASE_RE.fullmatch(database_name):
        raise IntersectionDerivativeError(
            "database name must identify a frozen derivative ending in '_intersection'"
        )
    if not _SAFE_ID_RE.fullmatch(snapshot_id):
        raise IntersectionDerivativeError("snapshot_id must be a safe 8-128 character identifier")
    if snapshot_marker != snapshot_id:
        raise IntersectionDerivativeError("database-local marker differs from snapshot_id")


async def observe_datasets(connection: asyncpg.Connection[Any]) -> DatasetObservation:
    identity = await connection.fetchrow(
        """
        SELECT current_database() AS database_name,
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
    rows = await connection.fetch(
        """
        SELECT id::text AS dataset_id, source_db, source_id
          FROM datasets
         ORDER BY id::text
        """
    )
    if identity is None:
        raise IntersectionDerivativeError("database identity query returned no row")
    ids = frozenset(str(row["dataset_id"]) for row in rows)
    memberships = tuple(
        (str(row["source_db"]), str(row["source_id"]), str(row["dataset_id"])) for row in rows
    )
    if len(ids) != len(rows):
        raise IntersectionDerivativeError("datasets contains duplicate internal IDs")
    if any(not source or not accession for source, accession, _ in memberships):
        raise IntersectionDerivativeError("datasets contains missing accession identity")
    return DatasetObservation(
        database_name=str(identity["database_name"]),
        snapshot_marker=str(identity["snapshot_marker"] or ""),
        row_count=len(rows),
        dataset_id_set_sha256=canonical_lines_sha256(ids),
        accession_membership_sha256=canonical_membership_sha256(memberships),
        ids=ids,
        memberships=memberships,
    )


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise IntersectionDerivativeError("database catalog returned an unsafe identifier")
    return f'"{value}"'


async def observe_reference_effects(
    connection: asyncpg.Connection[Any], exclusions: frozenset[str]
) -> tuple[ReferenceEffect, ...]:
    rows = await connection.fetch(
        """
        SELECT constraint_info.conname,
               namespace.nspname AS schema_name,
               child.relname AS table_name,
               child_column.attname AS column_name,
               parent_column.attname AS parent_column_name,
               constraint_info.confdeltype::text AS confdeltype,
               CARDINALITY(constraint_info.conkey) AS child_column_count,
               CARDINALITY(constraint_info.confkey) AS parent_column_count
          FROM pg_constraint AS constraint_info
          JOIN pg_class AS child ON child.oid = constraint_info.conrelid
          JOIN pg_namespace AS namespace ON namespace.oid = child.relnamespace
          JOIN pg_attribute AS child_column
            ON child_column.attrelid = constraint_info.conrelid
           AND child_column.attnum = constraint_info.conkey[1]
          JOIN pg_attribute AS parent_column
            ON parent_column.attrelid = constraint_info.confrelid
           AND parent_column.attnum = constraint_info.confkey[1]
         WHERE constraint_info.contype = 'f'
           AND constraint_info.confrelid = 'datasets'::regclass
         ORDER BY namespace.nspname, child.relname, constraint_info.conname
        """
    )
    ids = [uuid.UUID(value) for value in sorted(exclusions)]
    actions = {
        "c": "CASCADE",
        "n": "SET NULL",
        "d": "SET DEFAULT",
        "r": "RESTRICT",
        "a": "NO ACTION",
    }
    effects: list[ReferenceEffect] = []
    for row in rows:
        if int(row["child_column_count"]) != 1 or int(row["parent_column_count"]) != 1:
            raise IntersectionDerivativeError("composite foreign key to datasets is unsupported")
        if str(row["parent_column_name"]) != "id":
            raise IntersectionDerivativeError(
                "foreign key references an unexpected datasets column"
            )
        action = actions.get(str(row["confdeltype"]))
        if action is None:
            raise IntersectionDerivativeError("foreign key uses an unknown delete action")
        schema = _quote_identifier(str(row["schema_name"]))
        table = _quote_identifier(str(row["table_name"]))
        column = _quote_identifier(str(row["column_name"]))
        count = int(
            await connection.fetchval(
                f"SELECT COUNT(*)::bigint FROM {schema}.{table} WHERE {column} = ANY($1::uuid[])",
                ids,
            )
        )
        effects.append(
            ReferenceEffect(
                child_table=f"{row['schema_name']}.{row['table_name']}",
                child_column=str(row["column_name"]),
                on_delete=action,
                affected_rows=count,
            )
        )
    return tuple(effects)


async def observe_characterization(
    connection: asyncpg.Connection[Any], exclusions: frozenset[str]
) -> dict[str, Any]:
    ids = [uuid.UUID(value) for value in sorted(exclusions)]
    rows = await connection.fetch(
        """
        SELECT source_db, extraction_version, COUNT(*)::bigint AS row_count
          FROM datasets
         WHERE id = ANY($1::uuid[])
         GROUP BY source_db, extraction_version
         ORDER BY source_db, extraction_version
        """,
        ids,
    )
    summary = await connection.fetchrow(
        """
        SELECT COUNT(*)::bigint AS row_count,
               COUNT(*) FILTER (WHERE CARDINALITY(modality) = 0)::bigint AS empty_modality_count,
               COUNT(*) FILTER (WHERE title IS NULL OR BTRIM(title) = '')::bigint AS missing_title_count,
               COUNT(*) FILTER (WHERE abstract IS NULL OR BTRIM(abstract) = '')::bigint AS missing_abstract_count
          FROM datasets
         WHERE id = ANY($1::uuid[])
        """,
        ids,
    )
    if summary is None:
        raise IntersectionDerivativeError("exclusion characterization returned no row")
    return {
        "row_count": int(summary["row_count"]),
        "source_and_extraction_version_groups": [
            {
                "source_db": str(row["source_db"]),
                "extraction_version": str(row["extraction_version"]),
                "row_count": int(row["row_count"]),
            }
            for row in rows
        ],
        "empty_modality_count": int(summary["empty_modality_count"]),
        "missing_title_count": int(summary["missing_title_count"]),
        "missing_abstract_count": int(summary["missing_abstract_count"]),
    }


def _observation_public(observation: DatasetObservation) -> dict[str, Any]:
    return {
        "row_count": observation.row_count,
        "dataset_id_set_sha256": observation.dataset_id_set_sha256,
        "accession_membership_sha256": observation.accession_membership_sha256,
    }


def build_plan(
    *,
    observation: DatasetObservation,
    snapshot_id: str,
    audit: Mapping[str, Any],
    audit_sha256: str,
    private_sha256: str,
    exclusions: frozenset[str],
    reference_effects: Sequence[ReferenceEffect],
    characterization: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_derivative_identity(
        observation.database_name, observation.snapshot_marker, snapshot_id
    )
    if not exclusions or not exclusions.issubset(observation.ids):
        raise IntersectionDerivativeError("exclusion IDs are empty or absent from the derivative")
    if any(effect.affected_rows for effect in reference_effects):
        raise IntersectionDerivativeError(
            "proposed exclusions have referencing rows; this v1 tool refuses ancillary changes"
        )
    stores = _require_mapping(audit.get("stores"), "stores")
    target = _require_mapping(stores.get("qdrant"), "stores.qdrant")
    retained_ids = observation.ids - exclusions
    retained_memberships = tuple(
        membership for membership in observation.memberships if membership[2] in retained_ids
    )
    expected_target = {
        "row_count": int(target["unique_dataset_id_count"]),
        "dataset_id_set_sha256": str(target["dataset_id_set_sha256"]),
        "accession_membership_sha256": str(target["accession_membership_sha256"]),
    }
    calculated_target = {
        "row_count": len(retained_ids),
        "dataset_id_set_sha256": canonical_lines_sha256(retained_ids),
        "accession_membership_sha256": canonical_membership_sha256(retained_memberships),
    }
    if calculated_target != expected_target:
        raise IntersectionDerivativeError(
            "retained PostgreSQL identities do not equal the two search stores"
        )
    if int(characterization.get("row_count", -1)) != len(exclusions):
        raise IntersectionDerivativeError("exclusion characterization count differs")
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_snapshot_id": str(audit["snapshot_id"]),
        "derivative_snapshot_id": snapshot_id,
        "database_name": observation.database_name,
        "inclusion_rule": INCLUSION_RULE,
        "selection_timing": "before retrieval evaluation",
        "inputs": {
            "cross_store_audit_sha256": audit_sha256,
            "private_mismatches_sha256": private_sha256,
        },
        "before": _observation_public(observation),
        "exclusion": {
            "row_count": len(exclusions),
            "dataset_id_set_sha256": canonical_lines_sha256(exclusions),
            "aggregate_characterization": dict(characterization),
            "reference_effects": [asdict(effect) for effect in reference_effects],
        },
        "target": expected_target,
        "mutation_scope": ["datasets rows identified by the private mismatch-file hash"],
        "expected_ancillary_row_changes": 0,
        "evidence_boundary": (
            "This creates a declared common-store derivative. It does not repair the source "
            "snapshot, prove metadata accuracy, retrieval quality, latency, or superiority."
        ),
    }


def validate_apply_authorization(
    *, actual_plan_sha256: str, expected_plan_sha256: str, acknowledgement: str
) -> None:
    if actual_plan_sha256 != expected_plan_sha256:
        raise IntersectionDerivativeError("plan SHA-256 differs from --expected-plan-sha256")
    if acknowledgement != ACKNOWLEDGEMENT:
        raise IntersectionDerivativeError(f"--acknowledgement must equal {ACKNOWLEDGEMENT!r}")


def validate_plan_for_apply(
    plan: Mapping[str, Any],
    observation: DatasetObservation,
    *,
    private_sha256: str,
    exclusions: frozenset[str],
) -> Mapping[str, Any]:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise IntersectionDerivativeError("unsupported plan schema_version")
    snapshot_id = str(plan.get("derivative_snapshot_id") or "")
    _validate_derivative_identity(
        observation.database_name, observation.snapshot_marker, snapshot_id
    )
    if plan.get("database_name") != observation.database_name:
        raise IntersectionDerivativeError("current database name differs from plan")
    if plan.get("inclusion_rule") != INCLUSION_RULE:
        raise IntersectionDerivativeError("plan inclusion rule differs")
    if plan.get("selection_timing") != "before retrieval evaluation":
        raise IntersectionDerivativeError("plan selection timing differs")
    if plan.get("expected_ancillary_row_changes") != 0:
        raise IntersectionDerivativeError("plan permits ancillary row changes")
    if plan.get("before") != _observation_public(observation):
        raise IntersectionDerivativeError("current derivative differs from plan before-state")
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    if inputs.get("private_mismatches_sha256") != private_sha256:
        raise IntersectionDerivativeError("private mismatch file SHA-256 differs from plan")
    exclusion = _require_mapping(plan.get("exclusion"), "exclusion")
    if int(exclusion.get("row_count", -1)) != len(exclusions):
        raise IntersectionDerivativeError("private exclusion count differs from plan")
    if exclusion.get("dataset_id_set_sha256") != canonical_lines_sha256(exclusions):
        raise IntersectionDerivativeError("private exclusion ID hash differs from plan")
    if not exclusions.issubset(observation.ids):
        raise IntersectionDerivativeError("an exclusion ID is absent before apply")
    effects = exclusion.get("reference_effects")
    if not isinstance(effects, list) or any(
        not isinstance(effect, Mapping) or int(effect.get("affected_rows", -1)) != 0
        for effect in effects
    ):
        raise IntersectionDerivativeError("plan contains an ancillary reference effect")
    return _require_mapping(plan.get("target"), "target")


async def create_plan(
    database_url: str,
    *,
    snapshot_id: str,
    audit: Mapping[str, Any],
    audit_sha256: str,
    private: Mapping[str, Any],
    private_sha256: str,
) -> dict[str, Any]:
    exclusions = validate_audit_inputs(audit, private)
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            observation = await observe_datasets(connection)
            effects = await observe_reference_effects(connection, exclusions)
            characterization = await observe_characterization(connection, exclusions)
            return build_plan(
                observation=observation,
                snapshot_id=snapshot_id,
                audit=audit,
                audit_sha256=audit_sha256,
                private_sha256=private_sha256,
                exclusions=exclusions,
                reference_effects=effects,
                characterization=characterization,
            )
    finally:
        await connection.close()


async def apply_plan(
    database_url: str,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    expected_plan_sha256: str,
    private: Mapping[str, Any],
    private_sha256: str,
    acknowledgement: str,
) -> dict[str, Any]:
    validate_apply_authorization(
        actual_plan_sha256=plan_sha256,
        expected_plan_sha256=expected_plan_sha256,
        acknowledgement=acknowledgement,
    )
    exclusions = validate_audit_inputs(
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "snapshot_id": plan.get("source_snapshot_id"),
            "stores": {
                "postgresql": {
                    "unique_dataset_id_count": int(
                        _require_mapping(plan.get("before"), "before")["row_count"]
                    )
                },
                "qdrant": {
                    "unique_dataset_id_count": int(
                        _require_mapping(plan.get("target"), "target")["row_count"]
                    ),
                    "dataset_id_set_sha256": _require_mapping(plan.get("target"), "target")[
                        "dataset_id_set_sha256"
                    ],
                    "accession_membership_sha256": _require_mapping(plan.get("target"), "target")[
                        "accession_membership_sha256"
                    ],
                },
                "opensearch": dict(_require_mapping(plan.get("target"), "target")),
            },
            "comparisons": {
                "cross_store_mismatch_count": int(
                    _require_mapping(plan.get("exclusion"), "exclusion")["row_count"]
                ),
                "membership_mismatch_id_count": 0,
                "qdrant_vs_opensearch": {
                    "qdrant_only_count": 0,
                    "opensearch_only_count": 0,
                    "symmetric_difference_count": 0,
                },
            },
        },
        private,
    )
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction(isolation="serializable"):
            before = await observe_datasets(connection)
            target = validate_plan_for_apply(
                plan,
                before,
                private_sha256=private_sha256,
                exclusions=exclusions,
            )
            status = await connection.execute(
                "DELETE FROM datasets WHERE id = ANY($1::uuid[])",
                [uuid.UUID(value) for value in sorted(exclusions)],
            )
            deleted_rows = int(status.rsplit(" ", 1)[-1])
            if deleted_rows != len(exclusions):
                raise IntersectionDerivativeError("deleted row count differs from plan")
            after = await observe_datasets(connection)
            expected_after = {
                "row_count": int(target["row_count"]),
                "dataset_id_set_sha256": str(target["dataset_id_set_sha256"]),
                "accession_membership_sha256": str(target["accession_membership_sha256"]),
            }
            if _observation_public(after) != expected_after:
                raise IntersectionDerivativeError("post-apply identity differs from target")
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "applied_at_utc": datetime.now(UTC).isoformat(),
            "source_snapshot_id": plan["source_snapshot_id"],
            "derivative_snapshot_id": plan["derivative_snapshot_id"],
            "database_name": plan["database_name"],
            "plan_sha256": plan_sha256,
            "private_mismatches_sha256": private_sha256,
            "inclusion_rule": INCLUSION_RULE,
            "deleted_dataset_rows": deleted_rows,
            "ancillary_row_changes": 0,
            "after": expected_after,
            "evidence_boundary": plan["evidence_boundary"],
        }
    finally:
        await connection.close()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise IntersectionDerivativeError(f"{label} must be a JSON object")
    return raw


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="read only; create a hashed plan")
    plan_parser.add_argument("--snapshot-id", required=True)
    plan_parser.add_argument("--audit", type=Path, required=True)
    plan_parser.add_argument("--private-mismatches", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    apply_parser = subparsers.add_parser("apply", help="change only the isolated derivative")
    apply_parser.add_argument("--plan", type=Path, required=True)
    apply_parser.add_argument("--private-mismatches", type=Path, required=True)
    apply_parser.add_argument("--expected-plan-sha256", required=True)
    apply_parser.add_argument("--acknowledgement", required=True)
    apply_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise IntersectionDerivativeError("DATABASE_URL is not set")
    private = _read_object(args.private_mismatches, "private mismatch file")
    private_sha = sha256_file(args.private_mismatches)
    if args.command == "plan":
        audit = _read_object(args.audit, "audit")
        plan = await create_plan(
            database_url,
            snapshot_id=args.snapshot_id,
            audit=audit,
            audit_sha256=sha256_file(args.audit),
            private=private,
            private_sha256=private_sha,
        )
        _write_private_json(args.output, plan)
        print(f"plan_sha256={sha256_file(args.output)}")
        print(f"planned_exclusions={plan['exclusion']['row_count']}")
        print("mode=read_only_plan")
        return 0
    plan = _read_object(args.plan, "plan")
    report = await apply_plan(
        database_url,
        plan=plan,
        plan_sha256=sha256_file(args.plan),
        expected_plan_sha256=args.expected_plan_sha256,
        private=private,
        private_sha256=private_sha,
        acknowledgement=args.acknowledgement,
    )
    _write_private_json(args.output, report)
    print(f"report_sha256={sha256_file(args.output)}")
    print(f"deleted_dataset_rows={report['deleted_dataset_rows']}")
    print(f"retained_dataset_rows={report['after']['row_count']}")
    print("mode=isolated_derivative_apply")
    return 0


def main() -> int:
    return asyncio.run(async_main())
