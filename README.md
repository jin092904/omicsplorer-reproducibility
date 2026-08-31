# OmicsPlorer manuscript reproducibility materials

This repository contains the evaluation code, public query definitions, artifact contracts,
and selected derived results being prepared for an OmicsPlorer Application Note. The evolving
[OmicsPlorer application source](https://github.com/jin092904/OmicsPlorer) is published
separately under AGPL-3.0-or-later. Production credentials, the deployed configuration,
private user data, model weights, and the production corpus are not included in either
repository. The frozen evaluation release contains only the publishable configuration
evidence and derived artifacts defined by this repository's protocol.

## Current status

The public submission snapshot is tagged
[`gpb-application-note-public-v1`](https://github.com/jin092904/omicsplorer-reproducibility/releases/tag/gpb-application-note-public-v1).
A private rootless-Podman run completed on 30 August 2026 and its offline validation report
returned `RELEASE GO` for technical integrity. A deterministic exporter produced the sanitized
per-query projection and independently matched all 392 per-query metric rows and 280 aggregate
rows. A local review matched all 91 frozen GDC accessions to released records from the
unauthenticated official projects endpoint, and the resulting 634,485-row public accession
candidate passed the reviewed field boundary. The Git-sized projection is retained under
`results/frozen_retrieval_v1/`; the exact 73.9 MB accession TSV is attached to the GitHub
Release. A clean clone of the tag and an unauthenticated redownload of that attachment passed
the recorded tests, checksums, and full public-projection validation. This establishes public
projection integrity only. Persistent archive records remain private unsubmitted drafts pending
contributor review and are not yet public DOI records. Accordingly:

- unit-test success demonstrates evaluator behavior only;
- the private run retained 392/392 planned observations for 49 queries, two languages, and four
  modes, with zero missing observation, request failure, zero-result response, configuration
  deviation, or component fallback;
- the application-source trace contract and evaluation-client opt-in captured matching
  requested/effective modes, component states, and canonical configuration hashes;
- the run used a digest-bound OCI application image and isolated restored PostgreSQL, Qdrant,
  and OpenSearch stores under rootless Podman;
- the validator can preserve explicitly declared `historical_unresolved`
  lineage groups for an archived retrieval snapshot without inventing model
  provenance; an isolated restored PostgreSQL snapshot has been annotated, but
  those labels explicitly retain unresolved historical provenance;
- a read-only cross-store audit can stream PostgreSQL rows, Qdrant points, and
  OpenSearch documents to calculate canonical ID and accession-membership
  hashes while keeping exact mismatch identifiers in a separate private file;
- a separately named common-store PostgreSQL derivative passed a target
  zero-mismatch identity audit against the restored search stores; a
  non-identifying aggregate is public under `results/corpus_identity_audit_v1/`,
  but the private row-level audit remains operator evidence rather than a
  published frozen release;
- a read-only exporter can create the row-level accession TSV, deterministic
  gzip, and version-2 store manifest while binding them to that audit; the reviewed
  TSV is a GitHub Release attachment, while private store material and excluded
  generated files remain outside Git;
- the retained frozen hard-query results are internal facet-regression evidence, not independent
  relevance judgements; historical aggregate tables remain separately labelled;
- the browser run is a descriptive observation from one ingress, date, and measurement setup;
- none of these files establishes superiority over another system, a service-level objective,
  or metadata-extraction accuracy.

The public tag and GitHub Release are complete. The exact product and reproducibility scopes
have separate private Zenodo drafts because their license boundaries differ; those records must
not be cited as public DOI archives until contributor review is complete and both are published.
Publication decisions are defined in `protocols/frozen-release-v1/PUBLICATION_SCOPE.md`.

## Public artifact map

| Path | Contents | Interpretation |
|---|---|---|
| `src/`, `tests/` | Evaluator, metrics, clients, validators, and unit tests | MIT-licensed code; does not contain the product implementation |
| `data/hard_queries/` | Author-created paired Korean/English internal regression queries | Internal test set, not independent relevance ground truth |
| `protocols/frozen-release-v1/` | Fail-closed frozen-release contract and templates | Required structure; templates are not completed evidence |
| `protocols/external-services-v1/` | Prespecified pilot and latency query definitions | Descriptive pilot protocol, not a common relevance benchmark |
| `results/historical_internal/` | Historical aggregate tables | Raw per-query responses and complete effective configuration were not retained |
| `results/browser_2026-07-20/` | Sanitized observations and derived latency summaries | One date and ingress; no concurrency, regional, or SLA inference |
| `results/metadata_enrichment_pilot_v1/` | Identifier-free observations and aggregate feasibility tables | Write-disabled execution feasibility; no metadata-accuracy, search-latency, or superiority claim |
| `results/corpus_identity_audit_v1/` | Non-identifying counts used by the corpus figure | Source-side identifier consistency only; no row-level audit, metadata-accuracy, source-completeness, target-restore, or retrieval claim |
| `results/frozen_retrieval_v1/` | Approved Git-sized public projection of the technically valid private run | 392 sanitized responses and recomputed metrics; the checksum-bound accession TSV is a GitHub Release attachment and is intended for the matching archive record |

The exact exclusions and third-party boundary are documented in `THIRD_PARTY_DATA.md`.
Checksums for public inputs, protocols, and retained results are recorded in `ARTIFACTS.sha256`.

## Install and test

Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --frozen --extra dev
uv run pytest
uv run ruff check src tests scripts
uv run mypy src
```

These commands do not contact a live OmicsPlorer deployment. Tests use fixtures or mocked
HTTP responses.

## Reproduce the public summaries and figures

The public JSONL omits the deployment hostname, final URLs, internal dataset identifiers, and
resource-waterfall entries. The retained fields are sufficient to recompute the reported timing
distribution.

```bash
uv run python scripts/reproduce_browser_artifacts.py
uv run python scripts/reproduce_metadata_pilot_artifacts.py
uv run python -m genofinder_eval.figures.figure_corpus
```

The commands write recomputed files under `build/`, and check the retained public observations
against the committed summaries. The browser command also renders the tail-latency figure.
The corpus-identity command validates the public count relationships before writing its PNG
and PDF to `build/corpus_identity_audit_v1/`; it does not access the private row-level audit.

## Validate a frozen release candidate

The required artifact structure is defined in `protocols/frozen-release-v1/PROTOCOL.md`.

```bash
uv run python scripts/validate_frozen_release.py \
  --release-dir releases/gpb-application-note-v1
```

Any newly generated private or public candidate must independently pass its applicable checks.
The completed private run's `RELEASE GO` does not make an unreviewed public projection or the
journal submission ready.

To derive a public candidate from a validated private run:

```bash
uv run python scripts/export_public_frozen_release.py \
  --private-release /private/path/gpb-application-note-v1 \
  --output-dir /private/review/path/public-projection-v1
```

Without `--gdc-project-review`, the command deliberately omits the public accession TSV and
records one publication blocker. After every frozen GDC accession has been independently
confirmed through the unauthenticated official projects endpoint as a released public
study-level project record, supply a completed review based on
`protocols/frozen-release-v1/gdc-project-review.template.json`. This criterion concerns the
public project record and does not claim that every file in that project is open access. The
exporter rejects a missing, extra, duplicate, unreleased, or non-study-level record. Sanitized response evidence retains
public accessions and structured facet fields but excludes titles, snippets, internal dataset
identifiers, and unrelated source fields. The exclusion diagnostic remains explicitly labelled
as private-text-derived; the main facet metrics are recomputed from the public projection.

Validate the retained projection without downloading the external attachment:

```bash
uv run python scripts/validate_public_frozen_projection.py \
  --projection-dir results/frozen_retrieval_v1 \
  --allow-missing-external-attachment
```

For full projection validation, download the exact release attachment described in
`results/frozen_retrieval_v1/README.md` and pass it with `--accession-asset`. Neither validation
mode assesses overall publication or journal-submission readiness.

For a historical corpus whose original row-level extraction provenance cannot
be reconstructed, the isolated-snapshot preparation procedure is documented
under `Historical unresolved lineage policy` in the protocol. Planning is
read-only; applying a frozen plan requires a separately supplied plan hash,
an exact isolation acknowledgement, a matching database-local snapshot marker,
and a temporary role limited to the two lineage columns. This helper is not a
production migration and does not establish metadata accuracy.

After restoring all three stores, use the protocol's `Cross-store snapshot
audit` procedure before creating a corpus manifest. A nonzero mismatch count
is a frozen-corpus blocker; the tool does not silently delete or reindex data.
Exit status 0 establishes identity agreement only and is not `RELEASE GO`.

After a zero-mismatch derivative audit, the protocol's `Corpus and
store-manifest export` procedure creates the canonical accession TSV and a
deterministic compressed copy. Large generated corpus artifacts are kept out of
Git and may be published only after review as immutable release/archive assets
with their SHA-256 values. A local export does not by itself make the release
public or submission-ready.

The protocol's `Local OCI archive inspection` procedure separately checks every
referenced image blob and binds the archive to a clean public product commit,
Dockerfile, dependency lock, pinned base image, non-root user, and entrypoint.
Its output is local image-candidate evidence, not proof of registry publication,
frozen-store execution, response-trace eligibility, or performance.

The declared-user smoke-evidence template and validator then cross-check that
local image report against one retained OCI bundle and startup-only operator
record. This consistency check does not replay the container, convert a direct
OCI-runtime check into Docker/Podman evidence, or establish retrieval or latency.

When the preparation host cannot run an eligible containerized evaluation, use
the [evaluation-server handoff procedure](protocols/frozen-release-v1/EVALUATION_SERVER_HANDOFF.md)
and its manifest validator. GitHub carries public code only; private snapshots,
the unpublished OCI archive, operator evidence, model artifacts, and newly
created target secrets remain separate. Handoff validation checks bytes and
permissions, not restore or scientific results.

To verify or refresh the checksums after an intentional artifact update:

```bash
uv run python scripts/update_artifact_checksums.py --check
uv run python scripts/update_artifact_checksums.py --write
```

## Licenses and citation

Code is released under the MIT License. Original data definitions, protocols, result tables,
figures, and documentation are released under CC BY 4.0; see `LICENSE-DATA.md`. Third-party raw
records are excluded. Citation metadata are provided in `CITATION.cff`; the paper citation and
archival DOI will be added after the persistent archive is published; the paper citation will be
added when its bibliographic details are available.
