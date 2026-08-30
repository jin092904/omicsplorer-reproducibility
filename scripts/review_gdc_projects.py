#!/usr/bin/env python3
"""Review frozen GDC accessions against the unauthenticated official projects endpoint."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from genofinder_eval.external.provenance import utc_now, write_json
from genofinder_eval.frozen_release_public import (
    GDC_PROJECT_REVIEW_SCHEMA_VERSION,
    validate_gdc_project_review,
)

API_URL = "https://api.gdc.cancer.gov/projects"
DOCUMENTATION_URL = "https://docs.gdc.cancer.gov/API/Users_Guide/Search_and_Retrieval/"


def frozen_gdc_accessions(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not {"source_db", "accession"}.issubset(
            reader.fieldnames
        ):
            raise ValueError("accession manifest lacks source_db/accession columns")
        accessions = {
            str(row["accession"])
            for row in reader
            if str(row["source_db"]).upper() == "GDC" and str(row["accession"])
        }
    if not accessions:
        raise ValueError("accession manifest contains no GDC records")
    return accessions


def review_payload(response_payload: dict[str, Any], expected: set[str]) -> dict[str, Any]:
    data = response_payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
        raise ValueError("official GDC response lacks data.hits")
    projects: dict[str, dict[str, Any]] = {}
    for hit in data["hits"]:
        if not isinstance(hit, dict) or not isinstance(hit.get("project_id"), str):
            raise ValueError("official GDC response contains an invalid project record")
        projects[hit["project_id"]] = hit
    missing = expected - projects.keys()
    if missing:
        raise ValueError(f"official GDC projects endpoint did not return {len(missing)} records")
    records: list[dict[str, Any]] = []
    for accession in sorted(expected):
        project = projects[accession]
        state = project.get("state")
        released = project.get("released")
        if not isinstance(state, str) or not state:
            raise ValueError(f"GDC project {accession} lacks a state")
        if released is not True:
            raise ValueError(f"GDC project {accession} is not released")
        records.append(
            {
                "accession": accession,
                "entity_type": "project",
                "public_metadata_access": True,
                "released": True,
                "state": state,
                "study_level_only": True,
            }
        )
    return {
        "schema_version": GDC_PROJECT_REVIEW_SCHEMA_VERSION,
        "review_basis": (
            "unauthenticated response from the official GDC projects endpoint; confirms "
            "released public project metadata only, not that every associated file is open"
        ),
        "official_api_url": API_URL,
        "official_documentation_url": DOCUMENTATION_URL,
        "retrieved_at_utc": utc_now(),
        "api_response_sha256": hashlib.sha256(
            json.dumps(response_payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "record_count": len(records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accession-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = frozen_gdc_accessions(args.accession_manifest)
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            API_URL,
            params={"size": 2000, "fields": "project_id,state,released"},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("official GDC response is not an object")
    review = review_payload(payload, expected)
    write_json(args.output, review)
    validate_gdc_project_review(args.output, expected)
    state_counts: dict[str, int] = {}
    for record in review["records"]:
        state = str(record["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
    print(
        f"reviewed {len(expected)} released public GDC project records; "
        f"states={dict(sorted(state_counts.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
