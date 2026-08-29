from __future__ import annotations

import hashlib
import json

from genofinder_eval.cross_store_snapshot import (
    StoreSnapshot,
    build_report,
    canonical_lines_sha256,
    canonical_membership_sha256,
)


def _hash(lines: list[str]) -> str:
    return hashlib.sha256("".join(f"{line}\n" for line in sorted(lines)).encode()).hexdigest()


def _store(name: str, rows: list[tuple[str, str, str]]) -> StoreSnapshot:
    snapshot = StoreSnapshot(name=name, native_count=len(rows))
    for dataset_id, source_db, source_id in rows:
        snapshot.add(
            native_id=dataset_id,
            dataset_id=dataset_id,
            source_db=source_db,
            source_id=source_id,
        )
    return snapshot


def test_canonical_hashes_sort_and_use_trailing_newlines() -> None:
    assert canonical_lines_sha256(["b", "a"]) == _hash(["a", "b"])
    assert canonical_membership_sha256(
        [("SRA", "SRP2", "id-2"), ("GEO", "GSE1", "id-1")]
    ) == _hash(["SRA\tSRP2\tid-2", "GEO\tGSE1\tid-1"])


def test_equal_stores_are_ready_and_have_equal_hashes() -> None:
    rows = [("id-1", "GEO", "GSE1"), ("id-2", "SRA", "SRP2")]
    report, private = build_report(
        snapshot_id="snapshot-v1",
        postgresql=_store("postgresql", rows),
        qdrant=_store("qdrant", list(reversed(rows))),
        opensearch=_store("opensearch", rows),
    )

    assert report["ready_for_frozen_corpus"] is True
    assert report["blocking_reasons"] == []
    assert report["comparisons"] == {
        "postgresql_vs_qdrant": {
            "postgresql_only_count": 0,
            "qdrant_only_count": 0,
            "symmetric_difference_count": 0,
        },
        "postgresql_vs_opensearch": {
            "postgresql_only_count": 0,
            "opensearch_only_count": 0,
            "symmetric_difference_count": 0,
        },
        "qdrant_vs_opensearch": {
            "qdrant_only_count": 0,
            "opensearch_only_count": 0,
            "symmetric_difference_count": 0,
        },
        "cross_store_mismatch_count": 0,
        "membership_mismatch_id_count": 0,
    }
    hashes = {
        store["dataset_id_set_sha256"] for store in report["stores"].values()
    }
    assert len(hashes) == 1
    assert all(not values for values in private["dataset_id_differences"].values())


def test_identifier_differences_stay_out_of_aggregate_report() -> None:
    common = [("id-common", "GEO", "GSE1")]
    database = _store("postgresql", [*common, ("private-id-171", "SRA", "SRP9")])
    qdrant = _store("qdrant", common)
    opensearch = _store("opensearch", common)

    report, private = build_report(
        snapshot_id="snapshot-v1",
        postgresql=database,
        qdrant=qdrant,
        opensearch=opensearch,
    )

    assert report["ready_for_frozen_corpus"] is False
    assert report["comparisons"]["cross_store_mismatch_count"] == 1
    assert report["comparisons"]["postgresql_vs_qdrant"] == {
        "postgresql_only_count": 1,
        "qdrant_only_count": 0,
        "symmetric_difference_count": 1,
    }
    assert "private-id-171" not in json.dumps(report)
    assert private["dataset_id_differences"]["postgresql_not_qdrant"] == [
        "private-id-171"
    ]
    assert private["dataset_id_differences"]["postgresql_not_opensearch"] == [
        "private-id-171"
    ]


def test_membership_mismatch_is_separate_from_id_set_mismatch() -> None:
    report, private = build_report(
        snapshot_id="snapshot-v1",
        postgresql=_store("postgresql", [("id-1", "GEO", "GSE1")]),
        qdrant=_store("qdrant", [("id-1", "GEO", "GSE-wrong")]),
        opensearch=_store("opensearch", [("id-1", "GEO", "GSE1")]),
    )

    assert report["comparisons"]["cross_store_mismatch_count"] == 0
    assert report["comparisons"]["membership_mismatch_id_count"] == 1
    assert report["ready_for_frozen_corpus"] is False
    assert list(private["membership_mismatches"]) == ["id-1"]


def test_missing_duplicate_and_native_id_mismatch_are_blockers() -> None:
    database = StoreSnapshot("postgresql", native_count=3)
    database.add(native_id="native-other", dataset_id="id-1", source_db="GEO", source_id="GSE1")
    database.add(native_id="id-1", dataset_id="id-1", source_db="GEO", source_id="GSE2")
    database.add(native_id="id-2", dataset_id="id-2", source_db="", source_id="GSE3")
    qdrant = _store("qdrant", [("id-1", "GEO", "GSE1")])
    opensearch = _store("opensearch", [("id-1", "GEO", "GSE1")])

    report, _ = build_report(
        snapshot_id="snapshot-v1",
        postgresql=database,
        qdrant=qdrant,
        opensearch=opensearch,
    )

    database_report = report["stores"]["postgresql"]
    assert database_report["missing_identity_count"] == 1
    assert database_report["duplicate_dataset_id_count"] == 1
    assert database_report["conflicting_membership_count"] == 1
    assert database_report["native_id_mismatch_count"] == 1
    assert report["ready_for_frozen_corpus"] is False
