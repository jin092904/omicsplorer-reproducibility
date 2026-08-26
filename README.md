# OmicsPlorer manuscript reproducibility materials

This repository contains the evaluation code, public query definitions, artifact contracts,
and selected derived results being prepared for an OmicsPlorer Application Note. The
OmicsPlorer product source code and deployment configuration are proprietary and are not part
of this repository.

## Current status

This is a **pre-submission artifact, not a completed frozen release**. The offline validator and
release templates are implemented, but no release directory currently satisfies the required
corpus, model, configuration, request-trace, and row-level lineage checks. Accordingly:

- unit-test success demonstrates evaluator behavior only;
- the hard-query tables are historical internal regression aggregates;
- the browser run is a descriptive observation from one ingress, date, and measurement setup;
- none of these files establishes superiority over another system, a service-level objective,
  or metadata-extraction accuracy.

The submission artifact will receive a version tag and archival DOI only after the frozen run
passes the offline validator and the manuscript's retained values are regenerated or explicitly
versioned.

## Public artifact map

| Path | Contents | Interpretation |
|---|---|---|
| `src/`, `tests/` | Evaluator, metrics, clients, validators, and unit tests | MIT-licensed code; does not contain the product implementation |
| `data/hard_queries/` | Author-created paired Korean/English internal regression queries | Internal test set, not independent relevance ground truth |
| `protocols/frozen-release-v1/` | Fail-closed frozen-release contract and templates | Required structure; templates are not completed evidence |
| `protocols/external-services-v1/` | Prespecified pilot and latency query definitions | Descriptive pilot protocol, not a common relevance benchmark |
| `results/historical_internal/` | Historical aggregate tables | Raw per-query responses and complete effective configuration were not retained |
| `results/browser_2026-07-20/` | Sanitized observations and derived latency summaries | One date and ingress; no concurrency, regional, or SLA inference |

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

## Reproduce the public browser summaries and figure

The public JSONL omits the deployment hostname, final URLs, internal dataset identifiers, and
resource-waterfall entries. The retained fields are sufficient to recompute the reported timing
distribution.

```bash
uv run python scripts/reproduce_browser_artifacts.py
```

The command writes recomputed CSV files and the tail-latency figure under `build/browser_2026-07-20/`
and checks the retained metrics against the committed summaries.

## Validate a future frozen release

The required artifact structure is defined in `protocols/frozen-release-v1/PROTOCOL.md`.

```bash
uv run python scripts/validate_frozen_release.py \
  --release-dir releases/gpb-application-note-v1
```

Until the command reports `RELEASE GO`, the release must not be described as submission-ready.

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
