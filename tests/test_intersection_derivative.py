from __future__ import annotations

from copy import deepcopy

import pytest

from genofinder_eval.cross_store_snapshot import (
    PRIVATE_SCHEMA_VERSION,
    canonical_lines_sha256,
    canonical_membership_sha256,
)
from genofinder_eval.cross_store_snapshot import (
    SCHEMA_VERSION as AUDIT_SCHEMA_VERSION,
)
from genofinder_eval.intersection_derivative import (
    ACKNOWLEDGEMENT,
    INCLUSION_RULE,
    DatasetObservation,
    IntersectionDerivativeError,
    ReferenceEffect,
    build_plan,
    validate_apply_authorization,
    validate_audit_inputs,
    validate_plan_for_apply,
)

EXCLUDED = "00000000-0000-4000-8000-000000000003"
ROWS = (
    ("GEO", "GSE1", "00000000-0000-4000-8000-000000000001"),
    ("SRA", "SRP2", "00000000-0000-4000-8000-000000000002"),
    ("GEO", "GSE3", EXCLUDED),
)


def _observation() -> DatasetObservation:
    ids = frozenset(row[2] for row in ROWS)
    return DatasetObservation(
        database_name="omicsplorer_frozen_gpb_v1_intersection",
        snapshot_marker="gpb-snapshot-v1-intersection",
        row_count=3,
        dataset_id_set_sha256=canonical_lines_sha256(ids),
        accession_membership_sha256=canonical_membership_sha256(ROWS),
        ids=ids,
        memberships=ROWS,
    )


def _audit_private() -> tuple[dict[str, object], dict[str, object]]:
    retained = ROWS[:2]
    target_id_hash = canonical_lines_sha256(row[2] for row in retained)
    target_membership_hash = canonical_membership_sha256(retained)
    audit: dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "snapshot_id": "gpb-snapshot-v1",
        "stores": {
            "postgresql": {"unique_dataset_id_count": 3},
            "qdrant": {
                "unique_dataset_id_count": 2,
                "dataset_id_set_sha256": target_id_hash,
                "accession_membership_sha256": target_membership_hash,
            },
            "opensearch": {
                "unique_dataset_id_count": 2,
                "dataset_id_set_sha256": target_id_hash,
                "accession_membership_sha256": target_membership_hash,
            },
        },
        "comparisons": {
            "cross_store_mismatch_count": 1,
            "membership_mismatch_id_count": 0,
            "qdrant_vs_opensearch": {
                "qdrant_only_count": 0,
                "opensearch_only_count": 0,
                "symmetric_difference_count": 0,
            },
        },
    }
    private: dict[str, object] = {
        "schema_version": PRIVATE_SCHEMA_VERSION,
        "snapshot_id": "gpb-snapshot-v1",
        "dataset_id_differences": {
            "postgresql_not_qdrant": [EXCLUDED],
            "qdrant_not_postgresql": [],
            "postgresql_not_opensearch": [EXCLUDED],
            "opensearch_not_postgresql": [],
            "qdrant_not_opensearch": [],
            "opensearch_not_qdrant": [],
        },
        "membership_mismatches": {},
    }
    return audit, private


def _plan() -> tuple[dict[str, object], dict[str, object]]:
    audit, private = _audit_private()
    exclusions = validate_audit_inputs(audit, private)
    plan = build_plan(
        observation=_observation(),
        snapshot_id="gpb-snapshot-v1-intersection",
        audit=audit,
        audit_sha256="a" * 64,
        private_sha256="b" * 64,
        exclusions=exclusions,
        reference_effects=(ReferenceEffect("public.samples", "dataset_id", "CASCADE", 0),),
        characterization={
            "row_count": 1,
            "source_and_extraction_version_groups": [
                {"source_db": "GEO", "extraction_version": "legacy", "row_count": 1}
            ],
            "empty_modality_count": 1,
            "missing_title_count": 0,
            "missing_abstract_count": 0,
        },
    )
    return plan, private


def test_valid_audit_builds_hash_bound_non_outcome_plan() -> None:
    plan, private = _plan()
    exclusions = validate_audit_inputs(_audit_private()[0], private)

    assert plan["inclusion_rule"] == INCLUSION_RULE
    assert plan["selection_timing"] == "before retrieval evaluation"
    assert plan["exclusion"]["row_count"] == 1  # type: ignore[index]
    assert EXCLUDED not in str(plan)
    validate_plan_for_apply(
        plan,
        _observation(),
        private_sha256="b" * 64,
        exclusions=exclusions,
    )


def test_audit_rejects_asymmetric_stores_or_membership_mismatch() -> None:
    audit, private = _audit_private()
    changed = deepcopy(private)
    differences = changed["dataset_id_differences"]
    assert isinstance(differences, dict)
    differences["qdrant_not_opensearch"] = [EXCLUDED]
    with pytest.raises(IntersectionDerivativeError, match="qdrant_not_opensearch"):
        validate_audit_inputs(audit, changed)

    changed = deepcopy(private)
    changed["membership_mismatches"] = {EXCLUDED: {}}
    with pytest.raises(IntersectionDerivativeError, match="membership mismatches"):
        validate_audit_inputs(audit, changed)


def test_plan_refuses_any_ancillary_reference_effect() -> None:
    audit, private = _audit_private()
    with pytest.raises(IntersectionDerivativeError, match="referencing rows"):
        build_plan(
            observation=_observation(),
            snapshot_id="gpb-snapshot-v1-intersection",
            audit=audit,
            audit_sha256="a" * 64,
            private_sha256="b" * 64,
            exclusions=validate_audit_inputs(audit, private),
            reference_effects=(ReferenceEffect("public.samples", "dataset_id", "CASCADE", 1),),
            characterization={"row_count": 1},
        )


def test_apply_validation_binds_plan_private_hash_and_acknowledgement() -> None:
    plan, private = _plan()
    exclusions = validate_audit_inputs(_audit_private()[0], private)
    validate_apply_authorization(
        actual_plan_sha256="a" * 64,
        expected_plan_sha256="a" * 64,
        acknowledgement=ACKNOWLEDGEMENT,
    )
    with pytest.raises(IntersectionDerivativeError, match="plan SHA-256"):
        validate_apply_authorization(
            actual_plan_sha256="a" * 64,
            expected_plan_sha256="c" * 64,
            acknowledgement=ACKNOWLEDGEMENT,
        )
    with pytest.raises(IntersectionDerivativeError, match="private mismatch"):
        validate_plan_for_apply(
            plan,
            _observation(),
            private_sha256="c" * 64,
            exclusions=exclusions,
        )
