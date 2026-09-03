#!/usr/bin/env python3
"""Merge compact session score sheets into the complete blinded workbook."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.external.complex_query_review_pack import merge_score_sheets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-log", type=Path)
    parser.add_argument("--mode", choices=("partial", "complete"), required=True)
    args = parser.parse_args()
    result = merge_score_sheets(
        template=args.template.resolve(),
        manifest_path=args.manifest.resolve(),
        score_dir=args.scores.resolve(),
        output=args.output.resolve(),
        mode=args.mode,
        session_log=args.session_log.resolve() if args.session_log else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
