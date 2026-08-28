"""Hard-query facet evaluation with an optional frozen-release output.

The historical runner wrote aggregate CSV files only. In frozen mode this
runner preserves every scheduled request, decoded response, failure, derived
metric, input digest, and lifecycle state. Request failures and successful
zero-result responses are separate outcomes; failures are never silently
converted into an exclusion score of 1.0.

No relevance claim follows from these facet tags alone. The hard and balanced
sets are internal regression sets, not independently judged qrels.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from genofinder_eval.adapters.expert_curated_30 import load_queries_paired
from genofinder_eval.client.geno_finder import GenoFinderClient
from genofinder_eval.client.search_modes import SearchMode
from genofinder_eval.external.provenance import git_binary, git_value, utc_now, write_json
from genofinder_eval.frozen_release import (
    FrozenEvalConfig,
    derive_hard_query_metrics,
    file_artifact,
    finalize_run_manifest,
    frozen_response_path_issues,
    load_frozen_config,
    new_run_manifest,
    update_run_counts,
)
from genofinder_eval.metrics.trec_metrics import aggregate_macro
from genofinder_eval.runners.warmup import warmup_reranker
from genofinder_eval.utils.logging import configure_logging, get_logger
from genofinder_eval.utils.seed import set_global_seed

logger = get_logger(__name__)

OBSERVATION_SCHEMA_VERSION = "omicsplorer-hard-query-observation-v1"
METRIC_SCHEMA_VERSION = "omicsplorer-hard-query-metric-v1"
LANGUAGES: tuple[Literal["en", "ko"], Literal["en", "ko"]] = ("en", "ko")
_RELEASE_BLOCKERS = ("<TODO>", "REVIEW_REQUIRED")


def _load_facet_judgments(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row["qid"])
            if qid in out:
                raise ValueError(f"duplicate qid in {path}:{line_number}: {qid}")
            out[qid] = row.get("expected", {})
    return out


def _load_axis_map(manifest_path: Path) -> dict[str, str]:
    """Load qid -> diagnostic axis, rejecting duplicate identifiers."""
    axis: dict[str, str] = {}
    if not manifest_path.exists():
        return axis
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            qid = str(row["qid"])
            if qid in axis:
                raise ValueError(f"duplicate qid in {manifest_path}:{line_number}: {qid}")
            axis[qid] = row.get("axis") or row.get("tier") or "unknown"
    return axis


def _jsonl_qids(path: Path) -> list[str]:
    qids: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("_id") or row.get("qid") or "")
            if not qid:
                raise ValueError(f"missing qid at {path}:{line_number}")
            if qid in seen:
                raise ValueError(f"duplicate qid in {path}:{line_number}: {qid}")
            seen.add(qid)
            qids.append(qid)
    if not qids:
        raise ValueError(f"no queries in {path}")
    return qids


def _validate_input_sets(data_dir: Path, *, frozen: bool) -> dict[str, Path]:
    files = {
        "queries_en": data_dir / "queries_en.jsonl",
        "queries_ko": data_dir / "queries_ko.jsonl",
        "facet_judgments": data_dir / "facet_judgments.jsonl",
        "query_manifest": data_dir / "manifest.csv",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise ValueError("missing evaluation inputs: " + ", ".join(missing))

    en_qids = _jsonl_qids(files["queries_en"])
    ko_qids = _jsonl_qids(files["queries_ko"])
    facets = _load_facet_judgments(files["facet_judgments"])
    axes = _load_axis_map(files["query_manifest"])
    expected = set(en_qids)
    if expected != set(ko_qids) or expected != set(facets) or expected != set(axes):
        raise ValueError("qid sets differ across EN, KO, facet judgments, and query manifest")
    if frozen:
        for label, path in files.items():
            text = path.read_text(encoding="utf-8")
            blockers = [token for token in _RELEASE_BLOCKERS if token in text]
            if blockers:
                raise ValueError(f"frozen input {label} contains unresolved marker(s): {blockers}")
    return files


def _resolve_modes(explicit: list[str] | None = None) -> list[SearchMode]:
    if explicit is None:
        raw = os.environ.get("EVAL_MODES", "").strip()
        values = (
            [value.strip() for value in raw.split(",") if value.strip()]
            if raw
            else [mode.value for mode in SearchMode]
        )
    else:
        values = [value.strip() for value in explicit if value.strip()]
    if not values:
        raise ValueError("at least one evaluation mode is required")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate evaluation modes: {values}")
    allowed = {mode.value for mode in SearchMode}
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise ValueError(f"unknown evaluation mode(s): {invalid}")
    return [SearchMode(value) for value in values]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: _json_safe(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    return value


def _redacted_error(exc: BaseException) -> dict[str, Any]:
    message = str(exc)
    for env_name in ("GENOFINDER_BEARER_TOKEN", "NCBI_API_KEY"):
        secret = os.environ.get(env_name, "")
        if secret:
            message = message.replace(secret, "<redacted>")
    message = re.sub(r"(https?://[^\s?]+)\?\S+", r"\1?<redacted>", message)
    return {
        "error_type": type(exc).__name__,
        "message": message[:500],
        "client_attempts": int(getattr(exc, "attempts", 1)),
        "http_status": getattr(exc, "status_code", None),
        "response_body_sha256": getattr(exc, "response_body_sha256", None),
    }


def _arm_invariant_issues(mode: str, results: list[dict[str, Any]]) -> list[str]:
    if not results:
        return []
    breakdowns = [row.get("score_breakdown") or {} for row in results]
    if mode == "bm25_only" and any(item.get("semantic") is not None for item in breakdowns):
        return ["bm25_only response contains semantic scores"]
    if mode == "dense_only" and any(item.get("lexical") is not None for item in breakdowns):
        return ["dense_only response contains lexical scores (possible BM25 fallback)"]
    if mode == "rrf" and any(item.get("rerank") is not None for item in breakdowns):
        return ["rrf response contains reranker scores"]
    if mode == "rrf_rerank" and not any(item.get("rerank") is not None for item in breakdowns):
        return ["rrf_rerank response has no reranker score (possible RRF fallback)"]
    return []


def _effective_trace_issues(
    *,
    mode: str,
    response: dict[str, Any],
    required: bool,
    expected_configuration_sha256: str | None,
) -> list[str]:
    issues = _arm_invariant_issues(mode, list(response.get("results") or []))
    trace = response.get("evaluation_trace")
    if trace is None:
        if required:
            issues.append("service response lacks required evaluation_trace")
        return issues
    if not isinstance(trace, dict):
        return [*issues, "evaluation_trace is not an object"]
    if trace.get("requested_mode") != mode:
        issues.append("evaluation_trace.requested_mode mismatch")
    if trace.get("effective_mode") != mode:
        issues.append("evaluation_trace.effective_mode mismatch")
    fallbacks = trace.get("fallbacks")
    if not isinstance(fallbacks, list):
        issues.append("evaluation_trace.fallbacks is missing")
    elif fallbacks:
        issues.append(f"evaluation arm fallback recorded: {fallbacks}")
    if (
        expected_configuration_sha256 is not None
        and trace.get("configuration_sha256") != expected_configuration_sha256
    ):
        issues.append("evaluation_trace.configuration_sha256 mismatch")
    components = trace.get("components")
    required_components = {
        "lexical",
        "dense",
        "reranker",
        "translation",
        "query_understanding",
    }
    if required and (
        not isinstance(components, dict) or not required_components.issubset(components)
    ):
        issues.append("evaluation_trace.components is incomplete")
    return issues


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(path)


def _metric_row(observation: dict[str, Any]) -> dict[str, Any]:
    metrics = observation.get("metrics") or {}
    facet = metrics.get("facet") or {}
    exclusion = metrics.get("exclusion") or {}
    return {
        "schema_version": METRIC_SCHEMA_VERSION,
        "ordinal": observation["ordinal"],
        "call_id": observation["call_id"],
        **observation["key"],
        "outcome": observation["outcome"],
        "metric_eligible": bool(metrics.get("eligible")),
        "facet_present_macro": facet.get("present_macro"),
        "facet_conjunctive_macro": facet.get("conjunctive_macro"),
        "exclusion_applicable": exclusion.get("applicable"),
        "exclusion_eligible": exclusion.get("eligible"),
        "exclusion_clean_at_k": exclusion.get("clean_at_k"),
        "returned_count": observation.get("returned_count", 0),
        "scored_count": observation.get("scored_count", 0),
    }


def _aggregate_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        key = observation["key"]
        grouped[(key["mode"], key["lang"])].append(observation)

    rows: list[dict[str, Any]] = []
    for (mode, lang), group in sorted(grouped.items()):
        axes = ["ALL", *sorted({item["key"]["axis"] for item in group})]
        for axis in axes:
            subset = (
                group if axis == "ALL" else [item for item in group if item["key"]["axis"] == axis]
            )
            values_by_metric: dict[str, dict[str, float]] = {
                "facet_present_macro": {},
                "facet_conjunctive_macro": {},
                "exclusion_clean_at_k": {},
            }
            for item in subset:
                metric = _metric_row(item)
                identity = str(item["key"]["qid"])
                for name in values_by_metric:
                    value = metric.get(name)
                    if isinstance(value, (int, float)):
                        values_by_metric[name][identity] = float(value)

            for metric_name, per_query in values_by_metric.items():
                if not per_query and metric_name == "exclusion_clean_at_k":
                    continue
                agg = aggregate_macro(per_query) if per_query else None
                rows.append(
                    {
                        "dataset": subset[0]["key"]["set_name"],
                        "mode": mode,
                        "lang": lang,
                        "axis": axis,
                        "metric": metric_name,
                        "mean": agg["mean"] if agg else "",
                        "median": agg["median"] if agg else "",
                        "std": agg["std"] if agg else "",
                        "n_queries": len(per_query),
                        "n_planned": len(subset),
                        "n_success": sum(item["outcome"] != "failure" for item in subset),
                        "n_failure": sum(item["outcome"] == "failure" for item in subset),
                        "n_zero_result": sum(item["outcome"] == "zero_result" for item in subset),
                    }
                )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("no aggregate rows were produced")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


async def run(
    set_name: str | None = None,
    data_dir: Path | None = None,
    results_dir: Path | None = None,
    top_k: int = 20,
    score_k: int = 10,
    *,
    modes: list[str] | None = None,
    seed: int | None = None,
    release_dir: Path | None = None,
    freeze_config_path: Path | None = None,
    repo: Path | None = None,
    allow_dirty: bool = False,
    client_factory: Callable[..., Any] | None = None,
) -> Path:
    """Run an internal facet regression set and return the aggregate CSV path."""
    if (release_dir is None) != (freeze_config_path is None):
        raise ValueError("release_dir and freeze_config_path must be supplied together")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if not 1 <= score_k <= top_k:
        raise ValueError("score_k must be between 1 and top_k")

    configure_logging()
    actual_seed = set_global_seed(seed)
    set_name = set_name or os.environ.get("EVAL_QUERY_SET", "hard_queries")
    data_dir = data_dir or Path(os.environ.get("EVAL_DATA_DIR", "data")) / set_name
    results_dir = results_dir or Path(os.environ.get("EVAL_RESULTS_DIR", "results"))
    repo = (repo or Path(__file__).resolve().parents[4]).resolve()
    selected_modes = _resolve_modes(modes)
    mode_values = [mode.value for mode in selected_modes]
    frozen = release_dir is not None
    input_files = _validate_input_sets(data_dir, frozen=frozen)

    config: FrozenEvalConfig | None = None
    timeout_s = float(os.environ.get("GENOFINDER_TIMEOUT", "180"))
    auto_translate = True
    access_preference: Literal["any", "open_only"] = "open_only"
    corpus = "production"
    trace_required = False
    expected_configuration_sha256: str | None = None
    failure_policy = "report_separately_no_imputation"
    warmup_policy = "legacy"
    manifest: dict[str, Any] | None = None
    if frozen:
        assert freeze_config_path is not None and release_dir is not None
        release_dir = release_dir.resolve()
        freeze_config_path = freeze_config_path.resolve()
        if release_dir.exists() and any(release_dir.iterdir()):
            raise ValueError(f"release directory is not empty: {release_dir}")
        config = load_frozen_config(
            freeze_config_path,
            set_name=set_name,
            languages=list(LANGUAGES),
            modes=mode_values,
            top_k=top_k,
            score_k=score_k,
            seed=actual_seed,
        )
        if not allow_dirty:
            if git_binary(repo, "status", "--porcelain=v1", "--untracked-files=all"):
                raise ValueError(
                    "frozen collection requires a clean Git worktree; "
                    "use --allow-dirty only for rehearsal"
                )
            tags = (git_value(repo, "tag", "--points-at", "HEAD") or "").splitlines()
            if config.release_id not in tags:
                raise ValueError(
                    f"frozen collection requires Git tag {config.release_id!r} at HEAD; "
                    "use --allow-dirty only for rehearsal"
                )
        timeout_s = config.evaluation.timeout_s
        auto_translate = config.retrieval.auto_translate
        access_preference = config.retrieval.access_preference
        corpus = config.retrieval.corpus
        trace_required = config.retrieval.effective_trace_required
        expected_configuration_sha256 = config.retrieval.effective_configuration_sha256
        failure_policy = config.evaluation.failure_policy
        warmup_policy = config.evaluation.warmup

    queries = load_queries_paired(input_files["queries_en"], input_files["queries_ko"])
    facets = _load_facet_judgments(input_files["facet_judgments"])
    axis_of = _load_axis_map(input_files["query_manifest"])
    if config is not None and len(queries) != config.evaluation.expected_query_count:
        raise ValueError(
            "query count differs from machine-readable protocol contract: "
            f"{len(queries)} != {config.evaluation.expected_query_count}"
        )
    expected_observations = len(queries) * len(LANGUAGES) * len(selected_modes)
    logger.info(
        "hard_loaded",
        queries=len(queries),
        modes=mode_values,
        expected_observations=expected_observations,
    )

    if frozen:
        assert release_dir is not None and freeze_config_path is not None and config is not None
        manifest = new_run_manifest(
            repo=repo,
            release_dir=release_dir,
            config_path=freeze_config_path,
            config=config,
            input_files=input_files,
            set_name=set_name,
            expected_observations=expected_observations,
        )

    observations: list[dict[str, Any]] = []
    observation_dir = release_dir / "observations" if release_dir else None
    factory = client_factory or GenoFinderClient
    aborted = True
    try:
        async with factory(timeout_s=timeout_s) as client:
            if frozen and warmup_policy == "unscored_recorded":
                assert release_dir is not None
                assert config is not None
                warmup_query = "warmup query for reranker cold start"
                warm_started = time.perf_counter()
                try:
                    response = await client.search(
                        query_text=warmup_query,
                        top_k=5,
                        mode=SearchMode.RRF_RERANK,
                        lang="en",
                        corpus=corpus,
                        auto_translate=auto_translate,
                        access_preference=access_preference,
                    )
                except Exception as exc:
                    warmup = {
                        "outcome": "failure",
                        "wall_ms": (time.perf_counter() - warm_started) * 1000,
                        "error": _redacted_error(exc),
                    }
                    write_json(release_dir / "warmup.json", warmup)
                    raise
                warmup_response_dict = dict(_json_safe(response))
                trace_issues = frozen_response_path_issues(
                    config=config,
                    mode=SearchMode.RRF_RERANK.value,
                    lang="en",
                    query_text=warmup_query,
                    response=warmup_response_dict,
                )
                warmup = {
                    "outcome": "success" if not trace_issues else "invalid_effective_path",
                    "wall_ms": (time.perf_counter() - warm_started) * 1000,
                    "response": warmup_response_dict,
                    "trace_issues": trace_issues,
                }
                write_json(release_dir / "warmup.json", warmup)
                if trace_issues:
                    raise ValueError(
                        "frozen warmup effective path is invalid: " + "; ".join(trace_issues)
                    )
            elif not frozen:
                await warmup_reranker(client)

            ordinal = 0
            for mode in selected_modes:
                for lang in LANGUAGES:
                    for qid, query in queries.items():
                        ordinal += 1
                        query_text = query["text_en"] if lang == "en" else query["text_ko"]
                        axis = axis_of.get(qid, query.get("category", "unknown"))
                        expected = facets.get(qid, {})
                        started_at = utc_now()
                        wall_started = time.perf_counter()
                        error: dict[str, Any] | None = None
                        deviation: dict[str, str] | None = None
                        response_dict: dict[str, Any] | None = None
                        outcome = "failure"
                        metrics: dict[str, Any] = {"eligible": False}
                        returned_count = 0
                        scored_count = 0
                        effective_query: dict[str, Any] | None = None

                        try:
                            response = await client.search(
                                query_text=query_text,
                                top_k=top_k,
                                mode=mode,
                                lang=lang,
                                corpus=corpus,
                                auto_translate=auto_translate,
                                access_preference=access_preference,
                            )
                            response_dict = dict(_json_safe(response))
                            normalized_results: list[dict[str, Any]] = []
                            for rank, result in enumerate(
                                response_dict.get("results") or [], start=1
                            ):
                                normalized = dict(result)
                                normalized["rank"] = rank
                                normalized_results.append(normalized)
                            response_dict["results"] = normalized_results
                            effective_text = str(
                                response_dict.get("translated_query") or query_text
                            )
                            effective_query = {
                                "text": effective_text,
                                "sha256": hashlib.sha256(
                                    effective_text.encode("utf-8")
                                ).hexdigest(),
                                "translation_applied": bool(response_dict.get("translated_query")),
                            }
                            returned_count = len(normalized_results)
                            scored_results = normalized_results[:score_k]
                            scored_count = len(scored_results)

                            trace_issues = (
                                frozen_response_path_issues(
                                    config=config,
                                    mode=mode.value,
                                    lang=lang,
                                    query_text=query_text,
                                    response=response_dict,
                                )
                                if config is not None
                                else _effective_trace_issues(
                                    mode=mode.value,
                                    response=response_dict,
                                    required=trace_required,
                                    expected_configuration_sha256=(expected_configuration_sha256),
                                )
                            )
                            if (
                                auto_translate
                                and lang == "ko"
                                and any(ord(char) > 127 for char in query_text)
                                and not response_dict.get("translated_query")
                            ):
                                trace_issues.append("expected Korean translation was not recorded")

                            if trace_issues:
                                deviation = {
                                    "call_id": f"{ordinal:05d}",
                                    "type": "effective_path_unverified",
                                    "message": "; ".join(trace_issues),
                                }
                            metrics = derive_hard_query_metrics(
                                expected_facets=expected,
                                response=response_dict,
                                score_k=score_k,
                                trace_issues=trace_issues,
                            )
                            outcome = "zero_result" if returned_count == 0 else "success"
                        except Exception as exc:
                            error = _redacted_error(exc)
                            if failure_policy == "zero_utility":
                                metrics = {
                                    "eligible": True,
                                    "imputed_by_prespecified_failure_policy": True,
                                    "facet": {
                                        "present_macro": 0.0,
                                        "conjunctive_macro": 0.0,
                                    },
                                    "exclusion": {
                                        "applicable": bool(expected.get("must_not_contain")),
                                        "eligible": False,
                                        "clean_at_k": None,
                                        "ineligibility_reason": "request failure",
                                    },
                                }

                        call_id = hashlib.sha256(
                            f"{set_name}\0{qid}\0{lang}\0{mode.value}".encode()
                        ).hexdigest()[:20]
                        observation = {
                            "schema_version": OBSERVATION_SCHEMA_VERSION,
                            "ordinal": ordinal,
                            "call_id": call_id,
                            "key": {
                                "set_name": set_name,
                                "qid": qid,
                                "axis": axis,
                                "lang": lang,
                                "mode": mode.value,
                            },
                            "query": {
                                "text": query_text,
                                "sha256": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
                            },
                            "effective_query": effective_query,
                            "expected_facets": expected,
                            "request": {
                                "corpus": corpus,
                                "top_k": top_k,
                                "score_k": score_k,
                                "auto_translate": auto_translate,
                                "access_preference": access_preference,
                            },
                            "started_at_utc": started_at,
                            "wall_ms": (time.perf_counter() - wall_started) * 1000,
                            "outcome": outcome,
                            "returned_count": returned_count,
                            "scored_count": scored_count,
                            "response": response_dict,
                            "metrics": metrics,
                            "error": error,
                            "deviation": deviation,
                        }
                        observations.append(observation)
                        if observation_dir is not None:
                            write_json(observation_dir / f"{ordinal:05d}.json", observation)
                        if manifest is not None and release_dir is not None:
                            update_run_counts(
                                release_dir=release_dir,
                                manifest=manifest,
                                outcome=outcome,
                                error=(
                                    {"call_id": call_id, **error} if error is not None else None
                                ),
                                deviation=deviation,
                            )
                        logger.info(
                            "hard_query_done",
                            mode=mode.value,
                            lang=lang,
                            qid=qid,
                            outcome=outcome,
                        )
        aborted = False
    finally:
        aggregate_rows = _aggregate_rows(observations) if observations else []
        if frozen:
            assert release_dir is not None and manifest is not None
            raw_path = release_dir / "per_query_responses.jsonl"
            metric_path = release_dir / "per_query_metrics.jsonl"
            failure_path = release_dir / "failures.jsonl"
            aggregate_path = release_dir / "aggregate_metrics.csv"
            _write_jsonl(raw_path, observations)
            metric_rows = [_metric_row(item) for item in observations]
            _write_jsonl(metric_path, metric_rows)
            failures = [item for item in observations if item["outcome"] == "failure"]
            _write_jsonl(failure_path, failures)
            artifacts = [
                {
                    "role": "raw_observations",
                    **file_artifact(raw_path, base=release_dir, record_count=len(observations)),
                },
                {
                    "role": "per_query_metrics",
                    **file_artifact(metric_path, base=release_dir, record_count=len(metric_rows)),
                },
                {
                    "role": "failures",
                    **file_artifact(failure_path, base=release_dir, record_count=len(failures)),
                },
            ]
            if aggregate_rows:
                _write_csv(aggregate_path, aggregate_rows)
                artifacts.append(
                    {
                        "role": "aggregate_metrics",
                        **file_artifact(
                            aggregate_path, base=release_dir, record_count=len(aggregate_rows)
                        ),
                    }
                )
            warmup_path = release_dir / "warmup.json"
            if warmup_path.exists():
                artifacts.append({"role": "warmup", **file_artifact(warmup_path, base=release_dir)})
            finalize_run_manifest(
                release_dir=release_dir,
                manifest=manifest,
                artifacts=artifacts,
                aborted=aborted,
            )
        elif not aborted:
            aggregate_path = results_dir / "aggregated" / f"{set_name}_results.csv"
            _write_csv(aggregate_path, aggregate_rows)

    if frozen:
        assert release_dir is not None
        aggregate_path = release_dir / "aggregate_metrics.csv"
    logger.info("hard_csv_written", path=str(aggregate_path), rows=len(aggregate_rows))
    return aggregate_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-name", default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--score-k", type=int, default=10)
    parser.add_argument("--modes", nargs="+", choices=[mode.value for mode in SearchMode])
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--release-dir", type=Path, default=None)
    parser.add_argument("--freeze-config", type=Path, default=None)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = asyncio.run(
        run(
            set_name=args.set_name,
            data_dir=args.data_dir,
            results_dir=args.results_dir,
            top_k=args.top_k,
            score_k=args.score_k,
            modes=args.modes,
            seed=args.seed,
            release_dir=args.release_dir,
            freeze_config_path=args.freeze_config,
            repo=args.repo,
            allow_dirty=args.allow_dirty,
        )
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
