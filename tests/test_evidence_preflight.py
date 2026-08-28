from __future__ import annotations

from genofinder_eval.evidence_preflight import (
    REQUIRED_DATASET_COLUMNS,
    ComponentResult,
    assess_dataset_columns,
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
