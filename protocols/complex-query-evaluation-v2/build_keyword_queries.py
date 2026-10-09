"""Build the service-syntax keyword queries for the v2 comparator arms.

Input: 02-keyword-concepts.csv (concept groups drafted from the frozen v1
conditions before any v2 collection). Output: 03-keyword-queries.csv with one
NCBI GEO DataSets term and one OmicsDI query per query ID. The collectors wrap
these strings exactly as in v1: `(<term>) AND gse[Entry Type]` for GEO and
`(<query>) AND repository:"geo"` for OmicsDI.

Groups are separated by " ; " and alternatives by "|". "@NAME" expands a shared
assay group. Organisms are joined by " & " when all of them are required.
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "complex-query-evaluation-v1"

SHARED_GROUPS = {
    "SC": ["single cell", "single-cell", "scRNA-seq", "scRNAseq"],
    "SN": ["single nucleus", "single-nucleus", "snRNA-seq", "snRNAseq"],
    "RNASEQ": ["RNA-seq", "RNA sequencing", "RNAseq"],
    "SPATIAL": ["spatial transcriptomics", "spatial transcriptomic", "spatially resolved", "Visium"],
}
TAXON_IDS = {
    "Homo sapiens": "9606",
    "Mus musculus": "10090",
    "Danio rerio": "7955",
    "Pseudomonas aeruginosa": "287",
    "Mycobacterium tuberculosis": "1773",
}


def _groups(field: str) -> list[list[str]]:
    groups = []
    for raw in field.split(" ; "):
        raw = raw.strip()
        if raw.startswith("@"):
            groups.append(SHARED_GROUPS[raw[1:]])
        else:
            groups.append([term.strip() for term in raw.split("|") if term.strip()])
    return groups


def _quote(term: str) -> str:
    # Quote anything that is not a single plain token so both services read it as a phrase.
    return f'"{term}"' if any(ch in term for ch in " -'.") else term


def geo_term(groups: list[list[str]], organisms: list[str]) -> str:
    parts = ["(" + " OR ".join(_quote(t) for t in group) + ")" for group in groups]
    parts += [f'"{name}"[Organism]' for name in organisms]
    return " AND ".join(parts)


def omicsdi_query(groups: list[list[str]], organisms: list[str]) -> str:
    parts = ["(" + " OR ".join(_quote(t) for t in group) + ")" for group in groups]
    parts += [f'TAXONOMY:"{TAXON_IDS[name]}"' for name in organisms]
    return " AND ".join(parts)


def main() -> None:
    frozen_ids = [row["query_id"] for row in csv.DictReader(open(V1 / "01-query-authoring-sheet.csv"))]
    rows = list(csv.DictReader(open(HERE / "02-keyword-concepts.csv")))
    if [row["query_id"] for row in rows] != frozen_ids:
        raise SystemExit("02-keyword-concepts.csv must list the 60 frozen query IDs in the v1 order")
    out = []
    for row in rows:
        groups = _groups(row["concept_groups"])
        organisms = [name.strip() for name in row["organisms"].split("&") if name.strip()]
        unknown = [name for name in organisms if name not in TAXON_IDS]
        if unknown:
            raise SystemExit(f"{row['query_id']}: no taxon ID for {unknown}")
        out.append(
            {
                "query_id": row["query_id"],
                "n_concept_groups": len(groups),
                "ncbi_geo_term": geo_term(groups, organisms),
                "omicsdi_query": omicsdi_query(groups, organisms),
            }
        )
    with open(HERE / "03-keyword-queries.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote {len(out)} queries to 03-keyword-queries.csv")


if __name__ == "__main__":
    main()
