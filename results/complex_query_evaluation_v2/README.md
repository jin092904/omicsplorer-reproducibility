# Complex-query relevance assessment v2: public results

v2 repeats the assessment of `../complex_query_evaluation_v1/` with the same 60 frozen English
queries and the same expected-criteria sheet
(`protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv`). It changes three things:

- NCBI GEO DataSets (arm B) and OmicsDI (arm C) receive keyword searches written for each query
  and frozen before collection (`keyword_queries.csv`), instead of the unchanged sentences;
- OmicsPlorer (arm A) runs on an index in which the GEO source filter keeps lexical candidates,
  so its lists come from lexical and dense retrieval followed by reranking (see "Retrieval path
  of the OmicsPlorer arm" in the v1 README);
- the v1 OmicsPlorer path is rerun on the same work server as arm A (arm E), so that arm A can be
  compared with v1 without a hardware difference.

Arms B and C were collected on 8 October 2026 with the v1 collector. Arms A and E were collected
the same day on a CPU work server restored from the frozen September services. A planned fourth
arm (an AI search service) could not be collected and is not part of the analysis.

## Judging

The top-10 lists of arms A, B, C, and E contained 988 query–candidate pairs not judged in v1.
They were mixed with 74 sealed v1 pairs and judged once, on 9 October 2026, by the v1 annotator
with the v1 scale and screens, while system identity, rank, and repeat status were hidden. The
judged workbook was compared cell by cell with an AI review of the same rows that had been frozen
before the annotator's grades arrived; each differing cell was checked against the GEO record and
changed only where the record contradicted the received value (166 cells in 102 rows, 27 of them
grades; `judgment_corrections.csv`). The final judgments were locked before the restricted pool
key was opened.

The analysis uses extended qrels: the 739 v1 pairs keep their v1 grade, and the 988 new pairs
add their v2 grade. The 74 repeated pairs give the retest agreement; scoring them with their v2
grade is a sensitivity analysis.

## Files

| File | Content |
|---|---|
| `qrels.tsv` | TREC qrels of the 988 new pairs: query ID, `0`, GEO Series accession, grade 0–3 |
| `condition_judgments.csv` | For each new pair: the eight condition judgements (`1`, `0`, `NA`), `exclusion_violated` (`yes`/`no`/`NA`), and `insufficient_evidence` (`yes`/`no`). Judgement IDs are those of the v2 workbook and are unrelated to the v1 IDs |
| `retest_pairs.csv` | The 74 repeated v1 pairs: v1 grade, v2 grade as received, and v2 grade after the GEO check |
| `judgment_corrections.csv` | The 166 cells changed against GEO before unblinding, with received and corrected values (repeated pairs included) |
| `rankings.csv` | Returned GEO Series accessions and ranks of arms A (`omicsplorer_fixed_index`), B (`ncbi_geo_keyword`), C (`omicsdi_geo_keyword`), and E (`omicsplorer_v1_path_rerun`) |
| `responses.csv` | One row per system and query: returned count, request time, and the SHA-256 of the private raw response (arms A–C) |
| `keyword_queries.csv` | The NCBI GEO DataSets and OmicsDI search strings, frozen before collection |
| `derived/` | Tables written by `scripts/analyze_complex_query_v2_results.py` |

The raw responses, the judgment workbook, the free-text notes, and the restricted pool key are
not published, for the reasons given in the v1 README. `scripts/export_complex_query_v2_public_results.py`
produced the input files from those private artifacts and is included so that the projection rule
can be inspected. When the projection was prepared, every derived table was compared cell by cell
with the private analysis and matched within 1e-12.

## Recompute

```bash
uv run python scripts/analyze_complex_query_v2_results.py --out build/complex_query_evaluation_v2
uv run python scripts/analyze_complex_query_v2_results.py --check
uv run python -m genofinder_eval.figures.figure_complex_query_relevance
```

The analysis reads the v1 files for the v1 pairs and rankings. Metric definitions, the bootstrap
(10,000 query-level replicates, seed 20260720), and the sign-flip test are those of v1. The two
prespecified comparisons are arm A against arms B and C on mean nDCG@10, with Holm adjustment.
Relevant means grade 2 or 3.

| Derived table | Content |
|---|---|
| `metrics_per_query.csv`, `metrics_summary.csv` | Ranking metrics, strict Success@10, response availability, and relevant and grade-3 candidates per query for arms A, B, C, E and the three v1 systems on the extended qrels (Figure 3A–B) |
| `pairwise_primary_ndcg.csv` | Arm A minus arms B and C, with sign-flip and Holm-adjusted p-values |
| `metrics_by_difficulty.csv` | Simple, medium, and complex strata |
| `relevant_overlap.csv` | Relevant query–candidate pairs by the set of arms A–C that returned them (Figure 3C) |
| `v1_systems_extended_pool.csv` | v1 metrics recomputed with the extended qrels |
| `retest_agreement.csv` | Agreement on the 74 repeated pairs, with received and with corrected v2 grades |
| `arm_a_vs_v1_path.csv` | Arm A, arm E, and the v1 OmicsPlorer run compared pairwise |
| `sensitivity_received_grades_*.csv` | Arms A–C scored with the v2 grades as received |
| `sensitivity_retest_v2_grades_summary.csv` | Arms A–C with the repeated pairs scored by their v2 grade |
