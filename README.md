# OmicsPlorer manuscript reproducibility materials

This repository contains the evaluation code, public query definitions, artifact contracts,
and selected derived results being prepared for an OmicsPlorer Application Note. The evolving
[OmicsPlorer application source](https://github.com/jin092904/OmicsPlorer) is published
separately under AGPL-3.0-or-later. Production credentials, the deployed configuration,
private user data, model weights, and the production corpus are not included in either
repository; the frozen evaluation release will contain only the publishable configuration
evidence and derived artifacts defined by this repository's protocol.

## Current status

This is a **pre-submission artifact, not yet a public frozen release**. A private rootless-Podman
run completed on 30 August 2026 and its offline validation report returned `RELEASE GO` for
technical integrity. The public projection, remote release tag, clean-clone archive validation,
and persistent DOI remain incomplete. Accordingly:

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
  gzip, and version-2 store manifest while binding them to that audit; generated
  corpus files remain outside Git pending identifier, licensing, and release
  review;
- the retained frozen hard-query results are internal facet-regression evidence, not independent
  relevance judgements; historical aggregate tables remain separately labelled;
- the browser run is a descriptive observation from one ingress, date, and measurement setup;
- none of these files establishes superiority over another system, a service-level objective,
  or metadata-extraction accuracy.

The public submission artifact will receive a new version tag and archival DOI only after the
approved projection is generated, checked from a clean clone, and matched to the manuscript.
The earlier local collection tag is not the public submission tag. Publication decisions are
defined in `protocols/frozen-release-v1/PUBLICATION_SCOPE.md`.

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
| future `results/frozen_retrieval_v1/` | Approved public projection of the technically valid private run | Not present yet; must exclude third-party narrative text and internal identifiers |

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

## Validate a future frozen release

The required artifact structure is defined in `protocols/frozen-release-v1/PROTOCOL.md`.

```bash
uv run python scripts/validate_frozen_release.py \
  --release-dir releases/gpb-application-note-v1
```

Any newly generated private or public candidate must independently pass its applicable checks.
The completed private run's `RELEASE GO` does not make an unreviewed public projection or the
journal submission ready.

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
archival DOI will be added after acceptance of the frozen submission artifact.
