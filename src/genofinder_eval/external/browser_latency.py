"""Measure production browser click-to-render tail latency with Playwright.

This intentionally does not substitute API ``latency_ms`` for user-perceived time.
Each observation starts on the live landing page, submits through the real search
form, and waits for the server-rendered result status and DOM stabilization.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genofinder_eval.external.provenance import sha256_file
from genofinder_eval.external.runner import load_queries


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _percentile(values: list[float], quantile: float) -> float:
    """Linear interpolation between closest ranks (NumPy-compatible default)."""
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tail-first summaries; timeout/error observations are never silently dropped."""
    summary: list[dict[str, Any]] = []
    preferred = [
        "search_first_result_ms",
        "search_settled_ms",
        "ai_pick_cache_hit_ms",
        "ai_pick_cache_miss_ms",
        "ai_pick_forced_refresh_ms",
        "ai_pick_ms",
    ]
    observed_metrics = {str(row["metric"]) for row in rows if row.get("metric")}
    metrics = [metric for metric in preferred if metric in observed_metrics]
    metrics.extend(sorted(observed_metrics - set(metrics)))
    for metric in metrics:
        eligible = [row for row in rows if row.get("metric") == metric]
        successes = [float(row["elapsed_ms"]) for row in eligible if row.get("outcome") == "success"]
        summary.append(
            {
                "metric": metric,
                "n": len(eligible),
                "n_success": len(successes),
                "n_timeout": sum(row.get("outcome") == "timeout" for row in eligible),
                "n_error": sum(row.get("outcome") == "error" for row in eligible),
                "n_not_available": sum(
                    row.get("outcome") == "not_available" for row in eligible
                ),
                "success_rate": len(successes) / len(eligible) if eligible else math.nan,
                "p50_ms": _percentile(successes, 0.50),
                "p90_ms": _percentile(successes, 0.90),
                "p95_ms": _percentile(successes, 0.95),
                "p99_ms": _percentile(successes, 0.99),
                "max_ms": max(successes) if successes else math.nan,
                "mean_ms": statistics.fmean(successes) if successes else math.nan,
            }
        )
    return summary


