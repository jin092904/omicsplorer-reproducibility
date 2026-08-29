"""Cross-check declared-user startup evidence against OCI image evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from genofinder_eval.oci_archive import sha256_file

SCHEMA_VERSION = "omicsplorer-declared-user-smoke-evidence-v1"
VALIDATION_SCHEMA_VERSION = "omicsplorer-smoke-evidence-validation-v1"
IMAGE_SCHEMA_VERSION = "omicsplorer-oci-image-evidence-v1"
_ZERO_HEX_RE = re.compile(r"0+")


class OciSmokeEvidenceError(RuntimeError):
    """Raised when startup evidence is incomplete or internally inconsistent."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise OciSmokeEvidenceError(f"{label} path is not a file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OciSmokeEvidenceError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OciSmokeEvidenceError(f"{label} must contain an object")
    return value


def _object(parent: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise OciSmokeEvidenceError(f"{label} must be an object")
    return value


def _string(parent: Mapping[str, Any], key: str, label: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OciSmokeEvidenceError(f"{label} must be a nonblank string")
    return value


def _boolean(parent: Mapping[str, Any], key: str, label: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise OciSmokeEvidenceError(f"{label} must be a boolean")
    return value


def _string_list(parent: Mapping[str, Any], key: str, label: str) -> list[str]:
    value = parent.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise OciSmokeEvidenceError(f"{label} must be a nonempty string array")
    return list(value)


def _identity_quad(parent: Mapping[str, Any], key: str, label: str) -> list[int]:
    value = parent.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        raise OciSmokeEvidenceError(f"{label} must contain four integer IDs")
    return list(value)


def _timestamp(parent: Mapping[str, Any], key: str, label: str) -> datetime:
    value = _string(parent, key, label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OciSmokeEvidenceError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise OciSmokeEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _expect_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise OciSmokeEvidenceError(f"{label} does not match its bound evidence")


def validate_smoke_evidence(
    smoke_path: Path,
    image_path: Path,
    bundle_config_path: Path,
) -> dict[str, Any]:
    """Validate cross-file bindings and required startup-evidence boundaries.

    This validates retained records. It does not replay the recorded process or
    independently establish that the reported health observation occurred.
    """

    smoke = _load_object(smoke_path, "smoke evidence")
    image = _load_object(image_path, "image evidence")
    bundle = _load_object(bundle_config_path, "OCI bundle config")
    if smoke.get("schema_version") != SCHEMA_VERSION:
        raise OciSmokeEvidenceError("unsupported smoke evidence schema_version")
    if image.get("schema_version") != IMAGE_SCHEMA_VERSION:
        raise OciSmokeEvidenceError("unsupported image evidence schema_version")
    _string(image, "evidence_status", "image evidence status")
    publication_status = _string(image, "publication_status", "image publication status")

    recorded = _timestamp(smoke, "recorded_at_utc", "recorded_at_utc")
    execution = _object(smoke, "execution", "execution")
    started = _timestamp(execution, "started_at_utc", "execution.started_at_utc")
    ended = _timestamp(execution, "ended_at_utc", "execution.ended_at_utc")
    if not started <= ended <= recorded:
        raise OciSmokeEvidenceError("smoke timestamps are not ordered")
    method = _string(execution, "method", "execution.method")
    runtime_name = _string(execution, "runtime_name", "execution.runtime_name")
    runtime_version = _string(execution, "runtime_version", "execution.runtime_version")
    _string(execution, "container_id", "execution.container_id")
    docker_run = _boolean(execution, "docker_service_run", "execution.docker_service_run")
    podman_run = _boolean(execution, "podman_service_run", "execution.podman_service_run")
    if docker_run and podman_run:
        raise OciSmokeEvidenceError("one observation cannot be both a Docker and Podman run")
    if method == "direct_crun_oci_bundle" and (docker_run or podman_run):
        raise OciSmokeEvidenceError("direct crun evidence cannot be labelled Docker or Podman")
    if _boolean(
        execution,
        "runtime_user_override_for_main_process",
        "execution.runtime_user_override_for_main_process",
    ):
        raise OciSmokeEvidenceError("main-process runtime user override is not eligible")

    binding = _object(smoke, "image_binding", "image_binding")
    image_source = _object(image, "source", "image evidence source")
    image_data = _object(image, "image", "image evidence image")
    image_sha256 = sha256_file(image_path)
    bundle_sha256 = sha256_file(bundle_config_path)
    _expect_equal(
        _string(binding, "container_image_evidence_sha256", "image evidence SHA-256"),
        image_sha256,
        "image evidence SHA-256",
    )
    _expect_equal(
        _string(binding, "oci_bundle_config_sha256", "OCI bundle config SHA-256"),
        bundle_sha256,
        "OCI bundle config SHA-256",
    )
    bound_fields = {
        "product_git_commit": image_source.get("product_git_commit"),
        "archive_sha256": image_data.get("archive_sha256"),
        "oci_manifest_digest": image_data.get("oci_manifest_digest"),
        "image_config_digest": image_data.get("image_config_digest"),
    }
    for key, expected in bound_fields.items():
        _expect_equal(_string(binding, key, f"image_binding.{key}"), expected, key)

    image_entrypoint = _string_list(
        image_data, "declared_entrypoint", "image declared entrypoint"
    )
    process = _object(bundle, "process", "OCI bundle process")
    bundle_args = _string_list(process, "args", "OCI bundle process args")
    main_process = _object(smoke, "main_process", "main_process")
    smoke_entrypoint = _string_list(main_process, "entrypoint", "main_process.entrypoint")
    _expect_equal(bundle_args, image_entrypoint, "OCI bundle process args")
    _expect_equal(smoke_entrypoint, image_entrypoint, "recorded main-process entrypoint")

    bundle_user = _object(process, "user", "OCI bundle process user")
    bundle_uid = bundle_user.get("uid")
    bundle_gid = bundle_user.get("gid")
    if not isinstance(bundle_uid, int) or isinstance(bundle_uid, bool) or bundle_uid <= 0:
        raise OciSmokeEvidenceError("OCI bundle process UID must be a non-root integer")
    if not isinstance(bundle_gid, int) or isinstance(bundle_gid, bool) or bundle_gid <= 0:
        raise OciSmokeEvidenceError("OCI bundle process GID must be a non-root integer")
    uids = _identity_quad(
        main_process,
        "real_effective_saved_filesystem_uids",
        "main-process UIDs",
    )
    gids = _identity_quad(
        main_process,
        "real_effective_saved_filesystem_gids",
        "main-process GIDs",
    )
    if any(uid != bundle_uid for uid in uids) or any(gid != bundle_gid for gid in gids):
        raise OciSmokeEvidenceError("recorded main-process IDs differ from OCI bundle user")

    if process.get("noNewPrivileges") is not True or main_process.get("no_new_privileges") is not True:
        raise OciSmokeEvidenceError("no-new-privileges was not retained across the record")
    capabilities = _object(process, "capabilities", "OCI bundle capabilities")
    for capability_set in ("bounding", "effective", "inheritable", "permitted", "ambient"):
        if capabilities.get(capability_set) != []:
            raise OciSmokeEvidenceError(
                f"OCI bundle capability {capability_set} set is not empty"
            )
    capability_hex = _string(
        main_process, "capability_bounding_set_hex", "main-process capability bounding set"
    )
    if not _ZERO_HEX_RE.fullmatch(capability_hex):
        raise OciSmokeEvidenceError("recorded main-process capability bounding set is not zero")

    isolation = _object(smoke, "isolation", "isolation")
    bundle_root = _object(bundle, "root", "OCI bundle root")
    if bundle_root.get("readonly") is not True or isolation.get("root_filesystem_read_only") is not True:
        raise OciSmokeEvidenceError("read-only root filesystem is not retained across the record")
    linux = _object(bundle, "linux", "OCI bundle linux")
    raw_namespaces = linux.get("namespaces")
    if not isinstance(raw_namespaces, list):
        raise OciSmokeEvidenceError("OCI bundle namespaces must be an array")
    namespace_types: list[str] = []
    for value in raw_namespaces:
        if not isinstance(value, Mapping):
            raise OciSmokeEvidenceError("OCI bundle namespace entry must be an object")
        namespace_types.append(_string(value, "type", "OCI bundle namespace type"))
    if len(namespace_types) != len(set(namespace_types)) or "network" not in namespace_types:
        raise OciSmokeEvidenceError("OCI bundle must have distinct namespaces including network")
    recorded_namespaces = _string_list(
        isolation, "configured_namespaces", "recorded configured namespaces"
    )
    _expect_equal(recorded_namespaces, namespace_types, "recorded configured namespaces")
    if _boolean(isolation, "host_port_published", "isolation.host_port_published"):
        raise OciSmokeEvidenceError("startup-only evidence must not publish a host port")
    probe_origin = _string(isolation, "health_probe_origin", "isolation.health_probe_origin")
    if "loopback" not in probe_origin.lower():
        raise OciSmokeEvidenceError("health probe origin must state its loopback boundary")

    health = _object(smoke, "health_probe", "health_probe")
    if health.get("method") != "GET" or health.get("http_status") != 200:
        raise OciSmokeEvidenceError("health probe must record GET with HTTP 200")
    parsed_url = urlparse(_string(health, "url", "health_probe.url"))
    if parsed_url.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise OciSmokeEvidenceError("health probe URL must use loopback")
    if parsed_url.path != "/api/v1/health":
        raise OciSmokeEvidenceError("health probe URL has an unexpected path")
    if _boolean(health, "latency_measurement", "health_probe.latency_measurement"):
        raise OciSmokeEvidenceError("readiness polling must not be labelled latency measurement")
    readiness_attempt = health.get("readiness_poll_attempt")
    readiness_interval = health.get("readiness_poll_interval_seconds")
    if (
        not isinstance(readiness_attempt, int)
        or isinstance(readiness_attempt, bool)
        or readiness_attempt < 1
    ):
        raise OciSmokeEvidenceError("health readiness-poll attempt must be a positive integer")
    if (
        not isinstance(readiness_interval, (int, float))
        or isinstance(readiness_interval, bool)
        or readiness_interval <= 0
    ):
        raise OciSmokeEvidenceError("health readiness-poll interval must be positive")

    cleanup = _object(smoke, "cleanup", "cleanup")
    _string(cleanup, "termination_signal", "cleanup.termination_signal")
    required_cleanup = {
        "container_deleted": True,
        "matching_container_id_after_cleanup": False,
        "unrelated_runtime_containers_modified": False,
    }
    for key, expected in required_cleanup.items():
        if _boolean(cleanup, key, f"cleanup.{key}") is not expected:
            raise OciSmokeEvidenceError(f"cleanup.{key} is not eligible")

    limitations = _object(smoke, "environment_limitations", "environment_limitations")
    for key in (
        "docker_socket_readable",
        "rootless_podman_subuid_range_configured",
        "rootless_podman_subgid_range_configured",
    ):
        _boolean(limitations, key, f"environment_limitations.{key}")
    ordinary_run = _boolean(
        limitations,
        "ordinary_docker_or_podman_service_validation_completed",
        "ordinary service validation status",
    )
    if ordinary_run != (docker_run or podman_run):
        raise OciSmokeEvidenceError("ordinary service-validation status contradicts execution labels")
    if smoke.get("result") != "pass_startup_only":
        raise OciSmokeEvidenceError("smoke result must be pass_startup_only")
    boundary = _string(smoke, "evidence_boundary", "evidence_boundary")
    boundary_lower = boundary.lower()
    for required_phrase in ("does not establish", "retrieval", "latency"):
        if required_phrase not in boundary_lower:
            raise OciSmokeEvidenceError(
                f"evidence boundary must include {required_phrase!r}"
            )
    if method == "direct_crun_oci_bundle" and "not a docker or podman service run" not in boundary_lower:
        raise OciSmokeEvidenceError("direct crun boundary must reject Docker/Podman relabelling")

    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "validation_status": "pass",
        "source_evidence": {
            "smoke_evidence_sha256": sha256_file(smoke_path),
            "container_image_evidence_sha256": image_sha256,
            "oci_bundle_config_sha256": bundle_sha256,
        },
        "image_binding": bound_fields,
        "startup_observation": {
            "method": method,
            "runtime_name": runtime_name,
            "runtime_version": runtime_version,
            "main_process_uid": bundle_uid,
            "main_process_gid": bundle_gid,
            "health_http_status": 200,
            "result": "pass_startup_only",
        },
        "publication_status": publication_status,
        "evidence_boundary": (
            "This validates cross-file hashes, configuration consistency, required fields, and "
            "claim boundaries in retained startup evidence. It does not replay the container, "
            "independently prove the reported health observation, or establish frozen-store "
            "connectivity, retrieval correctness, latency, quality, publication, or superiority."
        ),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-evidence", type=Path, required=True)
    parser.add_argument("--image-evidence", type=Path, required=True)
    parser.add_argument("--bundle-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_smoke_evidence(
        args.smoke_evidence,
        args.image_evidence,
        args.bundle_config,
    )
    _write_json(args.output, report)
    observation = _object(report, "startup_observation", "startup observation")
    binding = _object(report, "image_binding", "image binding")
    print(f"validation_status={report['validation_status']}")
    print(f"oci_manifest_digest={binding['oci_manifest_digest']}")
    print(f"method={observation['method']}")
    print(f"health_http_status={observation['health_http_status']}")
    print("result=pass_startup_only")
    return 0
