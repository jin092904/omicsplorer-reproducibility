# Complex-query relevance assessment v2: frozen protocol

These files were committed before the first v2 collection on 8 October 2026 and are listed in
`SHA256SUMS` (`sha256sum -c SHA256SUMS`). The protocol text (`01-protocol-v2-ko.md`) is in
Korean, as is the v1 protocol in `../complex-query-evaluation-v1/`.

| File | Content |
|---|---|
| `01-protocol-v2-ko.md` | Aims, arms, keyword rules, collection, judging, and the prespecified analysis |
| `02-keyword-concepts.csv` | Concept groups per query, written from the v1 query text and frozen conditions only |
| `03-keyword-queries.csv` | The NCBI GEO DataSets and OmicsDI search strings built from the concept groups |
| `03-keyword-syntax-check.csv` | Syntax check of every string (HTTP status and error list only; no result counts or IDs were read) |
| `build_keyword_queries.py`, `check_keyword_syntax.py` | The scripts that wrote the two CSV files |

The queries, conditions, judging scale, and metrics are those of v1. The keyword strings join
the standard synonyms of each required concept with OR and the concepts with AND, add required
organisms through each service's filter syntax, and leave out design adjectives and exclusion
conditions, which were checked in judging. Claude drafted the concept groups from the query text
and frozen conditions without looking at any search result; the author approved them.

## Amendments and deviations

Recorded in order; none was made after the restricted pool key was opened.

1. **Gemma 4 field check (8 October 2026, before the re-extraction ran).** Section 7 planned a
   200-record automatic check of organism, sample count, and assay. Gemma 4 produces only disease,
   tissue, cell type, and study design, so that check was dropped; the 40 Series of the v1 field
   check were re-extracted and judged on the Gemma 4 output, mixed with the stored values and with
   the source hidden. The frozen file above keeps the original wording.
2. **Collection site of arm A.** The A100 host became unavailable on 8 October 2026. Arm A was
   collected on a CPU work server restored from the stopped September services. Before collection,
   the 60 September OmicsPlorer requests were rerun there (mean overlap with the September top 10:
   9.2 of 10; "conditionally equivalent" under the prespecified rule), and this rerun (arm E) was
   kept as a same-server reference. Its 40 pairs not in the other pools were judged with the rest.
3. **Arm D.** The semantic-search service (Public Omics Explorer) did not respond on the
   collection day or the following day and was excluded under section 3.2. The Holm adjustment
   therefore covers two comparisons.
4. **Judging.** The annotator used ChatGPT (OpenAI, Sol) to collate the main fields of each GEO
   record for display and entered every grade. An independent review by Claude, frozen with
   checksums before the grades arrived, was compared cell by cell, and at the annotator's request
   Claude checked each differing cell against the GEO record and changed it only where the record
   contradicted it (166 cells; `../../results/complex_query_evaluation_v2/judgment_corrections.csv`).
   Results with the grades as received are reported as a sensitivity analysis.
5. **Repeat judgment.** As recorded in section 5, the 74 repeated pairs were judged about four
   weeks after the v1 systems were unblinded.

Results: `../../results/complex_query_evaluation_v2/`.
