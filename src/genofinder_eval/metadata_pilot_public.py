"""Privacy-preserving public summaries for the metadata feasibility pilot."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

PUBLIC_FIELDS = (
    "observation",
    "stratum",
    "outcome",
    "schema_valid_after_policy",
    "validation_retry_used",
    "llm_http_attempts",
    "shadow_would_change",
    "shadow_new_curies",
    "elapsed_ms",
    "llm_ms",
    "normalization_ms",
)
TIMING_FIELDS = ("elapsed_ms", "llm_ms", "normalization_ms")


class PublicPilotError(ValueError):
    """Raised when private results cannot safely produce a public artifact."""


def _nonnegative_number(value: Any, *, field: str, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicPilotError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise PublicPilotError(f"{field} must be finite and non-negative")
    return number


def _nonnegative_integer(value: Any, *, field: str, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicPilotError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: Any, *, field: str, allow_none: bool = False) -> bool | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, bool):
        raise PublicPilotError(f"{field} must be boolean")
    return value


def public_observations(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Remove identifiers and model content, then break the private execution order."""
    sanitized: list[dict[str, Any]] = []
    for result in results:
        outcome = result.get("outcome")
        if not isinstance(outcome, str) or not outcome:
            raise PublicPilotError("outcome must be a non-empty string")
        stratum = result.get("stratum")
        if not isinstance(stratum, str) or not stratum:
            raise PublicPilotError("stratum must be a non-empty string")
        attempts = _nonnegative_integer(
            result.get("llm_http_attempts"), field="llm_http_attempts"
        )
        assert attempts is not None
        if attempts < 1:
            raise PublicPilotError("llm_http_attempts must be a positive integer")
        row = {
            "stratum": stratum,
            "outcome": outcome,
            "schema_valid_after_policy": _boolean(
                result.get("schema_valid_after_policy"), field="schema_valid_after_policy"
            ),
            "validation_retry_used": _boolean(
                result.get("validation_retry_used"), field="validation_retry_used"
            ),
            "llm_http_attempts": attempts,
            "shadow_would_change": _boolean(
                result.get("shadow_would_change"),
                field="shadow_would_change",
                allow_none=True,
            ),
            "shadow_new_curies": _nonnegative_integer(
                result.get("shadow_new_curies"),
                field="shadow_new_curies",
                allow_none=True,
            ),
            "elapsed_ms": round(
                _required_number(result, "elapsed_ms"),
                1,
            ),
            "llm_ms": round(_required_number(result, "llm_ms"), 1),
            "normalization_ms": _rounded_optional_number(result, "normalization_ms"),
        }
        sanitized.append(row)

    sanitized.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
    return [
        {"observation": index, **row}
        for index, row in enumerate(sanitized, start=1)
    ]


def _required_number(result: Mapping[str, Any], field: str) -> float:
    number = _nonnegative_number(result.get(field), field=field)
    assert number is not None
    return number


def _rounded_optional_number(result: Mapping[str, Any], field: str) -> float | None:
    number = _nonnegative_number(result.get(field), field=field, allow_none=True)
    return None if number is None else round(number, 1)


def validate_public_observations(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_n: int,
    expected_by_stratum: Mapping[str, int],
) -> None:
    if len(rows) != expected_n:
        raise PublicPilotError(f"expected {expected_n} public observations, found {len(rows)}")
    expected_fields = set(PUBLIC_FIELDS)
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        if set(row) != expected_fields:
            raise PublicPilotError("public observation fields differ from the whitelist")
        if row.get("observation") != index:
            raise PublicPilotError("public observation numbers are not contiguous")
        stratum = row.get("stratum")
        if not isinstance(stratum, str):
            raise PublicPilotError("public stratum must be a string")
        counts[stratum] += 1
        for field in TIMING_FIELDS:
            _nonnegative_number(row.get(field), field=field, allow_none=field == "normalization_ms")
        _boolean(row.get("schema_valid_after_policy"), field="schema_valid_after_policy")
        _boolean(row.get("validation_retry_used"), field="validation_retry_used")
        _boolean(row.get("shadow_would_change"), field="shadow_would_change", allow_none=True)
    if dict(counts) != dict(expected_by_stratum):
        raise PublicPilotError("public stratum counts differ from the selection plan")


def aggregate_results(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(str(row["outcome"]) for row in rows)
    return {
        "processed_n": len(rows),
        "outcome_counts": dict(sorted(outcomes.items())),
        "final_schema_valid_n": sum(
            row.get("schema_valid_after_policy") is True for row in rows
        ),
        "validation_retry_n": sum(row.get("validation_retry_used") is True for row in rows),
        "llm_http_attempts_total": sum(int(row["llm_http_attempts"]) for row in rows),
        "shadow_would_change_n": sum(row.get("shadow_would_change") is True for row in rows),
        "shadow_new_curies_total": sum(
            int(row["shadow_new_curies"])
            for row in rows
            if row.get("shadow_new_curies") is not None
        ),
    }


def by_stratum_rows(
    rows: Sequence[Mapping[str, Any]],
    strata: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for definition in strata:
        label = str(definition["label"])
        selected = [row for row in rows if row.get("stratum") == label]
        aggregate = aggregate_results(selected)
        outcome_counts = aggregate.pop("outcome_counts")
        success_n = int(outcome_counts.get("success", 0))
        output.append(
            {
                "stratum": label,
                "target_n": int(definition["target_n"]),
                "processed_n": aggregate.pop("processed_n"),
                "success_n": success_n,
                "non_success_n": len(selected) - success_n,
                **aggregate,
            }
        )
    return output


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise PublicPilotError("cannot summarize an empty timing field")
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def timing_rows(
    rows: Sequence[Mapping[str, Any]],
    strata: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scopes = [("all", rows), *(
        (str(definition["label"]), [row for row in rows if row.get("stratum") == definition["label"]])
        for definition in strata
    )]
    output: list[dict[str, Any]] = []
    for scope, scoped_rows in scopes:
        for metric in TIMING_FIELDS:
            values = [
                float(row[metric])
                for row in scoped_rows
                if isinstance(row.get(metric), (int, float))
                and not isinstance(row.get(metric), bool)
            ]
            if not values:
                continue
            output.append(
                {
                    "scope": scope,
                    "metric": metric,
                    "n": len(values),
                    "min_ms": round(min(values), 1),
                    "p50_ms": round(_percentile(values, 0.50), 1),
                    "p95_ms": round(_percentile(values, 0.95), 1),
                    "max_ms": round(max(values), 1),
                    "mean_ms": round(sum(values) / len(values), 1),
                }
            )
    return output
