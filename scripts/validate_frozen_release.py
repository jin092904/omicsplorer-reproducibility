#!/usr/bin/env python3
"""Offline validator for an OmicsPlorer frozen evaluation release."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from genofinder_eval.external.provenance import write_json
from genofinder_eval.frozen_release import validate_release_directory

_MANUSCRIPT_PLACEHOLDERS = (
    r"\[Author(?:s|\s|\d)",
    r"\[Affiliation",
    r"\[Corresponding",
    r"\[email",
    r"\[(?:repository|archive|service) URL",
    r"\[(?:DOI|ORCID)",
    r"\b(?:TODO|TBD|REVIEW_REQUIRED|PLACEHOLDER)\b",
)


def validate_manuscript(path: Path) -> list[str]:
    if not path.is_file():
        return [f"manuscript is missing: {path}"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for pattern in _MANUSCRIPT_PLACEHOLDERS:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            errors.append(
                f"manuscript contains unresolved placeholder pattern {pattern!r} "
                f"({len(matches)} occurrence(s))"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--manuscript", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also require a supplied manuscript and reject author/repository placeholders",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="default: <release-dir>-validation-report.json beside the release",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    release_dir = args.release_dir.resolve()
    report: dict[str, Any] = validate_release_directory(release_dir)
    errors = list(report.get("errors") or [])
    if args.manuscript is not None:
        errors.extend(validate_manuscript(args.manuscript.resolve()))
    elif args.strict:
        errors.append("--strict requires --manuscript")
    report["errors"] = errors
    report["status"] = "GO" if not errors else "NO-GO"
    report["scope"] = (
        "frozen evaluation integrity plus manuscript placeholders"
        if args.manuscript is not None
        else "frozen evaluation integrity only"
    )
    report_path = (
        args.report.resolve()
        if args.report is not None
        else release_dir.parent / f"{release_dir.name}-validation-report.json"
    )
    write_json(report_path, report)
    print(f"RELEASE {report['status']}: {report_path}")
    for error in errors:
        print(f"- {error}")
    return 0 if report["status"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
