# Frozen release publication scope

Status reviewed: 30 August 2026

Applies to: private technical run `gpb-application-note-v1`

## Decision

The private rootless-Podman run passed the offline integrity validator, but the
private release directory is **not** itself the public archive. Publication uses
a derived, checksum-bound export that removes internal identifiers,
third-party narrative text, credentials, host details, and large executable or
database artifacts.

This boundary separates two questions:

1. **Technical integrity:** did the fixed application path execute all 392
   planned observations without an omitted call, zero-result response,
   configuration deviation, or component fallback?
2. **Redistribution:** which evidence may be copied to GitHub and a DOI archive
   under a clear license?

The private validator answered the first question with `RELEASE GO`. It does
not answer the second question and does not establish independent relevance,
metadata accuracy, or service performance.

## Publication matrix

| Artifact class | GitHub release | DOI archive | Decision and condition |
|---|---:|---:|---|
| Evaluator, validator, tests, lockfile | Yes | Yes | MIT-licensed code and exact environment lock |
| Author-created protocol, English/Korean queries, facet labels, schedules, prompts, and options | Yes | Yes | CC BY 4.0; internal regression inputs, not an independent benchmark |
| Canonical effective configuration and model/runtime identities | Yes | Yes | Publish names, revisions, manifest/weight/configuration digests, and acquisition instructions; remove absolute paths, hostnames, and credentials |
| Per-query metrics, aggregate table, empty failure ledger, and validation report | Yes | Yes | Publish with planned and eligible denominators and the validator scope statement |
| Sanitized per-query response evidence | Yes | Yes | Retain accession, rank, scores, structured facet IDs, request mode, effective trace, counts, and hashes; remove titles, snippets, submitter text, internal IDs, and unrelated source fields |
| Public accession manifest | Release attachment or Git LFS only | Yes | Generate a derived TSV without `internal_dataset_id`; verify every GDC row is open/study-level and retain repository acknowledgements |
| Full private response and observation files | No | No | Contain third-party titles or snippets and internal identifiers; retain as private operator evidence with hashes |
| Full accession manifest | No | No | Contains `internal_dataset_id`; publish only the derived public manifest and canonical hashes |
| PostgreSQL, Qdrant, OpenSearch snapshots and mismatch-detail files | No | No | Large operator artifacts containing full document payloads or internal identifiers |
| Model weights, Ollama archive, and model cache | No | No | Cite official acquisition locations and record exact digests; do not duplicate multi-gigabyte third-party binaries |
| Application OCI archive | No by default | No by default | Publish source, Dockerfile/lock hashes, OCI manifest/config digests, and non-root smoke evidence; archive bytes only after a separate dependency and redistribution review |
| Credentials, tokens, internal hostnames, absolute operator paths, logs | Never | Never | Prohibited publication content |

## Public response minimum

The public per-query export must retain enough information to inspect the main
facet results without copying repository narrative text:

- query ID, language, mode, deterministic ordinal, outcome, and request limits;
- author-created query and expected facets, or their bundled references and
  SHA-256 values;
- requested/effective mode, component states, fallback list, and canonical
  configuration SHA-256;
- public source database and accession, result rank, lexical/semantic/RRF/
  reranker scores, and structured disease, tissue, cell-type, modality, and
  organism identifiers used by the facet scorer;
- returned/scored counts and the per-query facet metrics;
- a binding hash of the corresponding private response.

The export must omit `title`, `abstract_snippet`, `internal_dataset_id`,
deployment URLs, credentials, and other fields not required to inspect the
reported facet calculations. The snippet-based exclusion diagnostic cannot be
independently recomputed from this stripped export and must be labelled as a
private-text-derived diagnostic if retained as an aggregate.

## Public accession manifest minimum

The public manifest should contain only:

- `source_db`;
- public repository `accession`;
- `extraction_version`;
- `extraction_lineage_id`;
- `build_stage`.

It must omit `internal_dataset_id` and operator `snapshot_id`. The archive must
state the corpus cut-off date, intersection rule, row count, source counts,
canonical public-accession hash, and the private three-store ID/membership
hashes. The latter hashes demonstrate consistency without exposing internal
identifiers; they do not demonstrate metadata accuracy or source completeness.

Before publication, all 91 GDC rows must be confirmed as open/study-level
records and the exporter must fail if a controlled-access marker is present.

## Source and model policy basis

- NCBI states that it places no restriction on use or distribution of its
  molecular databases, while also noting that it cannot transfer rights that
  may remain with individual submitters. This supports publication of accession
  facts but motivates excluding copied titles and descriptions:
  <https://www.ncbi.nlm.nih.gov/home/about/policies/>.
- GDC states that open-access data may be analysed and published, subject to a
  prohibition on reidentification; controlled-access data remain governed by
  dbGaP authorization and applicable data-use agreements:
  <https://gdc.cancer.gov/analyze-data/data-analysis-policies> and
  <https://gdc.cancer.gov/access-data/data-access-processes-and-tools>.
- The official Qwen3 Embedding and Reranker model cards identify the evaluated
  model repositories as Apache-2.0:
  <https://huggingface.co/Qwen/Qwen3-Embedding-8B> and
  <https://huggingface.co/Qwen/Qwen3-Reranker-0.6B>.
- The official Gemma 4 model card identifies Gemma 4 as Apache-2.0:
  <https://ai.google.dev/gemma/docs/core/model_card_4>.

These pages were reviewed on 30 August 2026. This document records a cautious
project publication boundary; it is not legal advice. Repository and model
terms must be rechecked immediately before DOI publication.

## Release gates created by this decision

The public release remains blocked until all of the following are true:

1. a deterministic public exporter and tests implement this field boundary;
2. public per-query evidence and the public accession manifest pass secret,
   internal-ID, path, hostname, controlled-access, count, and checksum checks;
3. every public aggregate and Figure 3 value is reproduced from the approved
   public evidence or explicitly bound to a private-only diagnostic;
4. the public bundle is validated from a clean clone;
5. the release tag is created on public `main`, not on the earlier local
   collection commit;
6. the exact tagged scope is archived and receives a persistent DOI.
