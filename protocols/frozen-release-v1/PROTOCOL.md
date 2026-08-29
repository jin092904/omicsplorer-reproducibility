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

### Local OCI archive inspection

Before connecting an application image to the frozen stores, save it as a
single-image OCI archive from an exact clean checkout of the public product
commit. A mutable local tag, engine image ID, engine-storage digest, archive
file hash, OCI manifest digest, and image-config digest identify different
objects and must not be reported interchangeably.

Use the read-only inspector to verify every config and layer descriptor in the
archive and bind the result to the exact product tree, Dockerfile, dependency
lock, pinned base-image digest, declared non-root user, and JSON entrypoint:

```bash
uv run --frozen --offline python scripts/inspect_oci_archive.py \
  --archive /private/evidence/omicsplorer-api.oci.tar \
  --source-dir /path/to/clean/product-checkout \
  --expected-product-commit '<40-character-public-commit>' \
  --dockerfile-relative infra/docker/Dockerfile.api \
  --lockfile-relative apps/api/uv.lock \
  --builder-name '<builder-name>' \
  --builder-version '<builder-version>' \
  --acknowledgement I_CONFIRM_THIS_IS_A_LOCAL_UNPUBLISHED_IMAGE_CANDIDATE \
  --output /private/evidence/container-image-evidence.json
```

The inspector refuses a dirty or different source checkout, an unsafe or
multi-image archive, missing or altered blobs, descriptor size disagreement,
an unpinned base image, a root default user, or a Dockerfile/archive user or
entrypoint mismatch. The generated report remains local operator evidence. It
does not prove that the image was published, that its declared user was
successfully exercised, that it used the frozen stores, or that an eligible
response trace was captured.

Exercise the image's declared user without a runtime user override. Record the
OCI runtime and version, main-process UID/GID, exact entrypoint, root-filesystem
mode, capability boundary, health result, network boundary, and cleanup result.
When an engine limitation requires a lower-level OCI runtime, state that fact;
do not relabel such a check as a Docker or Podman service run. A health probe
establishes startup only and is not retrieval, latency, or quality evidence.

Start from `declared-user-smoke-evidence.template.json`, retain it outside Git,
and cross-check it against the image report and exact OCI bundle configuration:

```bash
uv run --frozen --offline python scripts/validate_oci_smoke_evidence.py \
  --smoke-evidence /private/evidence/declared-user-smoke-evidence.json \
  --image-evidence /private/evidence/container-image-evidence.json \
  --bundle-config /private/evidence/oci-bundle/config.json \
  --output /private/evidence/declared-user-smoke-validation.json
```

This validator checks file hashes, image and entrypoint bindings, non-root
process IDs, read-only and capability settings, network and health boundaries,
cleanup fields, runtime labels, and claim limitations. It validates retained
records only: it does not replay the container or independently prove that a
reported health observation occurred.

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

### Cross-store snapshot audit

After all three stores have been restored, run the read-only cross-store audit
before exporting a corpus manifest or starting the application. Use the
read-only PostgreSQL role and the exact Qdrant and OpenSearch versions recorded
with the source snapshots. The tool accepts only loopback HTTP(S) endpoints,
requires the database-local snapshot marker, and does not write corpus data.

```bash
DATABASE_URL='<isolated-snapshot-read-only-url>' \
uv run --frozen --offline python scripts/audit_cross_store_snapshot.py \
  --snapshot-id '<database-local-snapshot-id>' \
  --qdrant-url http://127.0.0.1:<isolated-qdrant-port> \
  --qdrant-collection datasets_v2 \
  --qdrant-version '<source-qdrant-version>' \
  --opensearch-url http://127.0.0.1:<isolated-opensearch-port> \
  --opensearch-index datasets_v2 \
  --opensearch-version '<source-opensearch-version>' \
  --acknowledgement I_CONFIRM_THESE_ARE_ISOLATED_FROZEN_STORES \
  --output /private/evidence/cross-store-audit.json \
  --private-mismatches /private/evidence/cross-store-mismatches.private.json
```

For each store, the audit streams every record and checks its native document
or point ID against the payload `dataset_id`. It requires non-empty
`source_db`, `source_id`, and `dataset_id`, and reports duplicate IDs,
conflicting memberships, exact scanned counts, canonical sorted dataset-ID-set
SHA-256, and canonical sorted `(source_db, source_id, dataset_id)` membership
SHA-256. It also records the database marker and version, Qdrant version and
vector-configuration hash, and OpenSearch version, health, and mapping hash.

The aggregate report contains counts and hashes, not mismatch identifiers. The
separate private file contains the exact pairwise differences and must remain
private unless each identifier is reviewed for release. Exit status 0 means
only that all scanned records are structurally complete and the three ID and
membership sets are equal. A nonzero mismatch count leaves the frozen corpus
ineligible and is not a software failure to hide by rerunning.

Do not automatically delete database-only rows, insert missing search records,
or choose an intersection after seeing retrieval outcomes. Any derivative
common-store corpus requires a separately stated, non-outcome-based inclusion
rule, a hashed transformation plan, before/after identities, and another
zero-mismatch audit. Likewise, reindexing missing records creates new index and
embedding provenance that must be frozen and reported. Neither repair option
may be relabelled as the untouched source snapshot.

### Common-store derivative procedure

