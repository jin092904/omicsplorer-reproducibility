from genofinder_eval.external.enrichment_metrics import compute_metrics


def test_enrichment_metrics_measure_gain_and_regression() -> None:
    gold = [
        {
            "dataset_id": "d1",
            "gold": {
                "modality": ["scRNA-seq"],
                "organism_taxid": [9606],
                "disease_ids": ["MONDO:1", "MONDO:2"],
                "tissue_ids": ["UBERON:1"],
                "cell_type_ids": [],
            },
        }
    ]
    predictions = [
        {
            "dataset_id": "d1",
            "condition": "sol4_shadow",
            "before": {
                "modality": ["scRNA-seq"],
                "organism_taxid": [9606],
                "disease_ids": ["MONDO:1"],
                "tissue_ids": ["UBERON:1"],
                "cell_type_ids": [],
            },
            "prediction": {
                "modality": ["scRNA-seq"],
                "organism_taxid": [9606],
                "disease_ids": ["MONDO:2"],
                "tissue_ids": ["UBERON:1"],
                "cell_type_ids": [],
            },
            "schema_valid": True,
            "first_pass_valid": True,
            "retry_count": 0,
            "curie_validation": {"MONDO:2": True, "UBERON:1": True},
            "timing": {"wall_ms": 1000},
        }
    ]

    summary, detail = compute_metrics(gold, predictions)
    disease = next(row for row in summary if row["field"] == "disease_ids")
    overall = next(row for row in summary if row["field"] == "__overall__")
    disease_detail = next(row for row in detail if row["field"] == "disease_ids")

    assert disease["information_gain_rate"] == 1.0
    assert disease["correct_value_loss_rate"] == 1.0
    assert disease_detail["regression"] is True
    assert disease_detail["safe_merge_shrink"] is True
    assert overall["dataset_regression_rate"] == 1.0
    assert overall["safe_merge_shrink_rate"] == 1.0


def test_enrichment_metrics_safe_superset_has_no_shrink() -> None:
    gold = [{"dataset_id": "d1", "gold": {"disease_ids": ["MONDO:1", "MONDO:2"]}}]
    predictions = [
        {
            "dataset_id": "d1",
            "condition": "sol4_shadow",
            "before": {"disease_ids": ["MONDO:1"]},
            "prediction": {"disease_ids": ["MONDO:1", "MONDO:2"]},
            "schema_valid": True,
            "first_pass_valid": True,
        }
    ]
    summary, _ = compute_metrics(gold, predictions)
    disease = next(row for row in summary if row["field"] == "disease_ids")
    assert disease["f1_micro"] == 1.0
    assert disease["safe_merge_shrink_rate"] == 0.0
