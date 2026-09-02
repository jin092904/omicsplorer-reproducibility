#!/usr/bin/env python3
"""Build the blinded Korean workbook and restricted unblinding key."""
from __future__ import annotations

import argparse
from pathlib import Path

from genofinder_eval.external.complex_query_judgment import (
    DEFAULT_SEED,
    export_judgment_workbook,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--criteria", type=Path, required=True)
    parser.add_argument("--review-ko", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--salt",
        help="Optional exact-rerun salt; omit for secure generation and keep it restricted",
    )
    args = parser.parse_args()
    manifest = export_judgment_workbook(
        run_dir=args.run.resolve(),
        query_csv=args.queries.resolve(),
        criteria_csv=args.criteria.resolve(),
        review_ko=args.review_ko.resolve(),
        output_dir=args.output.resolve(),
        seed=args.seed,
        salt=args.salt,
    )
    print(
        "created blinded workbook: "
        f"queries={manifest['query_count']} candidates={manifest['candidate_count']} "
        f"sessions={len(manifest['session_batch_counts'])}"
    )
    print("restricted files were created separately; do not open them before unblinding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
