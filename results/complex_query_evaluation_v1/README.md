# Blinded complex-query relevance assessment: public results

This directory holds the public results of the assessment prespecified in
`protocols/complex-query-evaluation-v1/`. On 2 September 2026, 60 frozen English natural-language
queries were sent unchanged to OmicsPlorer, NCBI GEO DataSets, and OmicsDI, each restricted to GEO
Series. The top 10 results of the three systems were pooled into 739 query–candidate pairs. One
annotator judged the pairs on a 0–3 scale while system identity and rank were hidden.

The files are sufficient to recompute every number that the manuscript reports for this
assessment. When this projection was prepared, the recomputed per-query metrics, summary means,
bootstrap intervals, and sign-flip p-values were compared cell by cell with the frozen private
analysis and matched within 1e-12; that private analysis is not published.

## Files

| File | Content |
|---|---|
| `qrels.tsv` | TREC qrels: query ID, `0`, GEO Series accession, grade 0–3 (739 rows) |
| `condition_judgments.csv` | For each judged pair: judgement ID, condition judgements (`1`, `0`, `NA`) for the eight required-condition types, `exclusion_violated` (`yes`/`no`/`NA`), and `insufficient_evidence` (`yes`/`no`). Whether a query has a given condition comes from `protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv` |
| `rankings.csv` | Each system's returned GEO Series accessions and ranks (774 rows) |
| `responses.csv` | One row per system and query: HTTP status, requested and returned counts, collector wall time, fetch time, and the SHA-256 of the private raw response |
| `judgment_corrections.csv` | The 27 judgement fields in 22 rows corrected against GEO before system unblinding, with received and corrected values |
| `derived/` | Tables written by `scripts/analyze_complex_query_results.py` |
| `lexical_filter_check_2026-09-27/` | Post-hoc check of the OmicsPlorer retrieval path (see below) |

The raw service responses, the judgement workbook, and the restricted pool key are not
published. They contain third-party titles and descriptions, the annotator's free-text notes,
and internal OmicsPlorer identifiers (see `THIRD_PARTY_DATA.md`). `responses.csv` keeps the
SHA-256 of each raw response, so the private files can be matched to this projection later.

## Recompute

```bash
uv run python scripts/analyze_complex_query_results.py --out build/complex_query_evaluation_v1
uv run python scripts/analyze_complex_query_results.py --check
uv run python -m genofinder_eval.figures.figure_complex_query_relevance
```

The first command writes the tables. The second writes nothing: it recomputes the values and
compares them with the committed tables in `derived/` (tolerance 1e-12). The third draws
Figure 3 from the committed tables.

The analysis uses the metric functions in `src/genofinder_eval/external/ranking_metrics.py`. The
bootstrap uses 10,000 query-level replicates with seed 20260720. The two prespecified paired
comparisons use two-sided sign-flip tests with Holm adjustment. Relevant means grade 2 or 3.
Queries for which a system returned nothing stay in every primary metric.

| Derived table | Manuscript use |
|---|---|
| `metrics_summary.csv`, `pairwise_primary_ndcg.csv` | Primary nDCG@10 and secondary metrics (Table S6, Figure 3B) |
| `response_availability_*.csv` | Queries with at least one result (Figure 3A) |
| `condition_metrics_*.csv` | Strict all-condition Success@10 (Figure 3C) |
| `metrics_by_difficulty.csv`, `condition_metrics_by_difficulty.csv` | Difficulty strata (Table S7) |
| `latency_summary.csv` | Collector wall time; not browser latency |
| `posthoc_returned_candidate_yield.csv` | Post-hoc relevant share of returned candidates (Table S6a) |
| `posthoc_nonempty_sensitivity.csv` | Post-hoc subsets where a comparator returned results |
| `posthoc_all_systems_nonempty.csv` | Post-hoc subset of 14 queries where all three systems returned results (Table S7 text) |

`scripts/export_complex_query_public_results.py` produced the five input files from the frozen
private artifacts. It is included so that the projection rule can be inspected.

## Retrieval path of the OmicsPlorer arm

Every OmicsPlorer request asked for lexical and dense retrieval followed by reranking
(`mode=rrf_rerank`) and restricted the source to GEO (`source_db=["GEO"]`). On 27 September 2026 the
same 60 requests were sent again to the same production endpoint. The results were as follows:

- every top-10 list and score was identical to the collected one;
- the same requests in `bm25_only` mode returned no candidates;
- the production OpenSearch index mapped `source_db` as analyzed `text`, a form consistent with
  dynamic mapping, instead of the `keyword` type that the application defines.

The GEO filter therefore excluded every lexical candidate. The OmicsPlorer lists in this assessment
came from single-list RRF over the dense candidates, reranking, and the enabled shared
post-processing. They do not measure the fusion of lexical and dense retrieval.
`lexical_filter_check_2026-09-27/` contains the sanitized re-run and the recorded mapping and
counts. It includes the request parameters, request times, and both top-10 lists with accession,
rank, score, and score breakdown. `scripts/rerun_complex_query_omicsplorer_requests.py` is the
re-run code.

## Limits

- The query author, OmicsPlorer developer, and sole annotator are the same person. No second
  annotator or within-annotator repeat was used.
- Pool-based recall and nDCG are defined relative to the three systems' top-10 candidates.
- Comparator queries were not rewritten into service-specific syntax.
- The assessment covers GEO Series only.

These files are original evaluation materials licensed under CC BY 4.0 (`LICENSE-DATA.md`).
The accessions identify third-party records whose terms are set by NCBI.
