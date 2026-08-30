from __future__ import annotations

from pathlib import Path

from genofinder_eval.frozen_release_public import validate_public_projection_directory

ROOT = Path(__file__).resolve().parents[1]


def test_committed_public_projection_requires_only_external_accession_attachment() -> None:
    report = validate_public_projection_directory(
        ROOT / "results" / "frozen_retrieval_v1"
    )
    assert report["status"] == "GO_WITH_EXTERNAL_ATTACHMENT_REQUIRED"
    assert report["errors"] == []
    assert report["artifacts_checked"] == 6
    assert report["observations_recomputed"] == 392
    assert report["publication_readiness_assessed"] is False
