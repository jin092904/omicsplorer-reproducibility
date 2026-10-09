"""Check that the 120 keyword queries parse, without looking at their results.

For NCBI E-utilities only the fatal `errorlist` is kept; hit counts, IDs, and
warnings are discarded unread so that the queries cannot be tuned on results.
For OmicsDI only the HTTP status and whether the body is JSON are kept.
Output: 03-keyword-syntax-check.csv.
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
OMICSDI = "https://www.omicsdi.org/ws/dataset/search"


def _get(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "omicsplorer-benchmark-syntax-check"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> None:
    rows = list(csv.DictReader(open(HERE / "03-keyword-queries.csv")))
    email = os.environ.get("NCBI_EMAIL", "")
    out = []
    for row in rows:
        geo_params = {
            "db": "gds",
            "term": f"({row['ncbi_geo_term']}) AND gse[Entry Type]",
            "retmode": "json",
            "retmax": 0,
            "tool": "omicsplorer_benchmark",
            "email": email,
        }
        status, body = _get(f"{NCBI}?{urllib.parse.urlencode(geo_params)}")
        errors = json.loads(body, strict=False).get("esearchresult", {}).get("errorlist", {}) if status == 200 else {}
        geo_errors = {key: value for key, value in errors.items() if value}
        time.sleep(0.4)
        omicsdi_params = {"query": f"({row['omicsdi_query']}) AND repository:\"geo\"", "start": 0, "size": 1}
        o_status, o_body = _get(f"{OMICSDI}?{urllib.parse.urlencode(omicsdi_params)}")
        try:
            json.loads(o_body, strict=False)
            o_json = True
        except ValueError:
            o_json = False
        time.sleep(0.4)
        out.append(
            {
                "query_id": row["query_id"],
                "ncbi_http_status": status,
                "ncbi_errorlist": json.dumps(geo_errors, sort_keys=True) if geo_errors else "",
                "omicsdi_http_status": o_status,
                "omicsdi_json": o_json,
            }
        )
    with open(HERE / "03-keyword-syntax-check.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    bad = [r["query_id"] for r in out if r["ncbi_http_status"] != 200 or r["ncbi_errorlist"] or r["omicsdi_http_status"] != 200 or not r["omicsdi_json"]]
    print(f"checked {len(out)} queries; problems: {bad or 'none'}")


if __name__ == "__main__":
    main()
