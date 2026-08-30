# GPB Application Note public release checklist

Proposed shared tag: `gpb-application-note-public-v1`

This checklist prepares immutable public software and evidence snapshots. Completing it establishes
release integrity; it does not establish retrieval superiority, independent relevance, metadata
accuracy, service performance, an SLA, or journal-submission readiness.

## Frozen release identities

| Scope | Repository | Version | Tag target |
|---|---|---:|---|
| Application source | `jin092904/OmicsPlorer` | `0.1.0` | final protected `main` after its release-metadata PR |
| Evaluation and public evidence | `jin092904/omicsplorer-reproducibility` | `0.1.0` | final protected `main` after this release-metadata PR |

Do not reuse the earlier local collection tag `gpb-application-note-v1`. It points to a historical
private-run collection commit and was never the public submission release.

## Verified before the release-metadata PR

- [x] Reproducibility public `main` commit `0b2f008bfea471a797fe7c51d878a8f3cc704f85`
  passed its remote CI.
- [x] An unauthenticated HTTPS clean clone of that commit passed lint, type checking, 166 tests,
  and 51 retained-artifact checksums.
- [x] The clean clone recomputed all 392 public observations and returned
  `GO_WITH_EXTERNAL_ATTACHMENT_REQUIRED` when the large accession attachment was absent.
- [x] The same clean clone returned projection `GO` when supplied with the exact external
  accession attachment.
- [x] Product public `main` commit `345abf725a8ac9265fb6f32e0b696f0c77eeed79` has successful
  `ci`, `security-gates`, and twelve-record synthetic `docker-demo` workflow runs.

## External reproducibility-release attachment

The reproducibility GitHub release and DOI archive must include:

- filename: `corpus_accessions_public.tsv`
- rows excluding header: 634,485
- bytes: 73,908,720
- SHA-256: `1f813acbc97e0a23048dff2ab7ad3ad9805f7cca10ffed674b181ca5de370858`

The attachment remains outside normal Git history. Its public fields and interpretation boundary are
defined in `results/frozen_retrieval_v1/README.md`.

## Required order after both release-metadata PRs are merged

1. Record the two final protected-`main` commit hashes and verify both worktrees are clean.
2. Create the same annotated tag `gpb-application-note-public-v1` at each repository's respective
   final commit. Do not move a published tag.
3. From fresh HTTPS clones of the tags, rerun the reproducibility checks and the product synthetic
   demo. The product demo is an application-path test, not a performance benchmark.
4. Publish two GitHub releases from those tags. Attach `corpus_accessions_public.tsv` to the
   reproducibility release only.
5. Download the attachment from the public release URL and require full projection `GO`; do not
   validate only the private local copy.
6. Archive both exact tagged scopes and the attachment in Zenodo or an equivalent repository.
7. Insert the issued persistent identifiers into the manuscript, data/code availability statement,
   `CITATION.cff`, cover letter, and submission checklist without moving the original tags. If a
   metadata-only follow-up release is necessary, issue a new tag rather than rewriting the first.

## Remaining non-release submission gates

- co-author approval of CRediT roles and manuscript;
- an institutional determination on whether ethics review or exemption documentation is required;
- acknowledgements and the public service URL/access conditions;
- final 4–6-page figure layout and upload-format review.
