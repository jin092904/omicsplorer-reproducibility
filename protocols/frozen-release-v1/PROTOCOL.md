# OmicsPlorer GPB Application Note frozen evaluation protocol

Status: template only; not a completed or preregistered run.

## Purpose and evidence boundary

This protocol freezes the internal hard-query facet regression run. Its labels
measure whether expected structured tags occur in retrieved results. They are
not independent document-relevance judgements and cannot establish precision,
recall, user utility, or superiority to another search service.

The technical release decision and the journal-submission decision are
separate. A technically complete run may contain timeouts or other request
failures if every prespecified request and failure remains in the denominator
and raw artifact. Poor results must not be discarded by repeating the run until
they improve. Missing or duplicated observations, hidden failures, dirty source
state, unverified configuration, or a retrieval-mode fallback are technical
NO-GO conditions.

## Freeze prerequisites

1. Start from one clean, tagged Git commit. Copy the exact evaluation lockfile
   into this directory and record its SHA-256.
2. Freeze the corpus cutoff and export an accession-level manifest. State the
   row identity and deduplication rule; do not call row count a unique-study
   count unless the export proves it.
3. Export a store manifest for PostgreSQL, Qdrant, and OpenSearch. It must state
   each immutable snapshot identifier, row/point/document count, schema or
   mapping hash, canonical internal-dataset-ID-set hash, and cross-store
   mismatch count. Hash the unique IDs as sorted UTF-8 lines with one trailing
   newline. Counts and hashes must agree with the accession TSV, and the
   mismatch count must be zero.
4. For every corpus row, record `extraction_version`, `build_stage`, and
   `extraction_lineage_id`. The lineage manifest must identify each local
   metadata extractor's checkpoint, revision, weight digest, quantization,
   serving engine, exact prompt, constrained schema, decoding/parser options,
   and deterministic post-processing revision. Stub or non-model lineages use
   explicit null model fields. Mixed historical lineages and their limitations
   must remain visible rather than being described as one uniform extraction.
5. Record the effective deployed image digest and immutable retrieval-model weight
   digests. Document and query embeddings must share the same checkpoint,
   revision, vector space, quantization, pooling, and truncation. Model-defined
   document/query role prefixes may differ, but both must be recorded. Equal
   dimensionality alone is not evidence of compatibility.
6. Record translation and query-understanding model, prompt, options, and cache
   policy when enabled. Bundle and hash both the prompt and decoding/options
   file; a digest without its source artifact is insufficient. Use explicit
   null only when the component is disabled.
7. Export `effective-server-config.json` from the deployed evaluation release.
   It must bind the effective candidate depths, RRF k, embedding and reranker
   model digests, reranker top-N, translation/cache state, query understanding,
   shortcut/boost state, and container image digest. Calculate
   `retrieval.effective_configuration_sha256` over its parsed JSON using UTF-8,
   sorted object keys, compact separators, no trailing newline, and no NaN.
   The validator recomputes that canonical digest and checks every field against
   the frozen config. Current repository descriptions conflict (including top
   15 versus top 20 and model defaults), so source-code inference is not
   accepted as deployment evidence.
8. The service response must expose an evaluation trace containing requested
   mode, effective mode, effective server-configuration SHA-256, component
   strict state values for lexical/dense/reranker/translation/query
   understanding, enabled/applied states for accession shortcut and cardinality
   boost, and fallback events. The public application source and this
   repository's evaluation client implement the additive trace contract and
   opt-in header. No frozen deployment response has yet been captured against a
   completed canonical server configuration, so the internal regression rerun
   remains NO-GO until those per-request traces pass the offline validator.

## Prespecified run

- Query set: exactly 49 `hard_queries`. The balanced set remains an LLM-assisted
  draft while its manifest contains `REVIEW_REQUIRED`; it is not an eligible
  input to this prespecified frozen internal regression rerun.
- Languages: English and Korean paired texts.
- Compared modes: BM25-based, dense-based, RRF, and RRF plus reranking. The
  internal API labels are `bm25_only`, `dense_only`, `rrf`, and `rrf_rerank`;
  “only” identifies the primary retrieval path and does not mean shared
  post-ranking is absent. This protocol retains the common accession shortcut
  and cardinality-boost configuration, requires their enabled/applied states in
  every trace, and rejects shortcut application in this non-accession query set.
