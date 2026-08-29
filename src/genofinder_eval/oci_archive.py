"""Validate a local OCI image archive against an exact clean product checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

SCHEMA_VERSION = "omicsplorer-oci-image-evidence-v1"
ACKNOWLEDGEMENT = "I_CONFIRM_THIS_IS_A_LOCAL_UNPUBLISHED_IMAGE_CANDIDATE"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_OCI_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
_MAX_JSON_BYTES = 16 * 1024 * 1024


class OciArchiveError(RuntimeError):
    """Raised when an OCI archive or its source binding is invalid."""


def _sha256_stream(handle: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return f"sha256:{digest.hexdigest()}", size


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        digest, _ = _sha256_stream(handle)
    return digest.removeprefix("sha256:")


def _read_small_json(archive: tarfile.TarFile, name: str) -> dict[str, Any]:
    try:
        member = archive.getmember(name)
    except KeyError as exc:
        raise OciArchiveError(f"OCI archive is missing {name}") from exc
    if not member.isfile() or not 0 < member.size <= _MAX_JSON_BYTES:
        raise OciArchiveError(f"OCI JSON member {name} has an invalid size or type")
    handle = archive.extractfile(member)
    if handle is None:  # pragma: no cover - tarfile defensive case
        raise OciArchiveError(f"OCI archive cannot read {name}")
    try:
        raw = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OciArchiveError(f"OCI member {name} is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise OciArchiveError(f"OCI member {name} must contain an object")
    return raw


def _blob_path(digest: str) -> str:
    if not _SHA256_RE.fullmatch(digest):
        raise OciArchiveError("OCI descriptor digest must be a full SHA-256")
    return f"blobs/sha256/{digest.removeprefix('sha256:')}"


def _descriptor(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OciArchiveError(f"{label} descriptor must be an object")
    digest = value.get("digest")
    size = value.get("size")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise OciArchiveError(f"{label} descriptor has an invalid digest")
    if not isinstance(size, int) or size < 1:
        raise OciArchiveError(f"{label} descriptor has an invalid size")
    return value


def _verify_descriptor(archive: tarfile.TarFile, descriptor: Mapping[str, Any], label: str) -> None:
    digest = str(descriptor["digest"])
    path = _blob_path(digest)
    try:
        member = archive.getmember(path)
    except KeyError as exc:
        raise OciArchiveError(f"OCI archive is missing the {label} blob") from exc
    if not member.isfile() or member.size != int(descriptor["size"]):
        raise OciArchiveError(f"OCI {label} blob size or type differs from its descriptor")
    handle = archive.extractfile(member)
    if handle is None:  # pragma: no cover - tarfile defensive case
        raise OciArchiveError(f"OCI archive cannot read the {label} blob")
    actual_digest, actual_size = _sha256_stream(handle)
    if actual_digest != digest or actual_size != int(descriptor["size"]):
        raise OciArchiveError(f"OCI {label} blob differs from its descriptor")


def _safe_archive_members(archive: tarfile.TarFile) -> None:
    seen_names: set[str] = set()
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise OciArchiveError("OCI archive contains an unsafe member path")
        if member.name in seen_names:
            raise OciArchiveError("OCI archive contains a duplicate member path")
        seen_names.add(member.name)
        if not (member.isfile() or member.isdir()):
            raise OciArchiveError("OCI archive contains an unsupported member type")


def _is_root_user(user: str) -> bool:
    principal = user.split(":", maxsplit=1)[0].strip().lower()
    if principal == "root":
        return True
    return principal.isdecimal() and int(principal) == 0


def inspect_archive(path: Path) -> dict[str, Any]:
    """Verify every referenced OCI blob and return aggregate image evidence."""

    if not path.is_file():
        raise OciArchiveError("OCI archive path is not a file")
    archive_sha256 = sha256_file(path)
    try:
        archive = tarfile.open(path, mode="r:*")
    except tarfile.TarError as exc:
        raise OciArchiveError("file is not a readable OCI tar archive") from exc
    with archive:
        _safe_archive_members(archive)
        layout = _read_small_json(archive, "oci-layout")
        if layout != {"imageLayoutVersion": "1.0.0"}:
            raise OciArchiveError("unsupported OCI image-layout version")
        index = _read_small_json(archive, "index.json")
        manifests = index.get("manifests")
        if index.get("schemaVersion") != 2 or not isinstance(manifests, list):
            raise OciArchiveError("OCI index is invalid")
        if len(manifests) != 1:
            raise OciArchiveError("OCI archive must contain exactly one manifest")
        manifest_descriptor = _descriptor(manifests[0], "manifest")
        if manifest_descriptor.get("mediaType") != _OCI_MANIFEST_MEDIA_TYPE:
            raise OciArchiveError("OCI index does not reference an OCI image manifest")
        _verify_descriptor(archive, manifest_descriptor, "manifest")
        manifest_path = _blob_path(str(manifest_descriptor["digest"]))
        manifest = _read_small_json(archive, manifest_path)
        if manifest.get("schemaVersion") != 2:
            raise OciArchiveError("OCI image manifest schemaVersion must be 2")
        config_descriptor = _descriptor(manifest.get("config"), "config")
        if config_descriptor.get("mediaType") != _OCI_CONFIG_MEDIA_TYPE:
            raise OciArchiveError("OCI manifest has an unsupported config mediaType")
        layers = manifest.get("layers")
        if not isinstance(layers, list) or not layers:
            raise OciArchiveError("OCI image manifest has no layers")
        layer_descriptors = [
            _descriptor(value, f"layer {layer_index}")
            for layer_index, value in enumerate(layers)
        ]
        descriptors = [config_descriptor, *layer_descriptors]
        digests = [str(value["digest"]) for value in descriptors]
        if len(digests) != len(set(digests)):
            raise OciArchiveError("OCI manifest repeats a config or layer digest")
        for descriptor_index, descriptor in enumerate(descriptors):
            label = "config" if descriptor_index == 0 else f"layer {descriptor_index - 1}"
            _verify_descriptor(archive, descriptor, label)
        config = _read_small_json(archive, _blob_path(str(config_descriptor["digest"])))

    image_config = config.get("config")
    if not isinstance(image_config, Mapping):
        raise OciArchiveError("OCI image config.config must be an object")
    user = str(image_config.get("User") or "").strip()
    if not user or _is_root_user(user):
        raise OciArchiveError("OCI image must declare a non-root default user")
    entrypoint = image_config.get("Entrypoint")
    if (
        not isinstance(entrypoint, list)
        or not entrypoint
        or not all(isinstance(value, str) and value for value in entrypoint)
    ):
        raise OciArchiveError("OCI image must declare a JSON-array entrypoint")
    architecture = str(config.get("architecture") or "")
    operating_system = str(config.get("os") or "")
    if not architecture or not operating_system:
        raise OciArchiveError("OCI image config omits platform")
    annotations = manifest_descriptor.get("annotations")
    return {
        "archive_sha256": archive_sha256,
        "archive_size_bytes": path.stat().st_size,
        "oci_manifest_digest": str(manifest_descriptor["digest"]),
        "image_config_digest": str(config_descriptor["digest"]),
        "verified_layer_count": len(layer_descriptors),
        "platform": f"{operating_system}/{architecture}",
        "created_at_utc": str(config.get("created") or ""),
        "declared_user": user,
        "declared_entrypoint": list(entrypoint),
        "index_annotations": dict(annotations) if isinstance(annotations, Mapping) else {},
        "all_referenced_descriptor_hashes_and_sizes_verified": True,
    }


def _git(source_dir: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_dir), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise OciArchiveError(f"git {' '.join(args)} failed for product source")
    return completed.stdout.strip()


def _source_file(source_dir: Path, relative: str, label: str) -> Path:
    candidate = (source_dir / relative).resolve()
    try:
        candidate.relative_to(source_dir.resolve())
    except ValueError as exc:
        raise OciArchiveError(f"{label} escapes the product checkout") from exc
    if not candidate.is_file():
        raise OciArchiveError(f"{label} is not a file")
    return candidate


def _dockerfile_contract(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    users = re.findall(r"(?m)^\s*USER\s+([^\s#]+)\s*$", text)
    entrypoints = re.findall(r"(?m)^\s*ENTRYPOINT\s+(\[[^\n]+\])\s*$", text)
    base_matches = re.findall(
        r"(?m)^\s*ARG\s+[A-Za-z_][A-Za-z0-9_]*=[^\s@]+@(sha256:[0-9a-f]{64})\s*$",
        text,
    )
    syntax_match = re.search(r"(?m)^#\s*syntax=[^\s@]+@(sha256:[0-9a-f]{64})\s*$", text)
    if not users or not entrypoints or not base_matches:
        raise OciArchiveError("Dockerfile lacks USER, JSON ENTRYPOINT, or pinned base digest")
    try:
        entrypoint = json.loads(entrypoints[-1])
    except json.JSONDecodeError as exc:
        raise OciArchiveError("Dockerfile ENTRYPOINT is not valid JSON") from exc
    if not isinstance(entrypoint, list) or not all(isinstance(value, str) for value in entrypoint):
        raise OciArchiveError("Dockerfile ENTRYPOINT must be a string array")
    return {
        "declared_user": users[-1],
        "declared_entrypoint": entrypoint,
        "pinned_base_image_digests": sorted(set(base_matches)),
        "pinned_dockerfile_frontend_digest": (syntax_match.group(1) if syntax_match else None),
    }


def inspect_source(
    source_dir: Path,
    *,
    expected_commit: str,
    dockerfile_relative: str,
    lockfile_relative: str,
) -> dict[str, Any]:
    if not _COMMIT_RE.fullmatch(expected_commit):
        raise OciArchiveError("expected product commit must be 40 lowercase hex characters")
    if _git(source_dir, "rev-parse", "HEAD") != expected_commit:
        raise OciArchiveError("product checkout HEAD differs from expected commit")
    if _git(source_dir, "status", "--porcelain=v1", "--untracked-files=all"):
        raise OciArchiveError("product checkout is not clean")
    dockerfile = _source_file(source_dir, dockerfile_relative, "Dockerfile")
    lockfile = _source_file(source_dir, lockfile_relative, "dependency lockfile")
    contract = _dockerfile_contract(dockerfile)
    return {
        "product_git_commit": expected_commit,
        "source_tree_sha": _git(source_dir, "rev-parse", "HEAD^{tree}"),
        "source_worktree_clean": True,
        "dockerfile_relative_path": dockerfile_relative,
        "dockerfile_sha256": sha256_file(dockerfile),
        "dependency_lock_relative_path": lockfile_relative,
        "dependency_lock_sha256": sha256_file(lockfile),
        **contract,
    }


def build_report(
    *,
    archive: Mapping[str, Any],
    source: Mapping[str, Any],
    builder_name: str,
    builder_version: str,
) -> dict[str, Any]:
    if archive.get("declared_user") != source.get("declared_user"):
        raise OciArchiveError("archive default user differs from Dockerfile USER")
    if archive.get("declared_entrypoint") != source.get("declared_entrypoint"):
        raise OciArchiveError("archive entrypoint differs from Dockerfile ENTRYPOINT")
    if not builder_name.strip() or not builder_version.strip():
        raise OciArchiveError("builder name and version must be nonblank")
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "evidence_status": "local_unpublished_image_candidate",
        "source": dict(source),
        "builder": {"name": builder_name.strip(), "version": builder_version.strip()},
        "image": dict(archive),
        "smoke_test_status": "separate_operator_evidence_required",
        "publication_status": "not_published",
        "evidence_boundary": (
            "This validates one local OCI archive and its clean source binding. It does not "
            "publish the image, run the retrieval stack, establish response traces, metadata "
            "accuracy, retrieval quality, latency, or superiority."
        ),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-product-commit", required=True)
    parser.add_argument("--dockerfile-relative", required=True)
    parser.add_argument("--lockfile-relative", required=True)
    parser.add_argument("--builder-name", required=True)
    parser.add_argument("--builder-version", required=True)
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.acknowledgement != ACKNOWLEDGEMENT:
        raise OciArchiveError(f"--acknowledgement must equal {ACKNOWLEDGEMENT!r}")
    archive = inspect_archive(args.archive)
    source = inspect_source(
        args.source_dir,
        expected_commit=args.expected_product_commit,
        dockerfile_relative=args.dockerfile_relative,
        lockfile_relative=args.lockfile_relative,
    )
    report = build_report(
        archive=archive,
        source=source,
        builder_name=args.builder_name,
        builder_version=args.builder_version,
    )
    _write_json(args.output, report)
    print(f"archive_sha256={archive['archive_sha256']}")
    print(f"oci_manifest_digest={archive['oci_manifest_digest']}")
    print(f"image_config_digest={archive['image_config_digest']}")
    print(f"product_git_commit={source['product_git_commit']}")
    print("source_archive_binding=pass")
    print("publication_status=not_published")
    return 0
