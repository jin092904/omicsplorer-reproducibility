"""Validate private evaluation-server handoff files before and after transfer."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from genofinder_eval.oci_archive import sha256_file

SCHEMA_VERSION = "omicsplorer-evaluation-server-handoff-v1"
REPORT_SCHEMA_VERSION = "omicsplorer-evaluation-server-handoff-validation-v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,127}")


class EvaluationHandoffError(RuntimeError):
    """Raised when a handoff manifest or retained file is invalid."""


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationHandoffError("handoff manifest path is not a file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EvaluationHandoffError("handoff manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise EvaluationHandoffError("handoff manifest must contain an object")
    return value


def _object(parent: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise EvaluationHandoffError(f"{label} must be an object")
    return value


def _string(parent: Mapping[str, Any], key: str, label: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationHandoffError(f"{label} must be a nonblank string")
    return value


def _boolean(parent: Mapping[str, Any], key: str, label: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise EvaluationHandoffError(f"{label} must be a boolean")
    return value


def _safe_transfer_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise EvaluationHandoffError("artifact transfer_path must be a safe relative POSIX path")
    return path


def _destination_file(root: Path, transfer_path: PurePosixPath) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*transfer_path.parts)).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise EvaluationHandoffError("artifact transfer_path escapes destination root") from exc
    return candidate


def _artifact_source(
    artifact: Mapping[str, Any],
    *,
    mode: Literal["source", "destination"],
    destination_root: Path | None,
) -> Path:
    transfer_path = _safe_transfer_path(
        _string(artifact, "transfer_path", "artifact transfer_path")
    )
    if mode == "source":
        source = Path(_string(artifact, "source_path", "artifact source_path"))
        if not source.is_absolute():
            raise EvaluationHandoffError("artifact source_path must be absolute in source mode")
        return source
    if destination_root is None:  # pragma: no cover - guarded by public API
        raise EvaluationHandoffError("destination root is required in destination mode")
    return _destination_file(destination_root, transfer_path)


def _validate_repositories(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise EvaluationHandoffError("public_repositories must be a nonempty array")
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise EvaluationHandoffError("public repository entry must be an object")
        name = _string(raw, "name", "public repository name")
        url = _string(raw, "url", "public repository URL")
        commit = _string(raw, "commit", "public repository commit")
        if name in seen:
            raise EvaluationHandoffError("public repository names must be unique")
        if not url.startswith("https://github.com/"):
            raise EvaluationHandoffError("public repository URL must be an HTTPS GitHub URL")
        if not _COMMIT_RE.fullmatch(commit):
            raise EvaluationHandoffError("public repository commit must be 40 lowercase hex")
        if raw.get("final_release_tag_status") not in {"not_created", "created"}:
            raise EvaluationHandoffError("public repository release-tag status is invalid")
        seen.add(name)
        result.append({"name": name, "url": url, "commit": commit})
    return result


def validate_handoff(
    manifest_path: Path,
    *,
    mode: Literal["source", "destination"],
    destination_root: Path | None = None,
) -> dict[str, Any]:
    """Hash and validate every transfer artifact in source or destination mode."""

    if mode == "source" and destination_root is not None:
        raise EvaluationHandoffError("destination root is not used in source mode")
    if mode == "destination" and destination_root is None:
        raise EvaluationHandoffError("destination root is required in destination mode")
    manifest = _load_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationHandoffError("unsupported handoff schema_version")
    status = _string(manifest, "status", "handoff status")
    if status not in {"preliminary_private_transfer_candidate", "ready_for_secure_transfer"}:
        raise EvaluationHandoffError("unsupported handoff status")
    repositories = _validate_repositories(manifest.get("public_repositories"))

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise EvaluationHandoffError("artifacts must be a nonempty array")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    total_size = 0
    verified: list[dict[str, Any]] = []
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping):
            raise EvaluationHandoffError("artifact entry must be an object")
        artifact_id = _string(raw, "artifact_id", "artifact_id")
        if not _ID_RE.fullmatch(artifact_id) or artifact_id in seen_ids:
            raise EvaluationHandoffError("artifact_id is unsafe or duplicated")
        transfer_path_text = _string(raw, "transfer_path", "artifact transfer_path")
        _safe_transfer_path(transfer_path_text)
        if transfer_path_text in seen_paths:
            raise EvaluationHandoffError("artifact transfer_path is duplicated")
        expected_sha256 = _string(raw, "sha256", "artifact SHA-256")
        expected_size = raw.get("size_bytes")
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise EvaluationHandoffError("artifact SHA-256 must be 64 lowercase hex")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 1:
            raise EvaluationHandoffError("artifact size_bytes must be a positive integer")
        if raw.get("classification") not in {
            "private_production_derived",
            "private_operator_evidence",
        }:
            raise EvaluationHandoffError("artifact classification is invalid")
        if not _boolean(raw, "required_on_evaluation_server", "artifact required status"):
            raise EvaluationHandoffError("manifest artifacts must be required on evaluation server")
        if raw.get("publication_status") != "not_published":
            raise EvaluationHandoffError("transfer artifact must remain not_published")
        _string(raw, "purpose", "artifact purpose")
        path = _artifact_source(raw, mode=mode, destination_root=destination_root)
        if not path.is_file():
            raise EvaluationHandoffError(f"required artifact is missing: {artifact_id}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise EvaluationHandoffError(f"artifact size differs: {artifact_id}")
        if path.stat().st_mode & 0o077:
            raise EvaluationHandoffError(f"private artifact permissions are too broad: {artifact_id}")
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise EvaluationHandoffError(f"artifact SHA-256 differs: {artifact_id}")
        seen_ids.add(artifact_id)
        seen_paths.add(transfer_path_text)
        total_size += actual_size
        verified.append(
            {
                "artifact_id": artifact_id,
                "transfer_path": transfer_path_text,
                "size_bytes": actual_size,
                "sha256": actual_sha256,
            }
        )

    expected_total = manifest.get("total_transfer_size_bytes")
    if expected_total != total_size:
        raise EvaluationHandoffError("total_transfer_size_bytes differs from artifact sum")
    excluded = manifest.get("explicitly_excluded")
    if not isinstance(excluded, list) or not excluded:
        raise EvaluationHandoffError("explicitly_excluded must document omitted material")
    for raw in excluded:
        if not isinstance(raw, Mapping):
            raise EvaluationHandoffError("excluded entry must be an object")
        _string(raw, "name", "excluded name")
        _string(raw, "reason", "excluded reason")
        if raw.get("transfer") is not False:
            raise EvaluationHandoffError("excluded entry must have transfer=false")
    secrets = _object(manifest, "secrets", "secrets")
    if _boolean(secrets, "included", "secrets.included"):
        raise EvaluationHandoffError("handoff must not include credentials or secret values")
    if not _boolean(secrets, "create_new_on_target", "secrets.create_new_on_target"):
        raise EvaluationHandoffError("target must create new secrets")
    blockers = manifest.get("known_blockers")
    if not isinstance(blockers, list) or not blockers or not all(
        isinstance(value, str) and value.strip() for value in blockers
    ):
        raise EvaluationHandoffError("known_blockers must be a nonempty string array")
    boundary = _string(manifest, "evidence_boundary", "evidence_boundary").lower()
    for phrase in ("does not establish", "restore", "retrieval", "latency"):
        if phrase not in boundary:
            raise EvaluationHandoffError(f"evidence boundary must contain {phrase!r}")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "validation_status": "pass",
        "mode": mode,
        "handoff_status": status,
        "manifest_sha256": sha256_file(manifest_path),
        "public_repositories": repositories,
        "verified_artifact_count": len(verified),
        "verified_total_size_bytes": total_size,
        "verified_artifacts": verified,
        "known_blockers_retained": len(blockers),
        "evidence_boundary": (
            "This verifies manifest structure, private-file permissions, sizes, and SHA-256 "
            "values in one source or destination directory. It does not establish successful "
            "transfer, restore, store identity, application startup, retrieval correctness, "
            "latency, quality, publication, or submission readiness."
        ),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", action="store_true")
    mode.add_argument("--destination-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_mode: Literal["source", "destination"] = (
        "source" if args.source else "destination"
    )
    report = validate_handoff(
        args.manifest,
        mode=selected_mode,
        destination_root=args.destination_root,
    )
    _write_json(args.output, report)
    print(f"validation_status={report['validation_status']}")
    print(f"mode={report['mode']}")
    print(f"verified_artifact_count={report['verified_artifact_count']}")
    print(f"verified_total_size_bytes={report['verified_total_size_bytes']}")
    print(f"handoff_status={report['handoff_status']}")
    return 0
