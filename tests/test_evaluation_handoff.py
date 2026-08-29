from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest

from genofinder_eval.evaluation_handoff import (
    EvaluationHandoffError,
    validate_handoff,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_private(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    path.chmod(0o600)


def _fixture(
    tmp_path: Path,
    *,
    mutator: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path]:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    one = source / "one.bin"
    two = source / "two.json"
    _write_private(one, b"private snapshot")
    _write_private(two, b'{"evidence":true}\n')
    _write_private(destination / "artifacts/one.bin", one.read_bytes())
    _write_private(destination / "evidence/two.json", two.read_bytes())
    artifacts = [
        {
            "artifact_id": "one-snapshot",
            "source_path": str(one),
            "transfer_path": "artifacts/one.bin",
            "size_bytes": one.stat().st_size,
            "sha256": _sha256(one),
            "classification": "private_production_derived",
            "required_on_evaluation_server": True,
            "publication_status": "not_published",
            "purpose": "synthetic snapshot fixture",
        },
        {
            "artifact_id": "two-evidence",
            "source_path": str(two),
            "transfer_path": "evidence/two.json",
            "size_bytes": two.stat().st_size,
            "sha256": _sha256(two),
            "classification": "private_operator_evidence",
            "required_on_evaluation_server": True,
            "publication_status": "not_published",
            "purpose": "synthetic evidence fixture",
        },
    ]
    manifest: dict[str, Any] = {
        "schema_version": "omicsplorer-evaluation-server-handoff-v1",
        "created_at_utc": "2026-08-29T00:00:00Z",
        "status": "preliminary_private_transfer_candidate",
        "public_repositories": [
            {
                "name": "omicsplorer-product",
                "url": "https://github.com/example/omicsplorer",
                "commit": "1" * 40,
                "final_release_tag_status": "not_created",
            }
        ],
        "artifacts": artifacts,
        "total_transfer_size_bytes": sum(value["size_bytes"] for value in artifacts),
        "explicitly_excluded": [
            {
                "name": "credentials",
                "reason": "create new values on target",
                "transfer": False,
            }
        ],
        "secrets": {"included": False, "create_new_on_target": True},
        "known_blockers": ["containerized restore not run"],
        "evidence_boundary": (
            "This does not establish transfer, restore, retrieval, or latency."
        ),
    }
    if mutator is not None:
        mutator(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path, destination


@pytest.mark.parametrize("mode", ["source", "destination"])
def test_validates_same_files_before_and_after_transfer(
    tmp_path: Path, mode: Literal["source", "destination"]
) -> None:
    manifest, destination = _fixture(tmp_path)

    report = validate_handoff(
        manifest,
        mode=mode,
        destination_root=destination if mode == "destination" else None,
    )

    assert report["validation_status"] == "pass"
    assert report["verified_artifact_count"] == 2
    assert report["verified_total_size_bytes"] == len(b"private snapshot") + len(
        b'{"evidence":true}\n'
    )
    assert "does not establish" in report["evidence_boundary"]


def test_rejects_same_size_changed_destination_bytes(tmp_path: Path) -> None:
    manifest, destination = _fixture(tmp_path)
    _write_private(destination / "artifacts/one.bin", b"changed snapshot")

    with pytest.raises(EvaluationHandoffError, match="SHA-256 differs"):
        validate_handoff(manifest, mode="destination", destination_root=destination)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["artifacts"][0].__setitem__(
                "transfer_path", "../escape.bin"
            ),
            "safe relative",
        ),
        (
            lambda value: value["artifacts"][1].__setitem__(
                "artifact_id", value["artifacts"][0]["artifact_id"]
            ),
            "unsafe or duplicated",
        ),
        (
            lambda value: value["secrets"].__setitem__("included", True),
            "must not include credentials",
        ),
        (
            lambda value: value["public_repositories"][0].__setitem__("commit", "main"),
            "40 lowercase hex",
        ),
    ],
)
def test_rejects_unsafe_or_unfrozen_manifest(
    tmp_path: Path,
    mutator: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    manifest, _ = _fixture(tmp_path, mutator=mutator)

    with pytest.raises(EvaluationHandoffError, match=message):
        validate_handoff(manifest, mode="source")


def test_rejects_broad_private_file_permissions(tmp_path: Path) -> None:
    manifest, _ = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    Path(value["artifacts"][0]["source_path"]).chmod(0o644)

    with pytest.raises(EvaluationHandoffError, match="permissions are too broad"):
        validate_handoff(manifest, mode="source")
