#!/usr/bin/env python3
"""Recompute every reported number of the blinded complex-query assessment from public files.

Usage:
    python scripts/analyze_complex_query_results.py --out build/complex_query_evaluation_v1
    python scripts/analyze_complex_query_results.py --check   # compare with the committed tables

Outputs one CSV per table: per-query and summary ranking metrics with bootstrap intervals, the
paired OmicsPlorer-versus-comparator nDCG@10 differences with sign-flip p-values and Holm
adjustment, response availability, condition-based metrics, collector wall time, and the two
post-hoc analyses (returned-candidate yield and the subsets of queries with comparator results).
With --check, nothing is written; the recomputed values are compared with the committed tables in
`<results>/derived` (tolerance 1e-12) and the exit status reports the outcome.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.external.complex_query_results import (
    analyze,
    compare_tables,
    load_public_results,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=Path("results/complex_query_evaluation_v1"))
    parser.add_argument("--criteria", type=Path,
                        default=Path("protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed tables instead of writing files")
    args = parser.parse_args()
    results = load_public_results(args.results, args.criteria)
    if args.check:
        problems = compare_tables(args.results / "derived", analyze(results, None))
        for problem in problems[:20]:
            print(problem)
        print(f"{'FAIL' if problems else 'OK'}: recomputed tables vs {args.results / 'derived'} "
              f"({len(problems)} differences)")
        return 1 if problems else 0
    outputs = analyze(results, args.out or args.results / "derived")
    summary = {(row["system"], row["metric"]): row for row in outputs["metrics_summary"]}
    print(json.dumps({
        system: {
            "ndcg_at_10": round(summary[(system, "ndcg_at_10")]["mean"], 3),
            "ci95": [round(summary[(system, "ndcg_at_10")]["ci95_low"], 3),
                     round(summary[(system, "ndcg_at_10")]["ci95_high"], 3)],
        }
        for system in ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
