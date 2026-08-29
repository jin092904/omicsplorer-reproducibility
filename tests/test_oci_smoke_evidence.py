from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from genofinder_eval.oci_smoke_evidence import (
    OciSmokeEvidenceError,
    validate_smoke_evidence,
)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(
    tmp_path: Path,
    *,
    smoke_mutator: Callable[[dict[str, Any]], None] | None = None,
    bundle_mutator: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path, Path]:
    entrypoint = [
        "python",
        "-m",
        "uvicorn",
        "src.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    image = {
        "schema_version": "omicsplorer-oci-image-evidence-v1",
        "evidence_status": "local_unpublished_image_candidate",
        "source": {"product_git_commit": "1" * 40},
        "image": {
            "archive_sha256": "2" * 64,
            "oci_manifest_digest": "sha256:" + "3" * 64,
            "image_config_digest": "sha256:" + "4" * 64,
            "declared_entrypoint": entrypoint,
        },
        "publication_status": "not_published",
    }
    bundle: dict[str, Any] = {
        "ociVersion": "1.0.0",
        "root": {"path": "rootfs", "readonly": True},
        "process": {
            "user": {"uid": 1001, "gid": 1001},
            "args": entrypoint,
            "noNewPrivileges": True,
            "capabilities": {
                "bounding": [],
                "effective": [],
                "inheritable": [],
                "permitted": [],
                "ambient": [],
            },
        },
        "linux": {
            "namespaces": [
                {"type": value}
                for value in ("pid", "network", "ipc", "uts", "user", "mount")
            ]
        },
    }
    if bundle_mutator is not None:
        bundle_mutator(bundle)
    image_path = tmp_path / "image.json"
    bundle_path = tmp_path / "config.json"
    _write(image_path, image)
    _write(bundle_path, bundle)
    smoke: dict[str, Any] = {
        "schema_version": "omicsplorer-declared-user-smoke-evidence-v1",
        "recorded_at_utc": "2026-08-29T09:10:02Z",
        "execution": {
            "started_at_utc": "2026-08-29T09:09:41Z",
            "ended_at_utc": "2026-08-29T09:09:47Z",
            "container_id": "test-smoke",
            "method": "direct_crun_oci_bundle",
            "runtime_name": "crun",
            "runtime_version": "0.17",
            "docker_service_run": False,
            "podman_service_run": False,
            "runtime_user_override_for_main_process": False,
        },
        "image_binding": {
            "product_git_commit": "1" * 40,
            "archive_sha256": "2" * 64,
            "oci_manifest_digest": "sha256:" + "3" * 64,
            "image_config_digest": "sha256:" + "4" * 64,
            "container_image_evidence_sha256": _sha256(image_path),
            "oci_bundle_config_sha256": _sha256(bundle_path),
        },
        "main_process": {
            "entrypoint": entrypoint,
            "name": "python",
            "real_effective_saved_filesystem_uids": [1001, 1001, 1001, 1001],
            "real_effective_saved_filesystem_gids": [1001, 1001, 1001, 1001],
            "capability_bounding_set_hex": "0000000000000000",
            "no_new_privileges": True,
        },
        "isolation": {
            "root_filesystem_read_only": True,
            "configured_namespaces": ["pid", "network", "ipc", "uts", "user", "mount"],
            "health_probe_origin": "loopback inside the same isolated network namespace",
            "host_port_published": False,
        },
        "health_probe": {
            "method": "GET",
            "url": "http://127.0.0.1:8000/api/v1/health",
            "http_status": 200,
            "readiness_poll_attempt": 10,
            "readiness_poll_interval_seconds": 0.25,
            "latency_measurement": False,
        },
        "cleanup": {
            "termination_signal": "TERM",
            "container_deleted": True,
            "matching_container_id_after_cleanup": False,
            "unrelated_runtime_containers_modified": False,
        },
        "environment_limitations": {
            "docker_socket_readable": False,
            "rootless_podman_subuid_range_configured": False,
            "rootless_podman_subgid_range_configured": False,
            "ordinary_docker_or_podman_service_validation_completed": False,
        },
        "result": "pass_startup_only",
        "evidence_boundary": (
            "This is not a Docker or Podman service run and does not establish "
            "retrieval correctness or latency."
        ),
    }
    if smoke_mutator is not None:
        smoke_mutator(smoke)
    smoke_path = tmp_path / "smoke.json"
    _write(smoke_path, smoke)
    return smoke_path, image_path, bundle_path


def test_valid_evidence_returns_hash_bound_startup_only_report(tmp_path: Path) -> None:
    smoke, image, bundle = _fixture(tmp_path)

    report = validate_smoke_evidence(smoke, image, bundle)

    assert report["validation_status"] == "pass"
    assert report["startup_observation"]["main_process_uid"] == 1001
    assert report["startup_observation"]["health_http_status"] == 200
    assert report["startup_observation"]["result"] == "pass_startup_only"
    assert report["publication_status"] == "not_published"
    assert "does not replay" in report["evidence_boundary"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["image_binding"].__setitem__("archive_sha256", "0" * 64),
            "archive_sha256",
        ),
        (
            lambda value: value["main_process"].__setitem__("entrypoint", ["wrong"]),
            "entrypoint",
        ),
        (
            lambda value: value["health_probe"].__setitem__("latency_measurement", True),
            "latency measurement",
        ),
        (
            lambda value: value.__setitem__("evidence_boundary", "does not establish retrieval latency"),
            "relabelling",
        ),
    ],
)
def test_rejects_contradictory_smoke_claims(
    tmp_path: Path,
    mutator: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    smoke, image, bundle = _fixture(tmp_path, smoke_mutator=mutator)

    with pytest.raises(OciSmokeEvidenceError, match=message):
        validate_smoke_evidence(smoke, image, bundle)


def test_rejects_bundle_without_read_only_root(tmp_path: Path) -> None:
    def writable_root(bundle: dict[str, Any]) -> None:
        bundle["root"]["readonly"] = False

    smoke, image, bundle = _fixture(tmp_path, bundle_mutator=writable_root)

    with pytest.raises(OciSmokeEvidenceError, match="read-only root"):
        validate_smoke_evidence(smoke, image, bundle)


def test_rejects_image_evidence_changed_after_binding(tmp_path: Path) -> None:
    smoke, image, bundle = _fixture(tmp_path)
    value = json.loads(image.read_text(encoding="utf-8"))
    value["publication_status"] = "changed"
    _write(image, value)

    with pytest.raises(OciSmokeEvidenceError, match="image evidence SHA-256"):
        validate_smoke_evidence(smoke, image, bundle)
