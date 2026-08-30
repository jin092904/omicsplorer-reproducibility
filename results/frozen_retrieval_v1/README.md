# Frozen retrieval public projection v1

Status: projection `GO`; public release tag and DOI not yet issued.

This directory is the reviewed public projection of the private rootless-Podman frozen run
`gpb-application-note-v1`. It retains the evidence needed to inspect the reported structured
facet calculations while excluding third-party titles and snippets, internal dataset IDs,
operator paths, host details, credentials, databases, model weights, and container archives.

## Retained files

| File | Role |
|---|---|
| `per_query_responses_public.jsonl` | 392 sanitized responses with public accessions, ranks, scores, structured facet fields, effective-path traces, and private-row binding hashes |
| `per_query_metrics.jsonl` | 392 derived per-query metric rows |
| `aggregate_metrics.csv` | 280 aggregate rows recomputed from the public metric payloads |
| `failures.jsonl` | Empty frozen failure ledger |
| `gdc_project_review.json` | Review of 91 released public GDC project records from the unauthenticated official projects endpoint |
| `validation_report_public.json` | Projection-specific validation summary |
| `publication_manifest.json` | Counts, field boundary, private evidence hashes, and public artifact descriptors |

The snippet-derived exclusion diagnostic is retained as a private-text-derived metric and cannot
be independently recomputed from the stripped response projection. The reported main facet
metrics are recomputed from the retained structured fields.

## External release/DOI attachment

The row-level public accession manifest is deliberately not stored in normal Git history. The
future release and DOI archive must include this exact attachment:

- filename: `corpus_accessions_public.tsv`
- rows excluding header: 634,485
- bytes: 73,908,720
- SHA-256: `1f813acbc97e0a23048dff2ab7ad3ad9805f7cca10ffed674b181ca5de370858`
- fields: `source_db`, `accession`, `extraction_version`, `extraction_lineage_id`, `build_stage`

The attachment contains public accession facts and reviewed lineage labels. It does not contain
`internal_dataset_id` or `snapshot_id`, and it does not establish metadata accuracy, source
completeness, or that every file belonging to a GDC project is open access.

## Offline validation

Validate the Git-retained projection while acknowledging the not-yet-published attachment:

```bash
uv run python scripts/validate_public_frozen_projection.py \
  --projection-dir results/frozen_retrieval_v1 \
  --allow-missing-external-attachment
```

After downloading the release attachment, require full projection validation:

```bash
uv run python scripts/validate_public_frozen_projection.py \
  --projection-dir results/frozen_retrieval_v1 \
  --accession-asset /path/to/corpus_accessions_public.tsv
```

`GO` establishes the integrity of this public projection only. It is not independent relevance
validation, metadata-extraction accuracy, production latency, throughput, superiority, an SLA,
or overall journal-submission readiness.
