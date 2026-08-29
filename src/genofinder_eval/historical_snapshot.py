"""Safely annotate unresolved lineage in an isolated PostgreSQL snapshot.

Planning is read-only. Applying a plan changes only ``extraction_lineage_id``
and ``build_stage`` and is guarded by an isolated-database naming convention,
a database-local snapshot marker, a frozen plan hash, and an exact operator
acknowledgement.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

PLAN_SCHEMA_VERSION = "omicsplorer-historical-snapshot-plan-v1"
REPORT_SCHEMA_VERSION = "omicsplorer-historical-snapshot-annotation-v1"
ACKNOWLEDGEMENT = "I_CONFIRM_THIS_IS_AN_ISOLATED_FROZEN_SNAPSHOT"
_DATABASE_RE = re.compile(r"^omicsplorer_frozen_[a-z0-9_]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class HistoricalSnapshotError(RuntimeError):
    """Raised when an isolated-snapshot safety condition is not satisfied."""


@dataclass(frozen=True)
class VersionGroup:
    extraction_version: str
    row_count: int
    lineage_id: str


@dataclass(frozen=True)
class SnapshotObservation:
    database_name: str
    snapshot_marker: str
    row_count: int
    missing_extraction_version_count: int
    missing_lineage_count: int
    missing_build_stage_count: int
    partial_lineage_count: int
    missing_accession_identity_count: int
    duplicate_accession_count: int
    dataset_id_set_sha256: str
    accession_membership_sha256: str
    groups: tuple[VersionGroup, ...]


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lineage_id_for_version(extraction_version: str) -> str:
    """Return a safe, deterministic unresolved-lineage ID for one version label."""

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", extraction_version).strip("-._")
    if not normalized:
        raise HistoricalSnapshotError("extraction_version cannot produce a safe lineage ID")
    label = normalized[:48]
    suffix = hashlib.sha256(extraction_version.encode("utf-8")).hexdigest()[:12]
    lineage_id = f"historical-{label}-{suffix}-unresolved"
    if not _SAFE_ID_RE.fullmatch(lineage_id):  # pragma: no cover - defensive invariant
        raise HistoricalSnapshotError("generated lineage ID is unsafe")
    return lineage_id


def _validate_isolated_identity(database_name: str, snapshot_marker: str, snapshot_id: str) -> None:
    if not _DATABASE_RE.fullmatch(database_name):
        raise HistoricalSnapshotError(
            "database name must match 'omicsplorer_frozen_<lowercase_name>'; "
            "the production database must never be renamed or annotated for this workflow"
        )
    if snapshot_marker != snapshot_id:
        raise HistoricalSnapshotError("database-local snapshot marker differs from snapshot_id")
    if not _SAFE_ID_RE.fullmatch(snapshot_id) or len(snapshot_id) < 8:
        raise HistoricalSnapshotError("snapshot_id must be a safe identifier of at least 8 characters")


def build_plan(observation: SnapshotObservation, *, snapshot_id: str) -> dict[str, Any]:
    """Build a frozen annotation plan after checking read-only preconditions."""

    _validate_isolated_identity(
        observation.database_name,
        observation.snapshot_marker,
        snapshot_id,
    )
    if observation.row_count < 1:
        raise HistoricalSnapshotError("datasets table is empty")
    blockers = {
        "missing_extraction_version_count": observation.missing_extraction_version_count,
        "partial_lineage_count": observation.partial_lineage_count,
        "missing_accession_identity_count": observation.missing_accession_identity_count,
        "duplicate_accession_count": observation.duplicate_accession_count,
    }
    nonzero = {key: value for key, value in blockers.items() if value}
    if nonzero:
        raise HistoricalSnapshotError(f"snapshot plan preconditions failed: {nonzero}")
    if observation.missing_lineage_count != observation.row_count:
        raise HistoricalSnapshotError("every row must have a blank extraction_lineage_id")
    if observation.missing_build_stage_count != observation.row_count:
        raise HistoricalSnapshotError("every row must have a blank build_stage")
    if sum(group.row_count for group in observation.groups) != observation.row_count:
        raise HistoricalSnapshotError("version-group counts do not sum to the dataset row count")
    if len({group.extraction_version for group in observation.groups}) != len(
        observation.groups
    ):
        raise HistoricalSnapshotError("extraction_version groups are duplicated")

    groups = [
        asdict(
            VersionGroup(
                extraction_version=group.extraction_version,
                row_count=group.row_count,
                lineage_id=lineage_id_for_version(group.extraction_version),
            )
        )
        for group in sorted(observation.groups, key=lambda item: item.extraction_version)
    ]
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "database_name": observation.database_name,
        "before": {
            "row_count": observation.row_count,
            "dataset_id_set_sha256": observation.dataset_id_set_sha256,
            "accession_membership_sha256": observation.accession_membership_sha256,
            "missing_extraction_version_count": (
                observation.missing_extraction_version_count
            ),
            "duplicate_accession_count": observation.duplicate_accession_count,
            "missing_lineage_count": observation.missing_lineage_count,
            "missing_build_stage_count": observation.missing_build_stage_count,
            "partial_lineage_count": observation.partial_lineage_count,
            "missing_accession_identity_count": (
                observation.missing_accession_identity_count
            ),
        },
        "groups": groups,
        "mutation_scope": ["datasets.extraction_lineage_id", "datasets.build_stage"],
        "evidence_boundary": (
            "This plan labels unreconstructable history in an isolated snapshot. It does not "
            "reconstruct model provenance, validate metadata accuracy, or modify production."
        ),
    }


def validate_plan_against_observation(
    plan: Mapping[str, Any], observation: SnapshotObservation
) -> list[VersionGroup]:
    """Fail if the database has changed since the plan was created."""

    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise HistoricalSnapshotError("unsupported plan schema_version")
    snapshot_id = str(plan.get("snapshot_id") or "")
    database_name = str(plan.get("database_name") or "")
    _validate_isolated_identity(database_name, observation.snapshot_marker, snapshot_id)
    if observation.database_name != database_name:
        raise HistoricalSnapshotError("current database name differs from the plan")
    before = plan.get("before")
    if not isinstance(before, Mapping):
        raise HistoricalSnapshotError("plan before-observation is missing")
    expected_observation = {
        "row_count": observation.row_count,
        "dataset_id_set_sha256": observation.dataset_id_set_sha256,
        "accession_membership_sha256": observation.accession_membership_sha256,
        "missing_extraction_version_count": observation.missing_extraction_version_count,
        "duplicate_accession_count": observation.duplicate_accession_count,
        "missing_lineage_count": observation.missing_lineage_count,
        "missing_build_stage_count": observation.missing_build_stage_count,
        "partial_lineage_count": observation.partial_lineage_count,
        "missing_accession_identity_count": observation.missing_accession_identity_count,
    }
    if dict(before) != expected_observation:
        raise HistoricalSnapshotError("current snapshot observations differ from the frozen plan")
    plan_groups = plan.get("groups")
    if not isinstance(plan_groups, list) or not plan_groups:
        raise HistoricalSnapshotError("plan has no version groups")
    try:
        parsed = [VersionGroup(**group) for group in plan_groups]
    except (TypeError, ValueError) as exc:
        raise HistoricalSnapshotError("plan contains an invalid version group") from exc
    current_counts = {
        group.extraction_version: group.row_count for group in observation.groups
    }
    if {group.extraction_version: group.row_count for group in parsed} != current_counts:
        raise HistoricalSnapshotError("current extraction-version counts differ from the plan")
    for group in parsed:
        if group.lineage_id != lineage_id_for_version(group.extraction_version):
            raise HistoricalSnapshotError("plan lineage ID differs from the deterministic mapping")
    return parsed


def validate_apply_authorization(
    *, actual_plan_sha256: str, expected_plan_sha256: str, acknowledgement: str
) -> None:
    if actual_plan_sha256 != expected_plan_sha256:
        raise HistoricalSnapshotError("plan SHA-256 differs from --expected-plan-sha256")
    if acknowledgement != ACKNOWLEDGEMENT:
        raise HistoricalSnapshotError(f"--acknowledgement must equal {ACKNOWLEDGEMENT!r}")


def validate_post_annotation(
    *,
    before: SnapshotObservation,
    after: SnapshotObservation,
    groups: Sequence[VersionGroup],
    assignments: set[tuple[str, str, str, int]],
) -> None:
    """Verify that annotation changed no row identity, membership, or version group."""

    immutable_before = (
        before.database_name,
        before.snapshot_marker,
        before.row_count,
        before.missing_extraction_version_count,
        before.missing_accession_identity_count,
        before.duplicate_accession_count,
        before.dataset_id_set_sha256,
        before.accession_membership_sha256,
        before.groups,
    )
    immutable_after = (
        after.database_name,
        after.snapshot_marker,
        after.row_count,
        after.missing_extraction_version_count,
        after.missing_accession_identity_count,
        after.duplicate_accession_count,
        after.dataset_id_set_sha256,
        after.accession_membership_sha256,
        after.groups,
    )
    if immutable_after != immutable_before:
        raise HistoricalSnapshotError("identity or version observations changed during annotation")
    if (
        after.missing_lineage_count
        or after.missing_build_stage_count
        or after.partial_lineage_count
    ):
        raise HistoricalSnapshotError("lineage annotation remained incomplete")
    expected = {
        (
            group.extraction_version,
            group.lineage_id,
            "historical_unresolved",
            group.row_count,
        )
        for group in groups
    }
    if assignments != expected:
        raise HistoricalSnapshotError("post-annotation assignments differ from the plan")


async def _hash_rows(
    connection: asyncpg.Connection[Any], query: str, fields: Sequence[str]
) -> str:
    digest = hashlib.sha256()
    async for row in connection.cursor(query, prefetch=5000):
        digest.update("\t".join(str(row[field]) for field in fields).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


async def observe_snapshot(connection: asyncpg.Connection[Any]) -> SnapshotObservation:
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
    counts = await connection.fetchrow(
        """
        SELECT COUNT(*)::bigint AS row_count,
               COUNT(*) FILTER (
                   WHERE NULLIF(BTRIM(extraction_version), '') IS NULL
               )::bigint AS missing_extraction_version_count,
               COUNT(*) FILTER (
                   WHERE NULLIF(BTRIM(extraction_lineage_id), '') IS NULL
               )::bigint AS missing_lineage_count,
               COUNT(*) FILTER (
                   WHERE NULLIF(BTRIM(build_stage), '') IS NULL
               )::bigint AS missing_build_stage_count,
               COUNT(*) FILTER (
                   WHERE (NULLIF(BTRIM(extraction_lineage_id), '') IS NULL)
                      <> (NULLIF(BTRIM(build_stage), '') IS NULL)
               )::bigint AS partial_lineage_count,
               COUNT(*) FILTER (
                   WHERE NULLIF(BTRIM(source_db), '') IS NULL
                      OR NULLIF(BTRIM(source_id), '') IS NULL
               )::bigint AS missing_accession_identity_count,
               (COUNT(*) - COUNT(DISTINCT (source_db, source_id)))::bigint
                   AS duplicate_accession_count
          FROM datasets
        """
    )
    if identity is None or counts is None:
        raise HistoricalSnapshotError("snapshot observation query returned no row")
    groups_raw = await connection.fetch(
        """
        SELECT extraction_version, COUNT(*)::bigint AS row_count
          FROM datasets
         GROUP BY extraction_version
         ORDER BY extraction_version
        """
    )
    dataset_hash = await _hash_rows(
        connection,
        "SELECT id::text AS dataset_id FROM datasets ORDER BY id::text",
        ("dataset_id",),
    )
    accession_hash = await _hash_rows(
        connection,
        """
        SELECT source_db, source_id, id::text AS dataset_id
          FROM datasets
         ORDER BY source_db, source_id, id::text
        """,
        ("source_db", "source_id", "dataset_id"),
    )
    return SnapshotObservation(
        database_name=str(identity["database_name"]),
        snapshot_marker=str(identity["snapshot_marker"] or ""),
        row_count=int(counts["row_count"]),
        missing_extraction_version_count=int(counts["missing_extraction_version_count"]),
        missing_lineage_count=int(counts["missing_lineage_count"]),
        missing_build_stage_count=int(counts["missing_build_stage_count"]),
        partial_lineage_count=int(counts["partial_lineage_count"]),
        missing_accession_identity_count=int(counts["missing_accession_identity_count"]),
        duplicate_accession_count=int(counts["duplicate_accession_count"]),
        dataset_id_set_sha256=dataset_hash,
        accession_membership_sha256=accession_hash,
        groups=tuple(
            VersionGroup(
                extraction_version=str(row["extraction_version"] or ""),
                row_count=int(row["row_count"]),
                lineage_id="",
            )
            for row in groups_raw
        ),
    )


async def create_plan(database_url: str, *, snapshot_id: str) -> dict[str, Any]:
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            observation = await observe_snapshot(connection)
            return build_plan(observation, snapshot_id=snapshot_id)
    finally:
        await connection.close()


async def apply_plan(
    database_url: str,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    expected_plan_sha256: str,
    acknowledgement: str,
) -> dict[str, Any]:
    validate_apply_authorization(
        actual_plan_sha256=plan_sha256,
        expected_plan_sha256=expected_plan_sha256,
        acknowledgement=acknowledgement,
    )
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        updates: list[dict[str, Any]] = []
        async with connection.transaction(isolation="serializable"):
            before = await observe_snapshot(connection)
            groups = validate_plan_against_observation(plan, before)
            for group in groups:
                status = await connection.execute(
                    """
                    UPDATE datasets
                       SET extraction_lineage_id = $1,
                           build_stage = 'historical_unresolved'
                     WHERE extraction_version = $2
                       AND NULLIF(BTRIM(extraction_lineage_id), '') IS NULL
                       AND NULLIF(BTRIM(build_stage), '') IS NULL
                    """,
                    group.lineage_id,
                    group.extraction_version,
                )
                updated = int(status.rsplit(" ", 1)[-1])
                if updated != group.row_count:
                    raise HistoricalSnapshotError(
                        f"updated row count differs for {group.extraction_version!r}"
                    )
                updates.append({**asdict(group), "updated_rows": updated})
            after = await observe_snapshot(connection)
            assignments = await connection.fetch(
                """
                SELECT extraction_version, extraction_lineage_id, build_stage,
                       COUNT(*)::bigint AS row_count
                  FROM datasets
                 GROUP BY extraction_version, extraction_lineage_id, build_stage
                 ORDER BY extraction_version
                """
            )
            observed = {
                (
                    str(row["extraction_version"]),
                    str(row["extraction_lineage_id"]),
                    str(row["build_stage"]),
                    int(row["row_count"]),
                )
                for row in assignments
            }
            validate_post_annotation(
                before=before,
                after=after,
                groups=groups,
                assignments=observed,
            )
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "applied_at_utc": datetime.now(UTC).isoformat(),
            "snapshot_id": plan["snapshot_id"],
            "database_name": plan["database_name"],
            "plan_sha256": plan_sha256,
            "updates": updates,
            "identity_before_after_equal": True,
            "after": {
                "row_count": after.row_count,
                "dataset_id_set_sha256": after.dataset_id_set_sha256,
                "accession_membership_sha256": after.accession_membership_sha256,
                "missing_lineage_count": after.missing_lineage_count,
                "missing_build_stage_count": after.missing_build_stage_count,
            },
            "evidence_boundary": (
                "Historical-unresolved labels were applied only to the isolated snapshot. "
                "They do not reconstruct metadata-generation provenance or establish accuracy."
            ),
        }
    finally:
        await connection.close()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply unresolved lineage labels in an isolated snapshot."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="read only; write a frozen annotation plan")
    plan.add_argument("--snapshot-id", required=True)
    plan.add_argument("--output", type=Path, required=True)
    apply = subparsers.add_parser("apply", help="mutate only the isolated snapshot")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--expected-plan-sha256", required=True)
    apply.add_argument("--acknowledgement", required=True)
    apply.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HistoricalSnapshotError("DATABASE_URL is not set")
    if args.command == "plan":
        plan = await create_plan(database_url, snapshot_id=args.snapshot_id)
        _write_json(args.output, plan)
        print(f"plan_sha256={sha256_file(args.output)}")
        print(f"planned_rows={plan['before']['row_count']}")
        print("mode=read_only_plan")
        return 0
    plan_sha = sha256_file(args.plan)
    raw = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise HistoricalSnapshotError("plan must be a JSON object")
    report = await apply_plan(
        database_url,
        plan=raw,
        plan_sha256=plan_sha,
        expected_plan_sha256=args.expected_plan_sha256,
        acknowledgement=args.acknowledgement,
    )
    _write_json(args.output, report)
    print(f"annotation_report_sha256={sha256_file(args.output)}")
    print(f"annotated_rows={report['after']['row_count']}")
    print("mode=isolated_snapshot_apply")
    return 0


def main() -> int:
    return asyncio.run(async_main())
