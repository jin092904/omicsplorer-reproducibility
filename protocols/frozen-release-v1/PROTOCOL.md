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
   `extraction_lineage_id`. A row points to its final lineage; when that output
   preserves or merges fields from an earlier stage, `parent_lineage_ids` must
   connect the final lineage to every direct predecessor. The complete,
   acyclic graph must identify each local metadata extractor's checkpoint,
   revision, weight digest, quantization, serving engine, exact prompt,
   constrained schema, decoding/parser options, and deterministic
   post-processing revision. Stub or non-model lineages use explicit null model
   fields. Undeclared parents, cycles, unreachable declarations, mixed
   historical lineages, and their limitations must remain visible rather than
   being collapsed into one uniform extraction.
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

## Containerized execution boundary

The frozen corpus-and-retrieval run must use an isolated OCI application image
built from the final tagged product commit. A mutable image tag, a successful
build, or a synthetic Docker demo is not runtime identity evidence. Record the
following before collection:

- the published and archived OCI manifest digest used to start the application;
- the image-config digest, target platform, builder name and version, product
  commit, Dockerfile SHA-256, dependency-lock SHA-256, and pinned base-image
  digests;
- the image's declared non-root user and a successful smoke check using that
  declared user without a runtime user override;
- the same OCI manifest digest in `runtime.container_image_digest`, the
  canonical `effective-server-config.json`, and every eligible response trace.

Use the OCI manifest digest, not a mutable tag or an engine-local abbreviated
image ID, as `runtime.container_image_digest`. Preserve the exact image in a
public immutable registry or archive before submission. A local-only image is
preliminary operator evidence and cannot satisfy this requirement.

Restore the frozen PostgreSQL, Qdrant, and OpenSearch snapshots into separate
evaluation stores. Do not bind-mount live production data directories into the
evaluation stack. Do not start the reference Compose file's migration,
worker, beat, ingestion, maintenance-commit, or reindex paths during evidence
collection. Use a database role that cannot write, publish service ports only
on loopback or an isolated evaluation network, and verify the restored
cross-store counts and canonical dataset-ID hashes before sending the unscored
warm-up request. Containerization does not replace row-level extraction
lineage, model-weight digests, store snapshots, eligible effective-path traces,
or independent scientific evaluation.

System-service observations collected under earlier dated protocols retain
their original runtime descriptions. They must not be relabelled as
containerized evidence after the fact.

## Historical unresolved lineage policy

The production corpus predates complete row-level lineage capture. A retained
historical row must not be assigned an exact model, weight, prompt, schema,
option, parent graph, or post-processing revision by inference from an
`extraction_version` label. Full reprocessing under a frozen lineage remains
the stronger option and is required before claiming reproducible corpus
construction or field-level extraction accuracy.

For the Application Note's frozen retrieval snapshot only, an isolated restored
database copy may explicitly mark unreconstructable history without changing
the production database. Such a lineage declaration must satisfy all of the
following rules:

- `extractor_kind` is exactly `historical_unresolved`;
- every model, weight, prompt, schema, option, serving-engine, parent-lineage,
  and deterministic-post-processing field is explicit `null` or empty as
  required by the schema;
- every corresponding accession row uses `build_stage=historical_unresolved`;
- one unresolved lineage ID maps to exactly one retained
  `extraction_version`; different historical version labels cannot be
  collapsed into a single unresolved lineage;
- the lineage `limitations` and manifest `mixed_history_note` state that the
  snapshot retains historical output whose original runtime cannot be
  reconstructed;
- the snapshot-annotation transformation is logged and hashed, and row counts,
  accession membership, canonical dataset-ID hashes, and search-store
  membership are checked before and after annotation.

This marker is a machine-checkable limitation, not reconstructed provenance.
It permits reproduction of retrieval against the exact archived metadata
snapshot but does not establish how that metadata was originally generated,
whether its fields are accurate, or whether rerunning a historical extractor
would reproduce it. The manuscript must report those boundaries. A resolved
local-model or non-model lineage cannot use the
`historical_unresolved` build stage.

### Isolated snapshot annotation procedure

The repository includes a two-step helper for this limited transformation. It
must never be pointed at the production database. First restore a frozen
PostgreSQL backup under a new database name matching
`omicsplorer_frozen_<lowercase_name>`. Keep all application, migration,
ingestion, worker, and maintenance processes stopped. Give the restored
database a distinct local marker and reconnect so the setting is visible:

```sql
ALTER DATABASE omicsplorer_frozen_gpb_v1
  SET omicsplorer.evidence_snapshot_id = 'gpb-snapshot-v1';
```

Use two database roles. The planning and final-validation role is read-only.
The temporary annotation role receives `SELECT` on `datasets` and column-level
`UPDATE` only on `extraction_lineage_id` and `build_stage`; revoke that update
permission immediately after annotation. Do not grant it schema-changing,
insertion, deletion, migration, Qdrant, or OpenSearch permissions.

Create the plan first. This command runs in a repeatable-read, read-only
transaction. It refuses a database whose name or local marker does not match,
an empty or partially annotated table, missing extraction-version labels,
duplicate `(source_db, source_id)` accessions, or changing row identities.

```bash
DATABASE_URL='<isolated-snapshot-read-only-url>' \
uv run --frozen --offline python \
  scripts/prepare_historical_lineage_snapshot.py plan \
  --snapshot-id gpb-snapshot-v1 \
  --output /private/evidence/historical-lineage-plan.json
```

Review the plan's database name, total and per-version row counts, mutation
scope, and identity hashes. Preserve the printed SHA-256 outside the plan file.
Only then run the apply step with the temporary annotation role, the separately
copied plan hash, and the exact acknowledgement shown below:

```bash
DATABASE_URL='<isolated-snapshot-annotation-url>' \
uv run --frozen --offline python \
  scripts/prepare_historical_lineage_snapshot.py apply \
  --plan /private/evidence/historical-lineage-plan.json \
  --expected-plan-sha256 '<printed-plan-sha256>' \
  --acknowledgement I_CONFIRM_THIS_IS_AN_ISOLATED_FROZEN_SNAPSHOT \
  --output /private/evidence/historical-lineage-annotation-report.json
```

The apply step uses one serializable transaction. It rechecks the database
identity, marker, plan hash, row and version counts, accession membership, and
canonical dataset-ID hash before writing. It changes only the two declared
columns, assigns one deterministic unresolved lineage per retained
`extraction_version`, and then verifies the same identities and exact
assignments. A mismatch raises an error and rolls back the transaction. The
tool does not contact or modify Qdrant or OpenSearch; the later frozen-release
validator must still prove cross-store membership equality.

The plan and annotation report are operator evidence, not by themselves a
publishable release. They may expose an internal database name or path and
must be reviewed before producing a sanitized, hash-bound public derivative.
After revoking the temporary write permission, run all corpus exports,
cross-store checks, the OCI-hosted search service, and evidence collection with
read-only store roles. A successful annotation run proves only that the stated
labels were applied consistently to that isolated snapshot.

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

Exit status 0 means only that the configured stores, required dataset lineage
columns, non-empty row identities, row-level lineage values, and accession
uniqueness are readable and complete. Only aggregate problem counts are
reported; corpus row values are not printed. The report is an operator preflight, not a
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
