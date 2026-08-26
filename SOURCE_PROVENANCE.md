# Source provenance

The initial public package was assembled on 2026-08-26 from the private OmicsPlorer development
tree at internal source revision `0e7c5cc`. The private Git history was not imported because it
also contains proprietary product code, operational configuration, duplicated delivery bundles,
and third-party raw responses outside this repository's public license boundary.

The following transformations were applied during extraction:

- copied evaluator source and unit tests without application source code;
- retained only the author-created hard-query set and public protocol definitions;
- excluded incomplete balanced/expert query drafts and uncertain third-party corpora;
- excluded raw NCBI GEO, OmicsDI, and OmicsPlorer responses;
- derived a 240-row browser timing JSONL containing measurement fields only;
- removed temporary deployment URLs, resource waterfalls, internal dataset identifiers, local
  filesystem paths, and personal email addresses;
- made type-only evaluator corrections required by the public repository's strict mypy check.

The retained historical tables are not promoted to frozen-release evidence. Their limits are
documented alongside each result directory and in the root README.
