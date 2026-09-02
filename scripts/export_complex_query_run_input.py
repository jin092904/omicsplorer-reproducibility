#!/usr/bin/env python3
"""Export the frozen complex-query workbook as external-run JSONL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.external.complex_query_input import export_collection_input


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-csv", type=Path, required=True)
    parser.add_argument("--criteria-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_collection_input(
        query_csv=args.query_csv.resolve(),
        criteria_csv=args.criteria_csv.resolve(),
        output_dir=args.output.resolve(),
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
