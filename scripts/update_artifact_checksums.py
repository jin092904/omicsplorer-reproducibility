#!/usr/bin/env python3
"""Write or verify SHA-256 checksums for public scientific artifacts."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ARTIFACTS.sha256"
ARTIFACT_ROOTS = (ROOT / "data", ROOT / "protocols", ROOT / "results")


def artifact_files() -> list[Path]:
    files: list[Path] = []
    for root in ARTIFACT_ROOTS:
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != "README.md"
        )
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def rendered_manifest() -> str:
    lines = []
    for path in artifact_files():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_manifest()
    if args.write:
        OUTPUT.write_text(expected, encoding="utf-8")
        print(f"wrote {len(artifact_files())} checksums to {OUTPUT}")
        return 0
    if not OUTPUT.is_file():
        print(f"missing checksum manifest: {OUTPUT}")
        return 1
    if OUTPUT.read_text(encoding="utf-8") != expected:
        print("artifact checksum manifest is stale")
        return 1
    print(f"verified {len(artifact_files())} artifact checksums")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