- Retrieval depth: 20; scoring depth: 10.
- Primary internal regression endpoints: facet present macro and within-facet
  conjunctive macro. The latter does not require all different facet types to
  occur in one study.
- Exclusion clean@10 is diagnostic and defined only for applicable queries with
  at least one successfully returned document. A failed request or empty result
  never receives clean@10 = 1.0.
- Failure policy: report request failures and failure rate separately without
  imputing a facet value. The denominator and success-conditional metric n must
  both be shown.
- No inferential p-value is produced by the existing bootstrap helper. If a
  later independently judged comparison is made, use a paired interval and a
  prespecified paired randomization/permutation test with multiplicity control.

## Collection command

Before creating any snapshot or export, run the read-only deployment preflight
from the repository root with `DATABASE_URL`, `QDRANT_URL`, and
`OPENSEARCH_URL` supplied through the process environment. Credentials and
connection URLs are never written to its report.

```bash
uv run --frozen --offline python scripts/preflight_frozen_evidence.py \
  --qdrant-collection datasets_v2 \
  --opensearch-index datasets_v2 \
  --output evidence-preflight.json
```

Exit status 0 means only that the configured stores and required dataset
lineage columns are readable. The report is an operator preflight, not a
snapshot, corpus manifest, cross-store comparison, performance result, or
`RELEASE GO` artifact. Do not add it to a submission archive as a substitute
for the evidence below.

Fill and rename `freeze-config.template.json`. Likewise copy the effective
server configuration, translation prompt, and structuring lineage, prompt,
translation options, schema, and options templates to the non-`.template` names referenced by the
config, replace every placeholder with exported evidence, and calculate all
SHA-256 values. Then run from the repository root. The
validator hard-codes this protocol ID's query-set name, language and mode order,
49-query count, top/scoring depth, seed, timeout, warmup, metrics, and failure
policy; editing the config cannot silently weaken those conditions.

```bash
uv run --frozen --offline python -m genofinder_eval.runners.run_hard_queries \
  --set-name hard_queries \
  --data-dir data/hard_queries \
  --modes bm25_only dense_only rrf rrf_rerank \
  --top-k 20 --score-k 10 --seed 42 \
  --freeze-config protocols/frozen-release-v1/freeze-config.json \
  --release-dir releases/gpb-application-note-v1
```

Do not use `--allow-dirty` for a submission release. It exists only for local
rehearsal and the manifest will remain submission-ineligible.

## Offline validation command

After collection, run without a search client, `curl`, or network access:

```bash
uv run --frozen --offline python scripts/validate_frozen_release.py \
  --release-dir releases/gpb-application-note-v1
```

The validator recomputes call counts and the exact qid-language-mode product
from raw JSONL, checks input and artifact hashes, rejects duplicates and missing
observations, performs the canonical server-config/config/response-trace
three-way digest check, verifies the effective path and complete rerank scoring,
binds every row to the bundled query text, facet judgement, axis, request,
schedule, and frozen accession set, and recomputes every retained metric from
the response. Boolean/non-finite scores, non-finite aggregates, metric-bearing
failure rows, and translation trace/text disagreement are rejected. Request
failure remains separate from a successful zero result. `RELEASE GO` means only
that the evaluation collection
is internally complete. It does not mean the manuscript satisfies author,
licensing, DOI, independent-judgement, journal-format, or service-availability
requirements. By default the report is written beside, rather than inside, the
release directory so validation does not mutate the frozen evidence.

## Expected release files

```text
releases/
├── gpb-application-note-v1/
│   ├── run_manifest.json
│   ├── freeze_config.json
│   ├── inputs/
│   ├── observations/
│   ├── per_query_responses.jsonl
│   ├── per_query_metrics.jsonl
│   ├── failures.jsonl
│   └── aggregate_metrics.csv
└── gpb-application-note-v1-validation-report.json
```

Credentials, authorization headers, complete environment dumps, hostnames,
private addresses, and URL query strings must not enter the public archive.
