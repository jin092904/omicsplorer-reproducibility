from __future__ import annotations

import pytest

from genofinder_eval.metadata_pilot_public import (
    PUBLIC_FIELDS,
    PublicPilotError,
    aggregate_results,
    by_stratum_rows,
    public_observations,
    timing_rows,
    validate_public_observations,
)


def _private_result(key: str, *, stratum: str, elapsed_ms: float, retry: bool) -> dict:
    return {
        "record_key_sha256": key,
        "input_sha256": f"input-{key}",
        "prediction_sha256": f"prediction-{key}",
        "stratum": stratum,
        "outcome": "success",
        "schema_valid_after_policy": True,
        "validation_retry_used": retry,
        "llm_http_attempts": 2 if retry else 1,
        "shadow_would_change": True,
        "shadow_new_curies": 2,
        "elapsed_ms": elapsed_ms,
        "llm_ms": elapsed_ms - 10,
        "normalization_ms": 10,
        "ollama_responses": [{"response_sha256": "private"}],
    }


def _strata() -> list[dict]:
    return [
        {"label": "sra", "target_n": 2},
        {"label": "gdc", "target_n": 1},
    ]


def test_public_observations_remove_identifiers_and_private_order() -> None:
    private = [
        _private_result("z", stratum="sra", elapsed_ms=30, retry=False),
        _private_result("a", stratum="gdc", elapsed_ms=20, retry=True),
        _private_result("m", stratum="sra", elapsed_ms=10, retry=False),
    ]
    rows = public_observations(private)
    assert all(set(row) == set(PUBLIC_FIELDS) for row in rows)
    assert [row["elapsed_ms"] for row in rows] != [30, 20, 10]
    assert all("record_key_sha256" not in row for row in rows)
    assert all("input_sha256" not in row for row in rows)
    assert all("prediction_sha256" not in row for row in rows)


def test_public_summaries_are_recomputed_from_whitelisted_rows() -> None:
    rows = public_observations(
        [
            _private_result("a", stratum="sra", elapsed_ms=10, retry=False),
            _private_result("b", stratum="sra", elapsed_ms=20, retry=True),
            _private_result("c", stratum="gdc", elapsed_ms=30, retry=False),
        ]
    )
    validate_public_observations(
        rows,
        expected_n=3,
        expected_by_stratum={"sra": 2, "gdc": 1},
    )
    aggregate = aggregate_results(rows)
    assert aggregate["processed_n"] == 3
    assert aggregate["validation_retry_n"] == 1
    assert aggregate["shadow_new_curies_total"] == 6
    stratum = by_stratum_rows(rows, _strata())[0]
    assert stratum["processed_n"] == 2
    assert stratum["success_n"] == 2
    assert stratum["non_success_n"] == 0
    overall_elapsed = timing_rows(rows, _strata())[0]
    assert overall_elapsed["metric"] == "elapsed_ms"
    assert overall_elapsed["p50_ms"] == 20.0


def test_public_validation_rejects_non_whitelisted_fields() -> None:
    rows = public_observations(
        [_private_result("a", stratum="gdc", elapsed_ms=20, retry=False)]
    )
    rows[0]["source_id"] = "must-not-leak"
    with pytest.raises(PublicPilotError, match="whitelist"):
        validate_public_observations(
            rows,
            expected_n=1,
            expected_by_stratum={"gdc": 1},
        )


def test_public_observations_reject_non_boolean_policy_status() -> None:
    private = _private_result("a", stratum="gdc", elapsed_ms=20, retry=False)
    private["schema_valid_after_policy"] = "true"
    with pytest.raises(PublicPilotError, match="must be boolean"):
        public_observations([private])
