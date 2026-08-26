# Third-party data boundary

This repository does not redistribute the raw responses collected from NCBI GEO, OmicsDI,
or other external services. Those responses can contain third-party titles, abstracts,
author names, and submitter contact metadata. Public result files contain only derived
measurements or aggregate statistics needed to inspect the reported calculations.

The repository also excludes:

- the bioCADDIE corpus and qrels, because their source terms must be verified at retrieval time;
- ontology label snapshots derived from OLS-hosted ontologies;
- PDFs and other reference documents for which redistribution permission was not established;
- application databases, document payloads, and internal dataset identifiers;
- raw browser resource waterfalls and deployment hostnames.

Public database accession identifiers are facts and may appear in explicitly documented
query definitions. Users who retrieve third-party records must follow the terms and policies
of the originating repository.