def summarize_by_category(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the same tail summary independently to preregistered query categories."""
    categories = sorted({str(row["category"]) for row in rows if row.get("category")})
    output: list[dict[str, Any]] = []
    for category in categories:
        subset = [row for row in rows if row.get("category") == category]
        for summary in summarize_observations(subset):
            if summary["n"]:
                output.append({"category": category, **summary})
    return output


async def measure(
    *,
    base_url: str,
    query_file: Path,
    output_dir: Path,
    repeats: int,
    seed: int,
    timeout_ms: int,
    headless: bool,
    measure_ai_pick: bool,
    force_ai_pick_refresh: bool,
) -> list[dict[str, Any]]:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "Install the browser extra and Chromium: "
            "uv sync --extra browser && uv run playwright install chromium"
        ) from exc

    queries = load_queries(query_file)
    schedule = [(repeat, query) for repeat in range(repeats) for query in queries]
    random.Random(seed).shuffle(schedule)
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "browser_timings.jsonl"
    rows: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        browser_version = browser.version
        try:
            for sequence, (repeat, query) in enumerate(schedule, start=1):
                context = await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                base = {
                    "run_sequence": sequence,
                    "repeat": repeat,
                    "qid": query.qid,
                    "category": query.category,
                    "query_text": query.text,
                    "base_url": base_url.rstrip("/"),
                    "fetched_at_utc": _utc_now(),
                    "browser": "chromium",
                    "browser_version": browser_version,
                    "browser_cache_state": "cold-new-context",
                    "query_cache_state": "unknown",
                    "model_cache_state": "unknown",
                    "timeout_ms": timeout_ms,
                }
                try:
                    await page.goto(base_url.rstrip("/"), wait_until="domcontentloaded")
                    search_input = page.locator('main input[type="text"]').first
                    await search_input.wait_for(state="visible")
                    # ``domcontentloaded`` can fire before React has attached the
                    # controlled input's event handlers.  Pressing Enter in that
                    # interval performs the browser's native empty-form submit and
                    # reloads ``/``.  Start the click clock only after the control is
                    # demonstrably hydrated and user-operable.
                    await page.wait_for_function(
                        """() => {
                          const input = document.querySelector('main input[type="text"]');
                          return !!input && Object.keys(input).some(
                            (key) => key.startsWith('__reactProps$')
                          );
                        }"""
                    )
                    await search_input.fill(query.text)

                    await page.evaluate("performance.clearResourceTimings()")
                    started = time.perf_counter()
                    await search_input.press("Enter")
                    result_status = page.locator('main p[role="status"]').first
                    await result_status.wait_for(state="visible")
                    first_result_ms = (time.perf_counter() - started) * 1000
                    first_row = {
                        **base,
                        "metric": "search_first_result_ms",
                        "outcome": "success",
                        "elapsed_ms": first_result_ms,
                        "final_url": page.url,
                    }
                    rows.append(first_row)
                    _append_jsonl(jsonl_path, first_row)

                    # The user-visible loading state ends when the transition overlay is gone.
                    # Do not add an arbitrary network-idle wait: background/prefetch traffic can
                    # remain active after the page is already usable and previously inflated this
                    # metric by up to the diagnostic timeout.
                    pending_overlay = page.locator('div[role="status"][aria-label="Searching"]')
                    await pending_overlay.wait_for(state="hidden", timeout=min(timeout_ms, 5_000))
                    await page.wait_for_timeout(100)
                    settled_ms = (time.perf_counter() - started) * 1000
                    resource_waterfall = await page.evaluate(
                        """() => {
                          return performance.getEntriesByType('resource')
                            .filter((r) => r.startTime >= 0)
                            .map((r) => ({
                              name: r.name,
                              initiator_type: r.initiatorType,
                              start_ms: r.startTime,
                              duration_ms: r.duration,
                              response_start_ms: r.responseStart,
                              transfer_size: r.transferSize
                            }));
                        }"""
                    )
                    settled_row = {
                        **base,
                        "metric": "search_settled_ms",
                        "outcome": "success",
                        "elapsed_ms": settled_ms,
                        "final_url": page.url,
                        "resource_waterfall": resource_waterfall,
                    }
                    rows.append(settled_row)
                    _append_jsonl(jsonl_path, settled_row)

                    if measure_ai_pick:
                        # The production UI intentionally calls this optional feature
                        # "Assisted shortlist" / "보조 추천 목록", not "AI".  Anchor
                        # on its translated accessible button name so the measurement
                        # follows the same user-visible control in either locale.
                        button = page.get_by_role(
                            "button",
                            name=re.compile(r"^(Generate shortlist|보조 추천 보기)$", re.I),
                        ).first
                        if await button.count():
                            ai_started = time.perf_counter()
                            async with page.expect_response(
                                lambda response: "/api/ai-pick" in response.url,
                                timeout=timeout_ms,
                            ) as response_info:
                                await button.click()
                            ai_response = await response_info.value
                            try:
                                ai_payload = await ai_response.json()
                            except Exception:
                                ai_payload = {}
                            await page.wait_for_function(
                                """() => {
                                  const s = document.querySelector(
                                    'section[aria-label="Assisted shortlist"], ' +
                                    'section[aria-label="보조 추천 목록"]'
                                  );
                                  return !!s && s.querySelectorAll('.animate-pulse').length === 0;
                                }""",
                                timeout=timeout_ms,
                            )
                            ai_row = {
                                **base,
                                "metric": (
                                    "ai_pick_cache_hit_ms"
                                    if ai_payload.get("cached") is True
                                    else "ai_pick_cache_miss_ms"
                                ),
                                "outcome": "success" if ai_response.ok else "error",
                                "elapsed_ms": (time.perf_counter() - ai_started) * 1000,
                                "ai_pick_http_status": ai_response.status,
                                "ai_pick_cached": ai_payload.get("cached"),
                                "ai_pick_count": len(ai_payload.get("picks") or []),
                                "ai_pick_model_version": ai_payload.get("model_version"),
                                "ai_pick_state": "completed-or-error-visible",
                            }
                            rows.append(ai_row)
                            _append_jsonl(jsonl_path, ai_row)

                            # Optional operational stress path: the visible refresh
                            # control maps to ?nocache=1 and forces a real model call.
                            # Keep it separate from organic misses in all summaries.
                            if force_ai_pick_refresh and ai_response.ok and ai_payload.get("picks"):
                                refresh_button = page.get_by_role(
                                    "button",
                                    name=re.compile(r"^(Refresh|새로 만들기)$", re.I),
                                ).first
                                if await refresh_button.count():
                                    refresh_started = time.perf_counter()
                                    async with page.expect_response(
                                        lambda response: "/api/ai-pick" in response.url,
                                        timeout=timeout_ms,
                                    ) as refresh_response_info:
                                        await refresh_button.click()
                                    refresh_response = await refresh_response_info.value
                                    try:
                                        refresh_payload = await refresh_response.json()
                                    except Exception:
                                        refresh_payload = {}
                                    await page.wait_for_function(
                                        """() => {
                                          const s = document.querySelector(
                                            'section[aria-label="Assisted shortlist"], ' +
                                            'section[aria-label="보조 추천 목록"]'
                                          );
                                          return !!s && s.querySelectorAll('.animate-pulse').length === 0;
                                        }""",
                                        timeout=timeout_ms,
                                    )
                                    refresh_row = {
                                        **base,
                                        "metric": "ai_pick_forced_refresh_ms",
                                        "outcome": "success" if refresh_response.ok else "error",
                                        "elapsed_ms": (
                                            time.perf_counter() - refresh_started
                                        ) * 1000,
                                        "ai_pick_http_status": refresh_response.status,
                                        "ai_pick_cached": refresh_payload.get("cached"),
                                        "ai_pick_count": len(refresh_payload.get("picks") or []),
                                        "ai_pick_model_version": refresh_payload.get("model_version"),
                                        "ai_pick_state": "forced-refresh-completed-or-error-visible",
                                    }
                                    rows.append(refresh_row)
                                    _append_jsonl(jsonl_path, refresh_row)
                        else:
                            ai_row = {
                                **base,
                                "metric": "ai_pick_ms",
                                "outcome": "not_available",
                                "elapsed_ms": 0.0,
                                "ai_pick_state": "no-result-or-no-section",
                            }
                            rows.append(ai_row)
                            _append_jsonl(jsonl_path, ai_row)
                except PlaywrightTimeoutError as exc:
                    row = {
                        **base,
                        "metric": "search_first_result_ms",
                        "outcome": "timeout",
                        "elapsed_ms": float(timeout_ms),
                        "error": str(exc)[:500],
                        "final_url": page.url,
                    }
                    rows.append(row)
                    _append_jsonl(jsonl_path, row)
                except Exception as exc:  # pragma: no cover - browser/runtime dependent
                    row = {
                        **base,
                        "metric": "search_first_result_ms",
                        "outcome": "error",
                        "elapsed_ms": 0.0,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                        "final_url": page.url,
                    }
                    rows.append(row)
                    _append_jsonl(jsonl_path, row)
                finally:
                    await context.close()
        finally:
            await browser.close()

    _write_summary(output_dir / "browser_latency_summary.csv", summarize_observations(rows))
    _write_summary(
        output_dir / "browser_latency_by_category.csv",
        summarize_by_category(rows),
    )
    manifest = {
        "protocol_version": "external-services-v1.0.0",
        "kind": "production-browser-tail-latency",
        "base_url": base_url.rstrip("/"),
        "query_file": str(query_file.resolve()),
        "query_file_sha256": sha256_file(query_file),
        "repeats": repeats,
        "scheduled_searches": len(schedule),
        "seed": seed,
        "timeout_ms": timeout_ms,
        "headless": headless,
        "measure_ai_pick": measure_ai_pick,
        "force_ai_pick_refresh": force_ai_pick_refresh,
        "completed_at_utc": _utc_now(),
        "browser": "chromium",
        "browser_version": browser_version,
        "primary_clock": "controller monotonic click-to-visible",
    }
    (output_dir / "browser_run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--measure-ai-pick", action="store_true")
    parser.add_argument(
        "--force-ai-pick-refresh",
        action="store_true",
        help="After a successful shortlist, click its visible refresh control (?nocache=1).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeats < 1:
        raise ValueError("repeats must be >= 1")
    if args.force_ai_pick_refresh and not args.measure_ai_pick:
        raise ValueError("--force-ai-pick-refresh requires --measure-ai-pick")
    asyncio.run(
        measure(
            base_url=args.base_url,
            query_file=args.queries.resolve(),
            output_dir=args.output.resolve(),
            repeats=args.repeats,
            seed=args.seed,
            timeout_ms=args.timeout_ms,
            headless=not args.headed,
            measure_ai_pick=args.measure_ai_pick,
            force_ai_pick_refresh=args.force_ai_pick_refresh,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
