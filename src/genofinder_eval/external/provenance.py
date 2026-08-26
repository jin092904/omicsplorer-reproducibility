"""Run-manifest helpers.  Secrets are deliberately excluded."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def git_value(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=False,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def git_binary(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=False,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return b""
    return result.stdout


def build_manifest(
    *,
    repo: Path,
    query_file: Path,
    systems: list[str],
    top_k: int,
    seed: int,
    protocol_version: str,
    api_key_used: bool,
) -> dict[str, Any]:
    status = git_binary(repo, "status", "--porcelain=v1", "--untracked-files=all")
    diff = git_binary(repo, "diff", "--binary", "HEAD")
    return {
        "protocol_version": protocol_version,
        "status": "running",
        "started_at_utc": utc_now(),
        "completed_at_utc": None,
        "git": {
            "commit": git_value(repo, "rev-parse", "HEAD"),
            "branch": git_value(repo, "branch", "--show-current"),
            "status_sha256": sha256_bytes(status),
            "tracked_diff_sha256": sha256_bytes(diff),
            "dirty": bool(status),
        },
        "query_file": str(query_file.resolve()),
        "query_file_sha256": sha256_file(query_file),
        "systems": systems,
        "top_k": top_k,
        "seed": seed,
        "ncbi_api_key_used": api_key_used,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "failures": 0,
        "responses": 0,
    }


def write_json(path: Path, value: Any) -> None:
    """Deterministic UTF-8 JSON with atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
