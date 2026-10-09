#!/usr/bin/env python3
"""Recompute every reported number of the v2 complex-query assessment from public files.

Usage:
    python scripts/analyze_complex_query_v2_results.py               # write <results>/derived
    python scripts/analyze_complex_query_v2_results.py --check       # compare with the committed tables

Outputs one CSV per table: per-query and summary ranking metrics with bootstrap intervals for the
v2 arms and the v1 systems on the extended qrels, the paired arm A-versus-keyword nDCG@10
differences with sign-flip p-values and Holm adjustment, difficulty strata, the overlap of
relevant candidates among arms A-C, the extended-pool sensitivity of the v1 systems, the retest
agreement, arm A versus the v1 OmicsPlorer path, and two sensitivity analyses (received grades
before correction; retest pairs graded with their v2 values). With --check, nothing is written;
the recomputed values are compared with the committed tables (tolerance 1e-12).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.external.complex_query_results import compare_tables
from genofinder_eval.external.complex_query_results_v2 import (
    MAIN_SYSTEMS,
    analyze_v2,
    load_public_results_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=Path("results/complex_query_evaluation_v2"))
    parser.add_argument("--v1-results", type=Path, default=Path("results/complex_query_evaluation_v1"))
    parser.add_argument("--criteria", type=Path,
                        default=Path("protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed tables instead of writing files")
    args = parser.parse_args()
    results = load_public_results_v2(args.results, args.v1_results, args.criteria)
    if args.check:
        problems = compare_tables(args.results / "derived", analyze_v2(results, None))
        for problem in problems[:20]:
            print(problem)
        print(f"{'FAIL' if problems else 'OK'}: recomputed tables vs {args.results / 'derived'} "
              f"({len(problems)} differences)")
        return 1 if problems else 0
    outputs = analyze_v2(results, args.out or args.results / "derived")
    summary = {(row["system"], row["metric"]): row for row in outputs["metrics_summary"]}
    print(json.dumps({
        system: {
            "ndcg_at_10": round(summary[(system, "ndcg_at_10")]["mean"], 3),
            "ci95": [round(summary[(system, "ndcg_at_10")]["ci95_low"], 3),
                     round(summary[(system, "ndcg_at_10")]["ci95_high"], 3)],
        }
        for system in MAIN_SYSTEMS
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
