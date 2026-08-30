# Frozen intersection-corpus identity audit: public aggregate v1

This directory contains the non-identifying aggregate used to generate the manuscript's
corpus-identity figure. It was derived from the private source-side audit of the isolated
29 August 2026 evaluation candidate.

The public JSON contains counts, source composition, store cardinalities, mismatch counts,
and interpretation boundaries. It intentionally excludes dataset IDs, source accessions,
row-level metadata, model outputs, database dumps, and search-store snapshots. The omitted
artifacts remain private while source-use and redistribution terms are reviewed.

The recorded rule retained a row only when its internal dataset identifier and
source-accession membership were present consistently in PostgreSQL, Qdrant, and OpenSearch.
It excluded 171 of 634,656 isolated rows and retained 634,485. The three retained source
counts sum to 634,485, and the recorded dataset-ID and source-accession-membership mismatch
counts are zero.

This aggregate supports the narrow statement that the retained derivative was internally
consistent under the recorded source-side rule. It does not independently reproduce the
private row-level audit and does not establish metadata accuracy, source completeness,
retrieval effectiveness, or successful restoration on another server.

Generate the figure from the repository root with:

```bash
uv run python -m genofinder_eval.figures.figure_corpus
```

By default, the command writes PNG and PDF files under
`build/corpus_identity_audit_v1/`, which is outside the retained public artifact set.

The JSON and this documentation are released under CC BY 4.0 as described in
`LICENSE-DATA.md`.
