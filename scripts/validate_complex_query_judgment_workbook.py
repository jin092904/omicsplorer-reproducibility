#!/usr/bin/env python3
"""Check a blinded judgment workbook without opening restricted system keys."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.external.complex_query_judgment_validation import (
    validate_judgment_workbook,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--session-log", type=Path)
    parser.add_argument("--mode", choices=("blank", "partial", "complete"), required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate_judgment_workbook(
        workbook=args.workbook.resolve(),
        template=args.template.resolve(),
        manifest_path=args.manifest.resolve(),
        mode=args.mode,
        session_log=args.session_log.resolve() if args.session_log else None,
    )
    payload = result.as_dict()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        args.report.chmod(0o600)
    status = "PASS" if result.valid else "FAIL"
    print(
        f"{status}: mode={result.mode} rows={result.row_count} "
        f"completed={result.completed_rows} remaining={result.remaining_rows} "
        f"queries={result.query_count} sessions={result.session_count}"
    )
    for message in result.errors:
        print(f"ERROR: {message}")
    for message in result.warnings:
        print(f"WARNING: {message}")
    return 0 if result.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
