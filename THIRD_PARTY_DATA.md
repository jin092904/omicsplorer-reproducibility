# Third-party data boundary

This repository does not redistribute unfiltered raw responses collected from NCBI GEO,
SRA/ENA, GDC, OmicsDI, or other external services. Those responses can contain third-party
titles, abstracts, submitter text, author names, contact metadata, or internal application
identifiers. Public result files contain author-created inputs, derived measurements,
aggregate statistics, or a deliberately reduced result projection needed to inspect the
reported calculations.

The repository also excludes:

- the bioCADDIE corpus and qrels, because their source terms must be verified at retrieval time;
- ontology label snapshots derived from OLS-hosted ontologies;
- PDFs and other reference documents for which redistribution permission was not established;
- application databases, document payloads, and internal dataset identifiers;
- raw browser resource waterfalls and deployment hostnames.
- PostgreSQL, Qdrant, and OpenSearch snapshots, model caches and weights, the Ollama runtime
  archive, and the private application OCI archive.

Public database accession identifiers are facts and may appear in explicitly documented
query definitions. Users who retrieve third-party records must follow the terms and policies
of the originating repository.

For the frozen retrieval run, the complete private observations remain operator evidence.
The planned public projection removes titles, abstract snippets, internal dataset IDs,
operator paths, and host information while retaining public accessions, ranks, ranking
scores, structured facet IDs, effective-path traces, counts, and binding hashes. The exact
field and archive decision is recorded in
`protocols/frozen-release-v1/PUBLICATION_SCOPE.md`.

NCBI states that it places no restrictions on molecular-data use or distribution but cannot
transfer rights that may remain with submitters. GDC distinguishes open from controlled
access and prohibits reidentification. Accordingly, a public accession manifest is generated
without internal IDs, and GDC rows require an open/study-level check before publication.
