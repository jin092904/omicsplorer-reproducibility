# Metadata-enrichment feasibility pilot v1

This directory contains identifier-free observations and aggregate tables derived from the
completed, write-disabled 491-record pilot. The run used one frozen product/evaluator/model
contract, processed one record at a time, and retained no source accession, source-input hash,
prediction, prompt, or model response text in the public observations.

## Retained files

- `metadata_pilot_observations_public.jsonl`: 491 sanitized observations, sorted independently
  of private execution order. `observation` is a new public row number and cannot be used as a
  selection rank.
- `metadata_pilot_by_stratum.csv`: target, completion, retry, and shadow-normalization counts by
  prespecified workload stratum.
- `metadata_pilot_timing_summary.csv`: descriptive timing distributions for the whole run and
  each stratum.
- `metadata_pilot_summary.json`: interpretation boundary, frozen commit/hash provenance, total
  run duration, write guard, and overall counts.

The public row whitelist contains only the stratum, final outcome, schema-policy status,
validation-retry indicator, HTTP attempt count, shadow-normalization counters, and three timing
fields. Timings are rounded to 0.1 ms before publication. P50 and p95 use linear interpolation
at index `(n - 1) * q` (Hyndman-Fan type 7) on those public values.

## Result and interpretation

All 491 selected records reached the runner's `success` outcome, and all were valid under the
frozen structural/semantic validation policy after at most one validation retry. Eight records
used that retry, producing 499 local-LLM HTTP attempts in total. The write guard passed: the
observed PostgreSQL selected-row state, Qdrant point count, and OpenSearch document count were
unchanged between the start and end of the run.

Here, “valid” means that the output passed the frozen software checks. It is not a blinded human
judgment that the extracted biological content is correct. The SHA-256 values for excluded
private files are audit anchors: an authorized reviewer with those files can verify identity,
but the hashes do not make the private contents publicly reproducible.

`shadow_would_change_n = 382` means that the product's shadow merge reported at least one
prospective difference for 382 records. `shadow_new_curies_total = 367` is the summed counter
returned by shadow normalization. Neither value establishes that a proposed field or ontology
identifier is correct, improved, or suitable for committing.

The complete process used serial execution (`parallelism = 1`) and took 6278.2 seconds in this
single frozen run. The per-record `elapsed_ms`, `llm_ms`, and `normalization_ms` values are
diagnostic observations under that condition. They are **not search latency**, concurrent
throughput, long-term production performance, or a service-level objective.

This pilot establishes execution feasibility and observed failure modes only. It does not
measure metadata accuracy or effectiveness. Those claims require retained source-payload
snapshots, blinded human annotation, and adjudication under a separate prespecified protocol.

## Reproduce the public summaries

From the repository root:

```bash
uv run python scripts/reproduce_metadata_pilot_artifacts.py
```

The command validates the public field whitelist and stratum sizes, recalculates the committed
CSV and JSON aggregates, verifies the public-observation SHA-256, and writes recomputed tables
under `build/metadata_enrichment_pilot_v1/`.
