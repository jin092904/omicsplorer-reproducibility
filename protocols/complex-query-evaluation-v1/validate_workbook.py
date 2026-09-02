#!/usr/bin/env python3
"""Validate the blank/final complex-query human-evaluation workbook."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
QUERY_SHEET = ROOT / "01-query-authoring-sheet.csv"
CRITERIA_SHEET = ROOT / "02-expected-criteria-sheet.csv"
EXPECTED_COUNTS = {"simple": 20, "medium": 20, "complex": 20}
MIN_CONSTRAINTS = {"simple": 2, "medium": 3, "complex": 5}
CONSTRAINT_FIELDS = (
    "required_disease",
    "required_tissue",
    "required_cell_type",
    "required_organism",
    "required_modality",
    "required_design",
    "required_comparison_groups",
    "required_time_treatment_or_dose",
    "must_not_contain_or_condition",
)
GSE_LIST = re.compile(r"GSE[0-9]+(?:\|GSE[0-9]+)*")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def validate_structure(
    query_rows: list[dict[str, str]], criteria_rows: list[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    if len(query_rows) != 60:
        errors.append(f"query sheet must contain 60 rows; observed {len(query_rows)}")
    if len(criteria_rows) != 60:
        errors.append(f"criteria sheet must contain 60 rows; observed {len(criteria_rows)}")

    query_ids = [row["query_id"] for row in query_rows]
    criteria_ids = [row["query_id"] for row in criteria_rows]
    if len(set(query_ids)) != len(query_ids):
        errors.append("query sheet contains duplicate query_id values")
    if len(set(criteria_ids)) != len(criteria_ids):
        errors.append("criteria sheet contains duplicate query_id values")
    if set(query_ids) != set(criteria_ids):
        errors.append("query and criteria sheets have different query_id sets")

    for name, rows in (("query", query_rows), ("criteria", criteria_rows)):
        counts = Counter(row["difficulty"] for row in rows)
        if counts != Counter(EXPECTED_COUNTS):
            errors.append(
                f"{name} sheet difficulty counts must be {EXPECTED_COUNTS}; observed {dict(counts)}"
            )
    return errors


def validate_completed(
    query_rows: list[dict[str, str]], criteria_rows: list[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    query_by_id = {row["query_id"]: row for row in query_rows}
    criteria_by_id = {row["query_id"]: row for row in criteria_rows}

    for qid in sorted(query_by_id):
        query = query_by_id[qid]
        criteria = criteria_by_id[qid]

        for field in (
            "query_en",
            "query_ko",
            "original_language",
            "query_author",
            "author_role",
            "date_written",
        ):
            if not query[field]:
                errors.append(f"{qid}: missing query field {field}")
        if query["original_language"].lower() not in {"en", "ko"}:
            errors.append(f"{qid}: original_language must be en or ko")
        if query["results_not_seen_yes"].lower() != "yes":
            errors.append(f"{qid}: query results_not_seen_yes must be yes")

        filled_constraints = sum(bool(criteria[field]) for field in CONSTRAINT_FIELDS)
        minimum = MIN_CONSTRAINTS[query["difficulty"]]
        if filled_constraints < minimum:
            errors.append(
                f"{qid}: {filled_constraints} expected constraints; {minimum}+ required for {query['difficulty']}"
            )

        for field in (
            "why_this_query_is_realistic",
            "criteria_author",
            "date_written",
        ):
            if not criteria[field]:
                errors.append(f"{qid}: missing criteria field {field}")
        if criteria["results_not_seen_yes"].lower() != "yes":
            errors.append(f"{qid}: criteria results_not_seen_yes must be yes")

        # An AI-assisted prespecification may be useful as a working draft, but it
        # must not be frozen as the human-authored reference standard until the
        # study author has checked and accepted every row.
        ai_draft = criteria["criteria_author"].lower().startswith("openai codex")
        review_pending = "review required before freeze" in criteria["notes"].lower()
        if ai_draft or review_pending:
            errors.append(f"{qid}: expected criteria still require human review")

        known = criteria["known_relevant_gse"]
        evidence = criteria["accession_evidence_url"]
        if known and not GSE_LIST.fullmatch(known):
            errors.append(
                f"{qid}: known_relevant_gse must look like GSE123|GSE456"
            )
        if known and not evidence:
            errors.append(f"{qid}: known GSE requires accession_evidence_url")
        if evidence and not known:
            errors.append(f"{qid}: accession_evidence_url supplied without known GSE")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--final",
        action="store_true",
        help="Require human review and all prespecified constraint counts",
    )
    args = parser.parse_args(argv)

    query_rows = read_csv(QUERY_SHEET)
    criteria_rows = read_csv(CRITERIA_SHEET)
    errors = validate_structure(query_rows, criteria_rows)
    if args.final:
        errors.extend(validate_completed(query_rows, criteria_rows))

    completed_queries = sum(
        bool(row["query_en"] and row["query_ko"]) for row in query_rows
    )
    completed_criteria = sum(
        sum(bool(row[field]) for field in CONSTRAINT_FIELDS)
        >= MIN_CONSTRAINTS[row["difficulty"]]
        and bool(row["why_this_query_is_realistic"])
        for row in criteria_rows
    )

    print(f"query rows: {len(query_rows)}; bilingual questions complete: {completed_queries}/60")
    print(f"criteria rows meeting minimum fields: {completed_criteria}/60")
    if errors:
        print(f"validation: FAIL ({len(errors)} issue(s))")
        for error in errors[:100]:
            print(f"- {error}")
        if len(errors) > 100:
            print(f"- ... {len(errors) - 100} additional issue(s)")
        return 1
    print("validation: PASS")
    if not args.final:
        print("draft mode checks structure only; use --final before freezing the workbook")
    return 0


if __name__ == "__main__":
    sys.exit(main())
