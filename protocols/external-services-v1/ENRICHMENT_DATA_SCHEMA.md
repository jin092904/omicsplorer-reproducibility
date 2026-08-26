# LLM enrichment benchmark data contract

## Gold JSONL

One immutable row per dataset:

```json
{
  "dataset_id": "uuid-or-stable-id",
  "source_db": "GEO",
  "source_id": "GSE123",
  "input_sha256": "64-hex",
  "gold": {
    "modality": ["scRNA-seq"],
    "organism_taxid": [9606],
    "disease_ids": ["MONDO:0005233"],
    "tissue_ids": ["UBERON:0002048"],
    "cell_type_ids": ["CL:0000625"]
  },
  "annotators": ["A1", "A2"],
  "adjudicated": true
}
```

The source payload itself is stored separately by content hash. Annotators may not see model output while creating gold labels.

## Prediction JSONL

One row per `(dataset_id, condition)`:

```json
{
  "dataset_id": "uuid-or-stable-id",
  "condition": "sol4_shadow",
  "before": {
    "modality": ["scRNA-seq"],
    "organism_taxid": [9606],
    "disease_ids": [],
    "tissue_ids": [],
    "cell_type_ids": []
  },
  "prediction": {
    "modality": ["scRNA-seq"],
    "organism_taxid": [9606],
    "disease_ids": ["MONDO:0005233"],
    "tissue_ids": ["UBERON:0002048"],
    "cell_type_ids": []
  },
  "schema_valid": true,
  "first_pass_valid": true,
  "retry_count": 0,
  "curie_validation": {
    "MONDO:0005233": true,
    "UBERON:0002048": true
  },
  "timing": {
    "wall_ms": 3240.2,
    "prompt_eval_count": 880,
    "eval_count": 146,
    "gpu_id": 2
  },
  "lineage": {
    "model": "gemma4:31b",
    "model_digest": "full-digest",
    "prompt_version": "sol4-...",
    "ollama_version": "0.23.3",
    "git_commit": "full-commit"
  }
}
```

Allowed conditions are preregistered in the run manifest. Missing rows are failures, not exclusions.

## Pipeline stage timing JSONL

```json
{
  "dataset_id": "uuid-or-stable-id",
  "source_id": "GSE123",
  "source_updated_at": "2026-07-20T01:02:03Z",
  "harvest_completed_at": "...",
  "structured_at": "...",
  "db_committed_at": "...",
  "qdrant_searchable_at": "...",
  "opensearch_searchable_at": "...",
  "run_id": "...",
  "outcome": "success"
}
```

If a stage fails or times out, preserve its failure and deadline; do not calculate freshness only from successful datasets.
