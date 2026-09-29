#!/usr/bin/env python3
"""Re-send the 60 September OmicsPlorer requests and compare them with the collected responses.

For each query this script sends the collected request unchanged to the same local endpoint with
`X-Eval-Mode: 1`, and then the same request with `mode=bm25_only`. It writes a sanitized record:
request parameters, request time, the collected and re-run top-10 lists (GEO accession, rank,
score, score breakdown), the re-run trace, and the BM25-only result count. Titles, summaries, and
internal dataset identifiers are not written.

Usage (read-only against the service; the collected raw responses are private operator evidence):
    python scripts/rerun_complex_query_omicsplorer_requests.py \
        --raw <private collector run>/raw/omicsplorer_geo \
        --endpoint http://127.0.0.1:8000/api/v1/search --out rerun-sanitized-2026-09-27.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path
from typing import Any


def sanitized(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"rank": rank, "accession": item["source_id"], "score": item.get("score"),
             "score_breakdown": item.get("score_breakdown")}
            for rank, item in enumerate(results, start=1)]


def post(endpoint: str, body: dict[str, Any]) -> tuple[dict[str, Any], str, float]:
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Eval-Mode": "1"})
    sent = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    started = time.monotonic()
    payload = json.load(urllib.request.urlopen(request, timeout=900))
    return payload, sent, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/v1/search")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    lines: list[str] = []
    same_lists = same_scores = empty_bm25 = 0
    for path in sorted(args.raw.glob("*.json")):
        collected = json.loads(path.read_text())
        raw = collected["raw_response"]
        raw = json.loads(raw) if isinstance(raw, str) else raw
        params = dict(collected["request_parameters"])
        rerun, sent, seconds = post(args.endpoint, params)
        bm25, bm25_sent, _ = post(args.endpoint, {**params, "mode": "bm25_only"})
        before, after = sanitized(raw["results"]), sanitized(rerun["results"])
        lists_equal = [r["accession"] for r in before] == [r["accession"] for r in after]
        scores_equal = [r["score"] for r in before] == [r["score"] for r in after]
        same_lists += lists_equal
        same_scores += scores_equal
        empty_bm25 += not bm25["results"]
        lines.append(json.dumps({
            "qid": collected["qid"],
            "request_parameters": params,
            "collected_at_utc": collected["fetched_at_utc"],
            "collected_top10": before,
            "rerun_sent_at_utc": sent,
            "rerun_seconds": round(seconds, 3),
            "rerun_top10": after,
            "rerun_trace": rerun.get("evaluation_trace"),
            "top10_accessions_equal": lists_equal,
            "top10_scores_equal": scores_equal,
            "bm25_only_sent_at_utc": bm25_sent,
            "bm25_only_result_count": len(bm25["results"]),
            "bm25_only_trace": bm25.get("evaluation_trace"),
        }, ensure_ascii=False, sort_keys=True))
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(lines), "top10_accessions_equal": same_lists,
                      "top10_scores_equal": same_scores, "bm25_only_empty": empty_bm25}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
