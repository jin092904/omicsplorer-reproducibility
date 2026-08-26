from genofinder_eval.external.browser_latency import summarize_by_category, summarize_observations


def test_tail_summary_preserves_failures_and_quantiles() -> None:
    rows = [
        {"metric": "search_first_result_ms", "outcome": "success", "elapsed_ms": 1000},
        {"metric": "search_first_result_ms", "outcome": "success", "elapsed_ms": 3000},
        {"metric": "search_first_result_ms", "outcome": "timeout", "elapsed_ms": 120000},
    ]
    summary = summarize_observations(rows)
    search = next(row for row in summary if row["metric"] == "search_first_result_ms")
    assert search["n"] == 3
    assert search["n_success"] == 2
    assert search["n_timeout"] == 1
    assert search["success_rate"] == 2 / 3
    assert search["p50_ms"] == 2000
    assert search["p95_ms"] == 2900
    assert search["max_ms"] == 3000


def test_category_summary_does_not_mix_workloads() -> None:
    rows = [
        {
            "metric": "search_first_result_ms",
            "category": "simple",
            "outcome": "success",
            "elapsed_ms": 100,
        },
        {
            "metric": "search_first_result_ms",
            "category": "complex",
            "outcome": "success",
            "elapsed_ms": 900,
        },
    ]
    summary = summarize_by_category(rows)
    values = {
        row["category"]: row["p50_ms"]
        for row in summary
        if row["metric"] == "search_first_result_ms"
    }
    assert values == {"complex": 900.0, "simple": 100.0}
