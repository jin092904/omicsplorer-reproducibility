from __future__ import annotations

import gzip
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from genofinder_eval.corpus_manifest import (
    MANIFEST_SCHEMA_VERSION,
    CorpusExport,
    CorpusManifestError,
    build_stores_manifest,
    validate_export_against_audit,
    validate_zero_mismatch_audit,
    write_deterministic_gzip,
)
from genofinder_eval.cross_store_snapshot import SCHEMA_VERSION as AUDIT_SCHEMA_VERSION

ID_HASH = "1" * 64
MEMBERSHIP_HASH = "2" * 64


def _audit() -> dict[str, object]:
    shared = {
        "native_count": 2,
        "unique_dataset_id_count": 2,
        "dataset_id_set_sha256": ID_HASH,
        "accession_membership_sha256": MEMBERSHIP_HASH,
        "missing_identity_count": 0,
        "duplicate_dataset_id_count": 0,
        "conflicting_membership_count": 0,
        "native_id_mismatch_count": 0,
    }
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "snapshot_id": "gpb-snapshot-v1-intersection",
        "ready_for_frozen_corpus": True,
        "stores": {
            "postgresql": dict(shared),
            "qdrant": {**shared, "version": "1.12.1", "collection": "datasets_v2"},
            "opensearch": {**shared, "version": "3.6.0", "index": "datasets_v2"},
        },
        "comparisons": {
            "cross_store_mismatch_count": 0,
            "membership_mismatch_id_count": 0,
        },
        "blocking_reasons": [],
    }


def _export() -> CorpusExport:
    return CorpusExport(
        row_count=2,
        accession_membership_count=2,
        dataset_id_set_sha256=ID_HASH,
        accession_membership_sha256=MEMBERSHIP_HASH,
        tsv_sha256="3" * 64,
        tsv_size_bytes=123,
        schema_revision="0006_dataset_lineage",
        server_version="18.6",
    )


def test_build_manifest_binds_audit_membership_and_store_configuration() -> None:
    audit = _audit()
    manifest = build_stores_manifest(
        snapshot_id="gpb-snapshot-v1-intersection",
        qdrant_snapshot_id="qdrant-sha256:" + "4" * 64,
        opensearch_snapshot_id="opensearch-sha256:" + "5" * 64,
        audit=audit,
        audit_sha256="6" * 64,
        export=_export(),
        search_evidence={
            "qdrant": {
                "version": "1.12.1",
                "collection": "datasets_v2",
                "point_count": 2,
                "collection_config_sha256": "7" * 64,
            },
            "opensearch": {
                "version": "3.6.0",
                "index": "datasets_v2",
                "document_count": 2,
                "mapping_sha256": "8" * 64,
                "settings_sha256": "9" * 64,
            },
        },
    )

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["database"]["accession_membership_sha256"] == MEMBERSHIP_HASH  # type: ignore[index]
    assert manifest["qdrant"]["collection_config_sha256"] == "7" * 64  # type: ignore[index]
    assert manifest["opensearch"]["settings_sha256"] == "9" * 64  # type: ignore[index]
    assert manifest["cross_store_mismatch_count"] == 0
    assert "does not establish" in str(manifest["evidence_boundary"])


def test_audit_validation_rejects_nonzero_or_inconsistent_evidence() -> None:
    audit = _audit()
    validate_zero_mismatch_audit(audit, "gpb-snapshot-v1-intersection")

    changed = deepcopy(audit)
    comparisons = changed["comparisons"]
    assert isinstance(comparisons, dict)
    comparisons["membership_mismatch_id_count"] = 1
    with pytest.raises(CorpusManifestError, match="membership mismatch"):
        validate_zero_mismatch_audit(changed, "gpb-snapshot-v1-intersection")

    changed = deepcopy(audit)
    stores = changed["stores"]
    assert isinstance(stores, dict)
    qdrant = stores["qdrant"]
    assert isinstance(qdrant, dict)
    qdrant["dataset_id_set_sha256"] = "a" * 64
    with pytest.raises(CorpusManifestError, match="ID hashes differ"):
        validate_zero_mismatch_audit(changed, "gpb-snapshot-v1-intersection")


def test_export_must_equal_audit() -> None:
    validate_export_against_audit(_export(), _audit())
    changed = CorpusExport(**{**_export().__dict__, "row_count": 1})
    with pytest.raises(CorpusManifestError, match="differ from"):
        validate_export_against_audit(changed, _audit())


def test_deterministic_gzip_has_stable_bytes_and_round_trips(tmp_path: Path) -> None:
    source = tmp_path / "corpus.tsv"
    first = tmp_path / "first.tsv.gz"
    second = tmp_path / "second.tsv.gz"
    payload = b"source_db\taccession\nGEO\tGSE1\n"
    source.write_bytes(payload)

    write_deterministic_gzip(source, first)
    write_deterministic_gzip(source, second)

    assert first.read_bytes() == second.read_bytes()
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )
    assert gzip.decompress(first.read_bytes()) == payload
