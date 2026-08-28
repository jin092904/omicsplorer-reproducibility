from __future__ import annotations

from genofinder_eval.evidence_preflight import (
    REQUIRED_DATASET_COLUMNS,
    ComponentResult,
    assess_dataset_columns,
    assess_dataset_values,
    build_report,
)


def test_dataset_column_assessment_fails_closed() -> None:
    result = assess_dataset_columns(REQUIRED_DATASET_COLUMNS - {"build_stage"})

    assert result.status == "blocked"
    assert result.checks["datasets_table_found"] is True
    assert result.checks["required_accession_lineage_columns_found"] is False
    assert result.blockers == ["missing datasets column: build_stage"]


def test_dataset_column_assessment_accepts_complete_schema() -> None:
    result = assess_dataset_columns(set(REQUIRED_DATASET_COLUMNS) | {"title"})

    assert result.status == "ready"
    assert result.blockers == []


def test_dataset_value_assessment_fails_on_incomplete_lineage() -> None:
    result = assess_dataset_values(
        {
            "row_count": 10,
            "invalid_identity_count": 0,
            "missing_extraction_version_count": 0,
            "missing_extraction_lineage_id_count": 3,
            "missing_build_stage_count": 2,
            "duplicate_accession_count": 0,
        }
    )

    assert result.status == "blocked"
    assert result.checks["row_lineage_complete"] is False
    assert result.blockers == [
        "rows missing extraction_lineage_id: 3",
        "rows missing build_stage: 2",
    ]
    assert result.observations is not None
    assert result.observations["row_count"] == 10


def test_dataset_value_assessment_accepts_complete_nonempty_corpus() -> None:
    result = assess_dataset_values(
        {
            "row_count": 10,
            "invalid_identity_count": 0,
            "missing_extraction_version_count": 0,
            "missing_extraction_lineage_id_count": 0,
            "missing_build_stage_count": 0,
            "duplicate_accession_count": 0,
        }
    )

    assert result.status == "ready"
    assert result.blockers == []


def test_dataset_value_assessment_rejects_empty_corpus() -> None:
    result = assess_dataset_values(
        {
            "row_count": 0,
            "invalid_identity_count": 0,
            "missing_extraction_version_count": 0,
            "missing_extraction_lineage_id_count": 0,
            "missing_build_stage_count": 0,
            "duplicate_accession_count": 0,
        }
    )

    assert result.status == "blocked"
    assert result.blockers == ["datasets table is empty"]


def test_report_does_not_equate_preflight_with_evidence() -> None:
    report = build_report(
        [
            ComponentResult("postgresql", "ready", {"read_probe_succeeded": True}, []),
            ComponentResult("qdrant", "ready", {"collection_found": True}, []),
            ComponentResult("opensearch", "ready", {"index_found": True}, []),
        ]
    )

    assert report["ready_for_evidence_collection"] is True
    assert "not corpus" in report["evidence_boundary"]
    assert "RELEASE GO" in report["evidence_boundary"]


def test_report_aggregates_blockers_without_connection_values() -> None:
    report = build_report(
        [
            ComponentResult(
                "postgresql",
                "blocked",
                {"required_accession_lineage_columns_found": False},
                ["missing datasets column: extraction_lineage_id"],
            )
        ]
    )

    assert report["ready_for_evidence_collection"] is False
    assert report["blocking_reasons"] == [
        "postgresql: missing datasets column: extraction_lineage_id"
    ]
    assert "url" not in str(report).lower()