When a pre-evaluation audit finds rows present only in PostgreSQL, a common-store
derivative may be used only if Qdrant and OpenSearch are already identical in
both internal dataset IDs and accession membership. The fixed inclusion rule is:
retain a dataset only when that identity and membership were present in all
three frozen stores in the pre-evaluation audit. This is a store-consistency
rule, not a relevance, metadata-quality, or retrieval-outcome filter.

Never apply the rule to the restored source database. Clone that database under
a name ending in `_intersection`, assign a distinct database-local snapshot
marker, and keep ingestion, migration, worker, and application processes
stopped. Preserve the source database and all three original audit inputs.

Run planning with a database administrator because it must count all foreign-key
references, including rows protected by row-level security. Planning is a
repeatable-read, read-only transaction. It checks that the private PostgreSQL-only
ID lists are identical for Qdrant and OpenSearch, every reverse difference is
empty, membership mismatches are empty, and the calculated retained PostgreSQL
hashes equal both search stores. Version 1 refuses the transformation if any
excluded row is referenced by another table, even when the foreign key would
cascade or set the reference to null.

```bash
DATABASE_URL='<isolated-derivative-admin-url>' \
uv run --frozen --offline python scripts/prepare_intersection_derivative.py plan \
  --snapshot-id '<distinct-derivative-snapshot-id>' \
  --audit /private/evidence/cross-store-audit.json \
  --private-mismatches /private/evidence/cross-store-mismatches.private.json \
  --output /private/evidence/intersection-plan.json
```

Review and separately record the printed plan SHA-256. For application, use a
temporary role with `SELECT, DELETE` on `datasets` only. The apply transaction
rechecks the derivative name and marker, complete before-state hashes, private
file hash, exclusion count and exclusion-ID-set hash. It deletes only those
private IDs and rolls back unless the resulting count, internal-ID hash, and
accession-membership hash exactly equal the target recorded from both search
stores.

```bash
DATABASE_URL='<isolated-derivative-temporary-role-url>' \
uv run --frozen --offline python scripts/prepare_intersection_derivative.py apply \
  --plan /private/evidence/intersection-plan.json \
  --private-mismatches /private/evidence/cross-store-mismatches.private.json \
  --expected-plan-sha256 '<printed-plan-sha256>' \
  --acknowledgement I_CONFIRM_THIS_IS_A_DERIVATIVE_INTERSECTION_DATABASE \
  --output /private/evidence/intersection-report.json
```

Immediately revoke the temporary role's delete permission and disable login.
Then rerun the full read-only cross-store audit against the derivative database.
Only a zero-mismatch result is eligible for the derivative corpus manifest.
Keep source-snapshot and derivative identifiers distinct in all reports. A
successful transformation proves only declared cross-store identity consistency;
it does not show that the excluded rows were scientifically inferior, that the
metadata are accurate, or that retrieval is fast or effective.

### Corpus and store-manifest export

Export the accession TSV only after the derivative audit reports zero dataset-ID
and accession-membership mismatches. Use the database-scoped read-only role; do
not broaden it to read migration, tenant, user, log, or feedback tables. Obtain
the Alembic revision separately with an administrator and pass that observed
value as `--schema-revision`.

The Qdrant and OpenSearch snapshot identifiers must identify the immutable
source snapshot files or archives, not mutable collection or index names. The
exporter rechecks the live loopback-only store versions, exact counts, Qdrant
vector configuration, and OpenSearch mapping against the successful audit. It
then records the full Qdrant collection-configuration hash and OpenSearch
settings hash in the version-2 store manifest.

```bash
DATABASE_URL='<isolated-derivative-read-only-url>' \
uv run --frozen --offline python scripts/export_frozen_corpus_manifests.py \
  --snapshot-id '<derivative-snapshot-id>' \
  --schema-revision '<observed-alembic-revision>' \
  --audit /private/evidence/cross-store-audit-intersection.json \
  --qdrant-url http://127.0.0.1:<isolated-qdrant-port> \
  --qdrant-snapshot-id '<immutable-qdrant-snapshot-id>' \
  --opensearch-url http://127.0.0.1:<isolated-opensearch-port> \
  --opensearch-snapshot-id '<immutable-opensearch-snapshot-id>' \
  --accessions-output /private/evidence/corpus-accessions.tsv \
  --gzip-output /private/evidence/corpus-accessions.tsv.gz \
  --stores-output /private/evidence/stores-manifest.json \
  --acknowledgement I_CONFIRM_THE_AUDIT_IS_ZERO_MISMATCH_AND_PRE_EVALUATION
```

The TSV is ordered by source, accession, and internal dataset ID and contains
one row per retained internal ID. Every row carries the derivative snapshot ID,
historical extraction-version label, lineage ID, and build stage. The exporter
rejects blanks, tabs, newlines, duplicate accessions, count differences, or any
ID or accession-membership hash that differs from the audit. Its gzip output is
deterministic (`mtime=0`, no embedded filename).

Do not commit an accession TSV as an oversized Git blob. Keep generated files
outside Git until identifier and licensing review is complete. Publish the
reviewed deterministic gzip as an immutable release/archive asset, publish its
SHA-256 beside it, and retain the uncompressed TSV locally because the offline
release validator reads that canonical form. Artifact publication is a later
release step; successful local export alone is not a public archive or
submission-ready release.

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
