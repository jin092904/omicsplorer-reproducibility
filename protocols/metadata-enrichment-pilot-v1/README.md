# Metadata-enrichment feasibility pilot v1

Status: **input-selection implementation; no model result is included**

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

## Stop conditions before model execution

Do not start the 491-record model run unless all of the following are true:

1. exactly 491 unique records are selected with every stratum at its target size;
2. the private manifest is mode `0600` and stored outside the public repository;
3. the exact prompt, schema, options, model digest, Ollama version, and product commit have
   SHA-256-bound manifest entries;
4. the runner has no commit flag and verifies a read-only database transaction;
5. a small smoke batch completes without a database or search-index count change.
