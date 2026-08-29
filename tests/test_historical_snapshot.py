from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from genofinder_eval.historical_snapshot import (
    ACKNOWLEDGEMENT,
    HistoricalSnapshotError,
    SnapshotObservation,
    VersionGroup,
    build_plan,
    lineage_id_for_version,
    validate_apply_authorization,
    validate_plan_against_observation,
    validate_post_annotation,
)


def _observation(**changes: object) -> SnapshotObservation:
    observation = SnapshotObservation(
        database_name="omicsplorer_frozen_gpb_v1",
        snapshot_marker="gpb-snapshot-v1",
        row_count=3,
        missing_extraction_version_count=0,
        missing_lineage_count=3,
        missing_build_stage_count=3,
        partial_lineage_count=0,
        missing_accession_identity_count=0,
        duplicate_accession_count=0,
        dataset_id_set_sha256="a" * 64,
        accession_membership_sha256="b" * 64,
        groups=(
            VersionGroup("v1 alpha", 2, ""),
            VersionGroup("v2/legacy", 1, ""),
        ),
    )
    return replace(observation, **changes)


def _planned_groups(plan: dict[str, object]) -> list[VersionGroup]:
    groups = plan["groups"]
    assert isinstance(groups, list)
    return [VersionGroup(**group) for group in groups]


def _assignments(groups: list[VersionGroup]) -> set[tuple[str, str, str, int]]:
    return {
        (
            group.extraction_version,
            group.lineage_id,
            "historical_unresolved",
            group.row_count,
        )
        for group in groups
    }


def test_lineage_id_is_safe_deterministic_and_version_specific() -> None:
    first = lineage_id_for_version("v1 alpha/legacy")

    assert first == lineage_id_for_version("v1 alpha/legacy")
    assert first != lineage_id_for_version("v1-alpha-legacy")
    assert first.startswith("historical-v1-alpha-legacy-")
    assert first.endswith("-unresolved")


def test_plan_binds_identity_counts_and_deterministic_groups() -> None:
    observation = _observation()

    plan = build_plan(observation, snapshot_id="gpb-snapshot-v1")
    parsed = validate_plan_against_observation(plan, observation)

    assert plan["database_name"] == "omicsplorer_frozen_gpb_v1"
    assert plan["before"] == {
        "row_count": 3,
        "dataset_id_set_sha256": "a" * 64,
        "accession_membership_sha256": "b" * 64,
        "missing_extraction_version_count": 0,
        "duplicate_accession_count": 0,
        "missing_lineage_count": 3,
        "missing_build_stage_count": 3,
        "partial_lineage_count": 0,
        "missing_accession_identity_count": 0,
    }
    assert parsed == _planned_groups(plan)
    assert len({group.lineage_id for group in parsed}) == 2


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"database_name": "omicsplorer"}, "database name must match"),
        ({"snapshot_marker": "wrong-snapshot"}, "snapshot marker differs"),
        ({"missing_extraction_version_count": 1}, "preconditions failed"),
        ({"partial_lineage_count": 1}, "preconditions failed"),
        ({"missing_accession_identity_count": 1}, "preconditions failed"),
        ({"duplicate_accession_count": 1}, "preconditions failed"),
        ({"missing_lineage_count": 2}, "every row must have a blank"),
        ({"missing_build_stage_count": 2}, "every row must have a blank"),
    ],
)
def test_plan_rejects_unsafe_or_incomplete_snapshot(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(HistoricalSnapshotError, match=message):
        build_plan(_observation(**changes), snapshot_id="gpb-snapshot-v1")


def test_frozen_plan_rejects_changed_snapshot() -> None:
    observation = _observation()
    plan = build_plan(observation, snapshot_id="gpb-snapshot-v1")

    changed = replace(observation, dataset_id_set_sha256="c" * 64)
    with pytest.raises(HistoricalSnapshotError, match="differ from the frozen plan"):
        validate_plan_against_observation(plan, changed)

    changed_plan = deepcopy(plan)
    groups = changed_plan["groups"]
    assert isinstance(groups, list)
    groups[0]["lineage_id"] = "historical-invented-unresolved"
    with pytest.raises(HistoricalSnapshotError, match="deterministic mapping"):
        validate_plan_against_observation(changed_plan, observation)


def test_apply_requires_exact_hash_and_acknowledgement() -> None:
    validate_apply_authorization(
        actual_plan_sha256="a" * 64,
        expected_plan_sha256="a" * 64,
        acknowledgement=ACKNOWLEDGEMENT,
    )

    with pytest.raises(HistoricalSnapshotError, match="plan SHA-256 differs"):
        validate_apply_authorization(
            actual_plan_sha256="a" * 64,
            expected_plan_sha256="b" * 64,
            acknowledgement=ACKNOWLEDGEMENT,
        )
    with pytest.raises(HistoricalSnapshotError, match="--acknowledgement"):
        validate_apply_authorization(
            actual_plan_sha256="a" * 64,
            expected_plan_sha256="a" * 64,
            acknowledgement="yes",
        )


def test_post_annotation_accepts_only_complete_planned_labels() -> None:
    before = _observation()
    plan = build_plan(before, snapshot_id="gpb-snapshot-v1")
    groups = _planned_groups(plan)
    after = replace(before, missing_lineage_count=0, missing_build_stage_count=0)

    validate_post_annotation(
        before=before,
        after=after,
        groups=groups,
        assignments=_assignments(groups),
    )


def test_post_annotation_rejects_identity_change_or_wrong_label() -> None:
    before = _observation()
    plan = build_plan(before, snapshot_id="gpb-snapshot-v1")
    groups = _planned_groups(plan)
    after = replace(before, missing_lineage_count=0, missing_build_stage_count=0)

    with pytest.raises(HistoricalSnapshotError, match="identity or version"):
        validate_post_annotation(
            before=before,
            after=replace(after, accession_membership_sha256="c" * 64),
            groups=groups,
            assignments=_assignments(groups),
        )
    wrong = _assignments(groups)
    item = wrong.pop()
    wrong.add((item[0], item[1], "resolved", item[3]))
    with pytest.raises(HistoricalSnapshotError, match="assignments differ"):
        validate_post_annotation(
            before=before,
            after=after,
            groups=groups,
            assignments=wrong,
        )
