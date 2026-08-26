"""평가 메트릭.

- trec_metrics — pytrec_eval 기반 TREC 표준 (infNDCG, nDCG@k, MAP, Recall@k, MRR@k, P@k)
- facet_satisfaction — Facet-aware satisfaction (자체 정의, motivated by DeepGEOSearch 2025).
  top-k 결과의 disease / tissue / cell_type / modality / design_type 가 query 의
  expected_facets 와 일치하는 hit rate.

TTFR (Time-to-First-Relevant) 은 원전 출처 확인 불가로 *본 패키지에 미포함*.
"""
