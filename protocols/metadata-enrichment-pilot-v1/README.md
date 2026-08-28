# Metadata-enrichment feasibility pilot v1

Status: **input-selection implementation; no model result is included**

Implementation note (2026-08-28): initial private, pre-eligible five-record smoke diagnostics exposed a
missing `jsonschema` dependency in the evaluation environment. Ollama returned HTTP 200 and
JSON objects, but downstream validation could not import its validator. That diagnostic run
set is excluded from pilot evidence. The evaluator now pins the same `jsonschema 4.26.0` version
observed in the product worker environment, and the frozen options record the validator
version explicitly.

This protocol deterministically selects 491 existing OmicsPlorer records across five
historical ingestion strata. The strata are workload/input-coverage labels only. They do not
establish the current row lineage, extraction accuracy, or superiority of one extractor.

The first pilot is limited to:

- whether the frozen prompt can be constructed from the retained source fields;
- wall time, model/schema failures, retries, and normalization failures;
- resource observations collected under a separately frozen runtime manifest.

It is not an accuracy or effectiveness evaluation. Accuracy claims require source-payload
snapshots, blinded human annotation, adjudication, and the conditions defined in
`protocols/external-services-v1/PROTOCOL.md` section 9.

## Selection

`selection-spec.json` is the prespecified selection frame. Within each stratum, records are
ordered by PostgreSQL `md5(source_db || ':' || source_id || ':' || seed)` and then by
`source_id`. MD5 is used only as a deterministic ordering function, not for integrity or
security. Published integrity fields use SHA-256.

The selector opens an explicit read-only transaction, verifies
`transaction_read_only = on`, contains no database mutation statement, and writes no source
payload. Its private JSONL manifest contains source accessions plus SHA-256 input hashes and
must remain outside Git. The public summary contains aggregate availability counts only.

```bash
DATABASE_URL='postgresql://...' uv run python scripts/select_metadata_enrichment_pilot.py \
  --private-manifest /restricted/path/metadata-pilot-v1.private.jsonl \
  --summary /restricted/path/metadata-pilot-v1-summary.json
```

The input hash covers a canonical JSON object containing the title, abstract, raw metadata,
reported sample count, and up to 30 usable sample titles. It binds the selected input but is
not the prompt hash. Prompt, schema, decoding options, model weights, serving engine, and
post-processing code must be frozen separately before any model call.

The freeze command extracts the prompt and schema from a clean product checkout, captures the
actual first-pass and validation-retry Ollama request bodies without sending a network request,
and binds them to the installed model digest and runtime:

```bash
uv run python scripts/freeze_metadata_pilot_contract.py \
  --product-root /path/to/clean/OmicsPlorer \
  --ollama-url http://127.0.0.1:11437 \
  --model-tag gemma4:31b \
  --gpu-index 5
```

The committed `frozen-contract/` directory can describe only the runtime from which it was
captured. Re-running the command after a model, prompt, product commit, or serving-engine
change creates a different contract and requires a documented protocol revision.

The committed contract can be checked without a database, Ollama, or product checkout:

```bash
uv run python scripts/validate_metadata_pilot_contract.py
```

## Stop conditions before model execution

Do not start the 491-record model run unless all of the following are true:

1. exactly 491 unique records are selected with every stratum at its target size;
2. the private manifest is mode `0600` and stored outside the public repository;
3. the exact prompt, schema, options, model digest, Ollama version, and product commit have
   SHA-256-bound manifest entries;
4. the runner has no commit flag and verifies a read-only database transaction;
5. a small smoke batch completes without a database or search-index count change.

## Write-disabled smoke execution

The smoke runner has no commit option. It selects the first record in each prespecified
stratum, verifies every source-input hash, and processes each record inside a PostgreSQL
read-only transaction. Sol4 inference and OLS4 exact-match normalization run, but the safe
merge is invoked only with `shadow=True`. PostgreSQL selected-row state, Qdrant point count,
and OpenSearch document count must be identical before and after the run.

```bash
DATABASE_URL='postgresql://...' uv run python scripts/run_metadata_pilot_smoke.py \
  --selection-manifest /restricted/path/selection.private.jsonl \
  --output /restricted/path/smoke-run.private.json \
  --product-root /path/to/clean/OmicsPlorer
```

Run the same command once with `--preflight-only` and a separate output path before allowing
the five model calls. Preflight validates all five input hashes and store observations without
contacting `/api/generate`.

This five-record smoke can establish only that the frozen pipeline executes under the stated
guards. Its success rate and timing are diagnostic and must not be reported as extraction
accuracy, general production throughput, or a service-level objective.

## Resumable batch execution

Longer rehearsals and the 491-record feasibility run use a separate resumable runner. In plain
terms, it saves after every record. Each saved line includes the previous line's SHA-256, so a
missing or edited intermediate result breaks the chain and blocks resume. `SIGINT`/`SIGTERM`
requests stop only after the current record has been saved. Five consecutive non-success
outcomes stop the run by default instead of spending hours on a systemic failure.

The runner must be launched from a clean, committed evaluator checkout. A 25-record rehearsal
is created with `--per-stratum 5`; the final selection uses `--all-records`. The choice, model
contract, product/evaluator commits, and source manifest hashes become immutable when the run
directory is created.

```bash
DATABASE_URL='postgresql://...' uv run python scripts/run_metadata_pilot_batch.py \
  --selection-manifest /restricted/path/selection.private.jsonl \
  --run-dir /restricted/path/rehearsal-25 \
  --product-root /path/to/clean/OmicsPlorer \
  --per-stratum 5

# Continue the same run after a safe pause:
DATABASE_URL='postgresql://...' uv run python scripts/run_metadata_pilot_batch.py \
  --selection-manifest /restricted/path/selection.private.jsonl \
  --run-dir /restricted/path/rehearsal-25 \
  --product-root /path/to/clean/OmicsPlorer \
  --per-stratum 5 --resume
```

The run directory and its files are private operational evidence (`0700` directory, `0600`
files) and are not committed to this repository.
