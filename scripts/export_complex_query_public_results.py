#!/usr/bin/env python3
"""Project the private blinded complex-query assessment into public result files.

Inputs are the frozen private artifacts of `protocols/complex-query-evaluation-v1`: the final
judgment workbook, the restricted pool key, the raw collector run, and the adopted-correction log.
The output keeps only what the analysis needs and what may be redistributed:

- `qrels.tsv`: TREC qrels (query, 0, GEO Series accession, grade 0-3);
- `condition_judgments.csv`: per judged pair, the 1/0/NA condition judgements and the exclusion
  and insufficient-evidence flags;
- `rankings.csv`: each system's returned GEO Series accessions and ranks;
- `responses.csv`: per system and query, HTTP status, returned count, wall time, fetch time, and
  the SHA-256 of the private raw response;
- `judgment_corrections.csv`: fields corrected against GEO before system unblinding.

Titles, descriptions, other third-party text, free-text notes and reasons, internal OmicsPlorer
identifiers, and request parameters are not written.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from genofinder_eval.external.pooling import load_responses

SYSTEMS = ("ncbi_geo", "omicsdi_geo", "omicsplorer_geo")
REQUIREMENTS = (
    # workbook requirement text, workbook judgement, public criteria column, public output column
    ("필수_질병_상태", "질병_상태_충족_1_0_NA", "required_disease", "disease_met"),
    ("필수_조직_검체", "조직_검체_충족_1_0_NA", "required_tissue", "tissue_met"),
    ("필수_세포유형", "세포유형_충족_1_0_NA", "required_cell_type", "cell_type_met"),
    ("필수_생물종", "생물종_충족_1_0_NA", "required_organism", "organism_met"),
    ("필수_분석법", "분석법_충족_1_0_NA", "required_modality", "modality_met"),
    ("필수_연구설계", "연구설계_충족_1_0_NA", "required_design", "design_met"),
    ("필수_비교군", "비교군_충족_1_0_NA", "required_comparison_groups", "comparison_groups_met"),
    ("필수_시점_처치_용량", "시점_처치_용량_충족_1_0_NA", "required_time_treatment_or_dose",
     "time_treatment_or_dose_met"),
)
CORRECTED_FIELDS = {
    "관련성": "grade",
    "근거부족": "insufficient_evidence",
    "분석법": "modality_met",
    "생물종": "organism_met",
    "세포": "cell_type_met",
    "제외위반": "exclusion_violated",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def accession_from_url(url: str) -> str:
    match = re.search(r"[?&]acc=(GSE\d+)(?:$|[&#])", url, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot read a GEO Series accession from {url!r}")
    return match.group(1).upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--final-workbook", type=Path, required=True)
    parser.add_argument("--pool-key", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True, help="private collector run directory")
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--criteria", type=Path,
                        default=Path("protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    workbook = read_csv(args.final_workbook)
    key = {(row["질의ID"], row["후보코드"]): row for row in read_csv(args.pool_key)}
    criteria = {row["query_id"]: row for row in read_csv(args.criteria)}
    if len(workbook) != 739 or len(key) != 739:
        raise ValueError("expected 739 judged pairs in the workbook and the pool key")

    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    conditions: list[dict[str, object]] = []
    accession_by_judgment: dict[str, tuple[str, str]] = {}
    for row in workbook:
        qid = row["질의ID"]
        accession = accession_from_url(row["원본_GEO_링크"])
        if accession != key[(qid, row["후보코드"])]["canonical_id"]:
            raise ValueError(f"accession mismatch for {qid}/{row['후보코드']}")
        if accession in qrels[qid]:
            raise ValueError(f"duplicate judged pair {qid}/{accession}")
        grade = int(row["관련성_0_3"])
        if grade not in (0, 1, 2, 3):
            raise ValueError(f"invalid grade for {qid}/{accession}")
        qrels[qid][accession] = grade
        output: dict[str, object] = {"judgment_id": row["판정ID"], "qid": qid, "accession": accession}
        for requirement, judgement, criteria_column, public_column in REQUIREMENTS:
            if bool(row[requirement].strip()) != bool(criteria[qid][criteria_column].strip()):
                raise ValueError(f"{qid}: {requirement} differs from the public criteria sheet")
            if row[judgement] not in ("1", "0", "NA"):
                raise ValueError(f"unexpected {judgement}={row[judgement]!r} for {qid}/{accession}")
            output[public_column] = row[judgement]
        if bool(row["제외조건"].strip()) != bool(criteria[qid]["must_not_contain_or_condition"].strip()):
            raise ValueError(f"{qid}: exclusion condition differs from the public criteria sheet")
        if row["제외조건_위반_yes_no_NA"] not in ("yes", "no", "NA"):
            raise ValueError(f"unexpected exclusion value for {qid}/{accession}")
        if row["근거부족_yes_no"] not in ("yes", "no"):
            raise ValueError(f"unexpected insufficient-evidence value for {qid}/{accession}")
        output["exclusion_violated"] = row["제외조건_위반_yes_no_NA"]
        output["insufficient_evidence"] = row["근거부족_yes_no"]
        conditions.append(output)
        accession_by_judgment[row["판정ID"]] = (qid, accession)

    responses = load_responses(args.run)
    if len(responses) != 180:
        raise ValueError(f"expected 180 responses, found {len(responses)}")
    rankings: list[dict[str, object]] = []
    response_rows: list[dict[str, object]] = []
    for response in sorted(responses, key=lambda item: (item.system, item.qid)):
        if response.system not in SYSTEMS:
            raise ValueError(f"unexpected system {response.system}")
        for hit in response.hits:
            if hit.canonical_id not in qrels[response.qid]:
                raise ValueError(f"returned candidate without judgement: {response.qid}/{hit.canonical_id}")
            rankings.append({"system": response.system, "qid": response.qid,
                             "rank": hit.rank, "accession": hit.canonical_id})
        response_rows.append({
            "system": response.system,
            "qid": response.qid,
            "http_status": response.http_status,
            "requested_top_k": response.requested_top_k,
            "returned": len(response.hits),
            "wall_latency_ms": response.wall_latency_ms,
            "fetched_at_utc": response.fetched_at_utc,
            "raw_sha256": response.raw_sha256,
        })

    corrections: list[dict[str, object]] = []
    for row in read_csv(args.corrections):
        qid, accession = accession_by_judgment[row["판정ID"]]
        if (qid, accession) != (row["질의ID"], row["GEO"]):
            raise ValueError(f"correction {row['판정ID']} does not match its judged pair")
        corrections.append({
            "judgment_id": row["판정ID"], "qid": qid, "accession": accession,
            "field": CORRECTED_FIELDS[row["변경열"]],
            "received_value": row["수신값"], "corrected_value": row["수정값"],
            "review_date": row["검수일"],
        })

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "qrels.tsv").write_text(
        "".join(f"{qid}\t0\t{accession}\t{grade}\n"
                for qid in sorted(qrels) for accession, grade in sorted(qrels[qid].items())),
        encoding="utf-8",
    )
    write_csv(args.out / "condition_judgments.csv",
              ["judgment_id", "qid", "accession", *[item[3] for item in REQUIREMENTS],
               "exclusion_violated", "insufficient_evidence"],
              sorted(conditions, key=lambda item: (str(item["qid"]), str(item["accession"]))))
    write_csv(args.out / "rankings.csv", ["system", "qid", "rank", "accession"], rankings)
    write_csv(args.out / "responses.csv", list(response_rows[0]), response_rows)
    write_csv(args.out / "judgment_corrections.csv", list(corrections[0]),
              sorted(corrections, key=lambda item: (str(item["judgment_id"]), str(item["field"]))))
    print(json.dumps({"judged_pairs": len(conditions), "queries": len(qrels),
                      "responses": len(response_rows), "ranked_hits": len(rankings),
                      "corrections": len(corrections)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
