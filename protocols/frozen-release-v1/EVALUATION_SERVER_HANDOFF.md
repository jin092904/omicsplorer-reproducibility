# Evaluation-server handoff

## Purpose

Use a second host for the containerized frozen retrieval run when the evidence-
preparation host cannot run Docker or ordinary rootless Podman. GitHub access is
sufficient to clone public code, but it is not sufficient to recover private
store snapshots, an unpublished OCI archive, operator evidence, model files, or
secrets. Transfer those items separately over an authenticated encrypted
channel and verify every file before restore.

Passing the handoff validator establishes file-level consistency only. It is
not `RELEASE GO` and does not establish successful transfer, restore, service
startup, store identity, retrieval correctness, latency, quality, publication,
or submission readiness.

## Work split

### Complete on the preparation host

1. Freeze public product and evaluator candidate commits without creating final
   submission tags prematurely.
2. Retain one valid OCI archive and its image/startup evidence. Exclude invalid
   archive attempts explicitly.
3. Export a custom dump of the already audited common-store PostgreSQL
   derivative. Exclude owner, privilege, role/global, and database-creation
   commands. Read its catalog, record its hash and limitations, and retain the
   database-local snapshot marker separately for reapplication after restore.
4. Retain the exact Qdrant snapshot and OpenSearch cold archive used by the
   cross-store audit, plus the zero-mismatch aggregate and private mismatch
   record.
5. Retain the deterministic corpus gzip, store manifest, lineage declarations,
   and intersection plan/report. Review identifier and licensing boundaries
   before publishing any derivative.
6. Freeze prespecified eligible queries and schedules. Exclude every unresolved
   `TODO` or `REVIEW_REQUIRED` input rather than deciding after seeing results.
7. Prepare the handoff manifest with absolute `source_path` values, safe
   relative `transfer_path` values, exact byte sizes, SHA-256 values,
   classifications, exclusions, and known blockers.
8. Verify the manifest in source mode. Do not include `.env` files, API keys,
   database passwords, model-service tokens, participant-level material, user
   data, PostgreSQL globals, or operational service units.

### Complete on the container-capable evaluation host

1. Clone each public repository and detach at the manifest's full commit. A
   branch name or mutable `main` is insufficient.
2. Create a private destination directory, transfer only manifest-listed files
   through SSH/SFTP or an equivalently authenticated encrypted channel, and
   retain mode 600. Resume-capable tools may be used, but their success message
   is not an integrity check.
3. Run the handoff validator in destination mode before opening or restoring an
   artifact. Any missing file, changed byte count, changed SHA-256, duplicate or
   unsafe path, or broad private-file permission is a hard stop.
4. Create new least-privilege secrets on the target. Never reuse or transfer
   production credentials.
5. Use isolated empty storage. Load the exact OCI archive, restore the
   PostgreSQL derivative, reapply its database-local marker, restore Qdrant and
   OpenSearch using compatible versions, and do not start migrations, workers,
   scheduled ingestion, maintenance writes, or reindex paths.
6. Rerun the full cross-store identity and accession-membership audit. The
   expected count and prior hashes are comparison inputs, not permission to
   skip the audit.
7. Start the application image as its declared non-root user, bind only the
   isolated read-only stores, and repeat the startup check under the actual
   Docker/Podman runtime.
8. Export the canonical effective server configuration from that running
   release. Bind its digest and the image OCI manifest digest to every eligible
   response trace.
9. Run the prespecified warm-up and fail closed if the trace is absent, a mode
   falls back, a required component is unavailable, or store identity differs.
10. Execute every scheduled query exactly once per prespecified observation,
    retaining successes, zero results, timeouts, HTTP errors, and schema errors.
    Do not repeat poor or failed observations until they disappear.
11. Run the offline frozen-release validator. Only its `RELEASE GO` result makes
    the technical release eligible for downstream manuscript regeneration.

### Complete only after the frozen run

Regenerate retained retrieval tables and figures, update manuscript values and
limitations, recheck citations and journal instructions, obtain author and
institutional metadata, create reviewed public release tags, archive eligible
artifacts with persistent identifiers, and then run the final submission
validator. These steps do not require Docker themselves but depend on the
frozen run and therefore cannot be truthfully finalized in advance.

## Source validation

Copy `evaluation-server-handoff.template.json` to a private directory and fill
it with reviewed values. Then run:

```bash
uv run --frozen --offline python scripts/validate_evaluation_handoff.py \
  --manifest /private/handoff/HANDOFF-MANIFEST.private.json \
  --source \
  --output /private/handoff/source-validation.json
```

The source manifest contains absolute local paths and must remain private.
Transfer the manifest itself and only the files listed under `artifacts`.

## Destination validation

After transfer, place every file at its manifest `transfer_path` beneath one
private directory and run:

```bash
uv run --frozen --offline python scripts/validate_evaluation_handoff.py \
  --manifest /private/handoff/HANDOFF-MANIFEST.private.json \
  --destination-root /private/handoff/received \
  --output /private/handoff/destination-validation.json
```

Compare the source and destination reports' manifest hash, artifact count,
total bytes, transfer paths, and file hashes. Dynamic validation timestamps and
report-file hashes may differ. Stop before restore if any retained value differs.

## Capacity and architecture preflight

The manifest total is only the compressed transfer size. The destination also
needs capacity for extracted OpenSearch data, restored PostgreSQL, Qdrant,
container layers, logs, temporary restore files, and retained raw evaluation
outputs. Measure those requirements from the selected artifacts and target
engine; do not infer a safe disk, RAM, CPU, or accelerator minimum from the
compressed transfer total alone. Confirm the recorded OCI platform is supported
and record target hardware without hostnames, IP addresses, usernames, or
secret-bearing command output.
