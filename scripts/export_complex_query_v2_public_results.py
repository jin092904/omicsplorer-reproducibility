#!/usr/bin/env python3
"""Project the private v2 complex-query assessment into public result files.

Inputs are the locked private v2 artifacts: the final judgment workbook, the workbook as received
from the annotator, the restricted pool key, the log of cells changed against GEO, the raw keyword
collector runs of NCBI GEO DataSets and OmicsDI, and the sanitized ranking projections of the
OmicsPlorer runs. The output keeps only what the analysis needs and what may be redistributed:

- `qrels.tsv`: TREC qrels of the 988 pairs judged for the first time in v2;
- `condition_judgments.csv`: for those pairs, the 1/0/NA condition judgements and the exclusion
  and insufficient-evidence flags;
- `retest_pairs.csv`: the 74 sealed v1 pairs judged again, with the v1 grade and the received and
  final v2 grades;
- `judgment_corrections.csv`: the cells changed against GEO before system unblinding;
- `rankings.csv`: each v2 system's returned GEO Series accessions and ranks;
- `responses.csv`: per system and query, returned count, request time, and (where a raw response
  was kept) its SHA-256;
- `keyword_queries.csv`: the keyword search strings frozen before collection.

Titles, descriptions, other third-party text, free-text notes and reasons, candidate codes, and
internal OmicsPlorer identifiers are not written.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from genofinder_eval.external.pooling import load_responses
from genofinder_eval.external.ranking_metrics import load_qrels

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
    "질병": "disease_met",
    "조직": "tissue_met",
    "세포": "cell_type_met",
    "생물종": "organism_met",
    "분석법": "modality_met",
    "설계": "design_met",
    "비교군": "comparison_groups_met",
    "시점처치용량": "time_treatment_or_dose_met",
    "제외위반": "exclusion_violated",
    "근거부족": "insufficient_evidence",
}
ARMS = {"A": "omicsplorer_fixed_index", "B": "ncbi_geo_keyword", "C": "omicsdi_geo_keyword",
        "E": "omicsplorer_v1_path_rerun"}
REVIEW_DATE = "2026-10-09"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    parser.add_argument("--received-workbook", type=Path, required=True)
    parser.add_argument("--pool-key", type=Path, required=True)
    parser.add_argument("--changes", type=Path, required=True, help="cells changed against GEO")
    parser.add_argument("--keyword-runs", type=Path, nargs=2, required=True,
                        help="private collector run directories of arms B and C")
    parser.add_argument("--arm-a-rankings", type=Path, required=True)
    parser.add_argument("--arm-a-trace", type=Path, required=True)
    parser.add_argument("--v1-path-rerun", type=Path, required=True)
    parser.add_argument("--keyword-queries", type=Path, required=True)
    parser.add_argument("--v1-results", type=Path, default=Path("results/complex_query_evaluation_v1"))
    parser.add_argument("--criteria", type=Path,
                        default=Path("protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    workbook = read_csv(args.final_workbook)
    received = {row["판정ID"]: row for row in read_csv(args.received_workbook)}
    key = {row["판정ID"]: row for row in read_csv(args.pool_key)}
    criteria = {row["query_id"]: row for row in read_csv(args.criteria)}
    v1_qrels = load_qrels(args.v1_results / "qrels.tsv")
    if len(workbook) != 1062 or set(key) != {row["판정ID"] for row in workbook} or set(received) != set(key):
        raise ValueError("expected the same 1,062 judged rows in the workbooks and the pool key")

    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    conditions: list[dict[str, object]] = []
    retest: list[dict[str, object]] = []
    pair_by_judgment: dict[str, tuple[str, str]] = {}
    for row in workbook:
        qid = row["질의ID"]
        accession = accession_from_url(row["원본_GEO_링크"])
        entry = key[row["판정ID"]]
        if (entry["질의ID"], entry["canonical_id"], entry["후보코드"]) != (qid, accession, row["후보코드"]):
            raise ValueError(f"key mismatch for {row['판정ID']}")
        grade = int(row["관련성_0_3"])
        if grade not in (0, 1, 2, 3):
            raise ValueError(f"invalid grade for {qid}/{accession}")
        pair_by_judgment[row["판정ID"]] = (qid, accession)
        in_v1 = accession in v1_qrels.get(qid, {})
        if in_v1 != (entry["row_type"] == "retest_v1"):
            raise ValueError(f"retest status of {row['판정ID']} differs from the v1 qrels")
        if in_v1:
            retest.append({"judgment_id": row["판정ID"], "qid": qid, "accession": accession,
                           "v1_grade": v1_qrels[qid][accession],
                           "v2_received_grade": int(received[row["판정ID"]]["관련성_0_3"]),
                           "v2_final_grade": grade})
            continue
        if accession in qrels[qid]:
            raise ValueError(f"duplicate judged pair {qid}/{accession}")
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
        if row["제외조건_위반_yes_no_NA"] not in ("yes", "no", "NA") or row["근거부족_yes_no"] not in ("yes", "no"):
            raise ValueError(f"unexpected flag value for {qid}/{accession}")
        output["exclusion_violated"] = row["제외조건_위반_yes_no_NA"]
        output["insufficient_evidence"] = row["근거부족_yes_no"]
        conditions.append(output)
    if len(conditions) != 988 or len(retest) != 74:
        raise ValueError(f"expected 988 new and 74 retest pairs, found {len(conditions)} and {len(retest)}")

    corrections: list[dict[str, object]] = []
    for row in read_csv(args.changes):
        qid, accession = pair_by_judgment[row["판정ID"]]
        if qid != row["질의ID"]:
            raise ValueError(f"change {row['판정ID']} does not match its judged pair")
        corrections.append({"judgment_id": row["판정ID"], "qid": qid, "accession": accession,
                            "field": CORRECTED_FIELDS[row["칸"]], "received_value": row["받은값"],
                            "corrected_value": row["최종값"], "review_date": REVIEW_DATE})

    rankings: list[dict[str, object]] = []
    response_rows: list[dict[str, object]] = []
    for run in args.keyword_runs:
        for response in sorted(load_responses(run), key=lambda item: item.qid):
            system = f"{response.system}_keyword"
            if system not in (ARMS["B"], ARMS["C"]):
                raise ValueError(f"unexpected system {response.system}")
            for hit in response.hits:
                rankings.append({"system": system, "qid": response.qid, "rank": hit.rank,
                                 "accession": hit.canonical_id})
            response_rows.append({"system": system, "qid": response.qid, "returned": len(response.hits),
                                  "requested_at_utc": response.fetched_at_utc,
                                  "raw_sha256": response.raw_sha256})
    trace = {row["query_id"]: row for row in read_jsonl(args.arm_a_trace)}
    arm_a: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(args.arm_a_rankings):
        arm_a[row["query_id"]].append(row)
    for qid in sorted(arm_a):
        for row in sorted(arm_a[qid], key=lambda item: item["rank"]):
            rankings.append({"system": ARMS["A"], "qid": qid, "rank": row["rank"], "accession": row["gse"]})
        response_rows.append({"system": ARMS["A"], "qid": qid, "returned": len(arm_a[qid]),
                              "requested_at_utc": trace[qid]["sent_at_utc"], "raw_sha256": trace[qid]["raw_sha256"]})
    for row in sorted(read_jsonl(args.v1_path_rerun), key=lambda item: item["qid"]):
        for hit in row["rerun_top10"]:
            rankings.append({"system": ARMS["E"], "qid": row["qid"], "rank": hit["rank"],
                             "accession": hit["accession"]})
        response_rows.append({"system": ARMS["E"], "qid": row["qid"], "returned": len(row["rerun_top10"]),
                              "requested_at_utc": row["sent_at_utc"], "raw_sha256": ""})
    systems = {row["system"] for row in response_rows}
    if systems != set(ARMS.values()) or len(response_rows) != 4 * len(criteria):
        raise ValueError("expected one response per query for each of the four v2 systems")
    for row in rankings:
        qid, accession = str(row["qid"]), str(row["accession"])
        if accession not in qrels[qid] and accession not in v1_qrels.get(qid, {}):
            raise ValueError(f"returned candidate without judgement: {qid}/{accession}")

    queries = [{"qid": row["query_id"], "concept_groups": row["n_concept_groups"],
                "ncbi_geo_query": row["ncbi_geo_term"], "omicsdi_query": row["omicsdi_query"]}
               for row in read_csv(args.keyword_queries)]

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
    write_csv(args.out / "retest_pairs.csv", list(retest[0]),
              sorted(retest, key=lambda item: (str(item["qid"]), str(item["accession"]))))
    write_csv(args.out / "judgment_corrections.csv", list(corrections[0]),
              sorted(corrections, key=lambda item: (str(item["judgment_id"]), str(item["field"]))))
    write_csv(args.out / "rankings.csv", ["system", "qid", "rank", "accession"],
              sorted(rankings, key=lambda item: (str(item["system"]), str(item["qid"]), int(item["rank"]))))
    write_csv(args.out / "responses.csv", list(response_rows[0]),
              sorted(response_rows, key=lambda item: (str(item["system"]), str(item["qid"]))))
    write_csv(args.out / "keyword_queries.csv", list(queries[0]), queries)
    print(json.dumps({"new_pairs": len(conditions), "retest_pairs": len(retest),
                      "corrections": len(corrections), "responses": len(response_rows),
                      "ranked_hits": len(rankings)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
