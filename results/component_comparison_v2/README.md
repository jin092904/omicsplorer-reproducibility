# Component comparison on the internal hard set (v2)

On 8–9 October 2026 the 49 English and Korean hard queries of `../frozen_retrieval_v1/` were run
in five conditions on a CPU work server restored from the stopped September services, against the
index whose `source_db` field is mapped as `keyword` (Supplementary Table S1b of the manuscript):

| Condition | Change from the baseline |
|---|---|
| `rrf_rerank` | Baseline: RRF over lexical and dense candidates, then reranking |
| `rrf_rerank_no_structured_fields` | The reranker input omits the structured tissue, assay, study design, and sample count (`RERANK_STRUCTURED_FIELDS_ENABLED=0`) |
| `rrf_rerank_no_design_boost` | The design-expression boost is off (`CARDINALITY_BOOST_ENABLED=0`) |
| `dense_only` | Dense retrieval only |
| `bm25_only` | Lexical retrieval only |

The product ran the `345abf7…` deployment with one added switch for the structured-field
condition, whose default reproduces the deployed behaviour (OmicsPlorer repository, release
`gpb-application-note-public-v3`). Requests used the settings of the frozen internal evaluation
(top 20 retrieved, 10 scored, automatic translation on, open-access filter). All 490 observations
succeeded, every response reported the requested mode, and every Korean observation recorded its
translation; Korean translations were computed once and reused across conditions.

| File | Content |
|---|---|
| `aggregate_metrics.csv` | Mean facet present@10, conjunctive@10, and exclusion clean@10 by condition, language, and diagnostic axis, computed with the metric code of `../frozen_retrieval_v1/` |
| `paired_vs_rrf_rerank.csv` | Per-condition differences from the baseline and the number of queries that went up, down, or stayed the same |

The baseline differs slightly from the frozen A100 release (English present@10 0.7772 versus
0.7823) because query embedding ran on CPU and reranking on a different CPU; BM25-only reproduced
the frozen English value. The per-query responses are not published because they contain
third-party titles and descriptions. These are internal facet metrics on 49 author-constructed
queries, not relevance judgments.
