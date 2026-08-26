"""External dataset / 자체 ground truth loaders.

- biocaddie       — bioCADDIE 2016 (Cohen et al., 2017) corpus / queries / qrels.
                    *별도 임시 인덱스* (`biocaddie_2016_eval`) 로 격리 평가. production
                    corpus 와 join 하지 않음 — out-of-distribution generalization 평가.
- expert_curated_30 — 본 연구 자체 ground truth. Short 10 + Medium 10 + Complex 10,
                    각 EN/KO 1:1 paired. 편집자 직접 작성, pooled labeling.
- beir_compat     — BEIR-format jsonl (corpus / queries) + TSV qrel 표준 IO.
"""
