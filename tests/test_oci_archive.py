from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from genofinder_eval.oci_archive import (
    OciArchiveError,
    build_report,
    inspect_archive,
    inspect_source,
)


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _add(archive: tarfile.TarFile, name: str, value: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(value)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(value))


def _archive(path: Path, *, user: str = "app", tamper_layer: bool = False) -> None:
    entrypoint = ["python", "-m", "uvicorn", "src.main:app"]
    config_bytes = _json(
        {
            "created": "2026-08-29T00:00:00Z",
            "architecture": "amd64",
            "os": "linux",
            "config": {"User": user, "Entrypoint": entrypoint},
        }
    )
    layer_bytes = b"actual layer" if tamper_layer else b"layer"
    declared_layer_bytes = b"layer"
    manifest_bytes = _json(
        {
            "schemaVersion": 2,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": _digest(config_bytes),
                "size": len(config_bytes),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": _digest(declared_layer_bytes),
                    "size": len(layer_bytes),
                }
            ],
        }
    )
    index_bytes = _json(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": _digest(manifest_bytes),
                    "size": len(manifest_bytes),
                    "annotations": {"org.opencontainers.image.ref.name": "example:test"},
                }
            ],
        }
    )
    with tarfile.open(path, "w") as archive:
        _add(archive, "oci-layout", _json({"imageLayoutVersion": "1.0.0"}))
        _add(archive, "index.json", index_bytes)
        _add(
            archive,
            "blobs/sha256/" + _digest(manifest_bytes).removeprefix("sha256:"),
            manifest_bytes,
        )
        _add(
            archive,
            "blobs/sha256/" + _digest(config_bytes).removeprefix("sha256:"),
            config_bytes,
        )
        _add(
            archive,
            "blobs/sha256/" + _digest(declared_layer_bytes).removeprefix("sha256:"),
            layer_bytes,
        )


def _archive_with_duplicate_layout(path: Path) -> None:
    with tarfile.open(path, "w") as archive:
        layout = _json({"imageLayoutVersion": "1.0.0"})
        _add(archive, "oci-layout", layout)
        _add(archive, "oci-layout", layout)


def _run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source(repo: Path) -> str:
    (repo / "infra/docker").mkdir(parents=True)
    (repo / "apps/api").mkdir(parents=True)
    (repo / "infra/docker/Dockerfile.api").write_text(
        "# syntax=docker/dockerfile:1.7@sha256:" + "1" * 64 + "\n"
        "ARG PYTHON_IMAGE=python:3.12@sha256:" + "2" * 64 + "\n"
        "FROM ${PYTHON_IMAGE}\n"
        "USER app\n"
        'ENTRYPOINT ["python", "-m", "uvicorn", "src.main:app"]\n',
        encoding="utf-8",
    )
    (repo / "apps/api/uv.lock").write_text("version = 1\n", encoding="utf-8")
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.invalid")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "add", ".")
    _run(repo, "commit", "-qm", "fixture")
    return _run(repo, "rev-parse", "HEAD")


def test_archive_and_clean_source_build_hash_bound_report(tmp_path: Path) -> None:
    archive_path = tmp_path / "image.oci.tar"
    source_dir = tmp_path / "source"
    _archive(archive_path)
    commit = _source(source_dir)

    archive = inspect_archive(archive_path)
    source = inspect_source(
        source_dir,
        expected_commit=commit,
        dockerfile_relative="infra/docker/Dockerfile.api",
        lockfile_relative="apps/api/uv.lock",
    )
    report = build_report(
        archive=archive,
        source=source,
        builder_name="Podman",
        builder_version="3.4.4",
    )

    assert archive["verified_layer_count"] == 1
    assert archive["declared_user"] == "app"
    assert source["source_worktree_clean"] is True
    assert source["pinned_base_image_digests"] == ["sha256:" + "2" * 64]
    assert report["evidence_status"] == "local_unpublished_image_candidate"
    assert report["publication_status"] == "not_published"


@pytest.mark.parametrize(
    ("user", "tamper", "message"),
    [
        ("root", False, "non-root"),
        ("root:app", False, "non-root"),
        ("0:1001", False, "non-root"),
        ("app", True, "blob differs"),
    ],
)
def test_archive_rejects_root_user_or_tampered_layer(
    tmp_path: Path, user: str, tamper: bool, message: str
) -> None:
    archive_path = tmp_path / "image.oci.tar"
    _archive(archive_path, user=user, tamper_layer=tamper)

    with pytest.raises(OciArchiveError, match=message):
        inspect_archive(archive_path)


def test_archive_rejects_duplicate_member_path(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.oci.tar"
    _archive_with_duplicate_layout(archive_path)

    with pytest.raises(OciArchiveError, match="duplicate member path"):
        inspect_archive(archive_path)


def test_source_rejects_wrong_commit_or_dirty_tree(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    commit = _source(source_dir)
    kwargs: dict[str, Any] = {
        "dockerfile_relative": "infra/docker/Dockerfile.api",
        "lockfile_relative": "apps/api/uv.lock",
    }

    with pytest.raises(OciArchiveError, match="HEAD differs"):
        inspect_source(source_dir, expected_commit="0" * 40, **kwargs)

    (source_dir / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(OciArchiveError, match="not clean"):
        inspect_source(source_dir, expected_commit=commit, **kwargs)
