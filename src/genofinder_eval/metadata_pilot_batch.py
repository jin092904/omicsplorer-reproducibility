"""Resumable, write-disabled batch orchestration for the metadata feasibility pilot."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import asyncpg

from genofinder_eval.metadata_contract import (
    clean_product_commit,
    load_product_modules,
    sha256_bytes,
    validate_contract,
)
from genofinder_eval.metadata_pilot import sha256_json, validate_records
from genofinder_eval.metadata_pilot_runner import (
    _run_one,
    activate_product_import_paths,
    database_dsn,
    load_private_manifest,
    observe_model_residency,
    observe_stores,
    select_per_stratum,
    verify_live_runtime,
    verify_selected_inputs,
)


class BatchPilotError(ValueError):
    """Raised when batch evidence cannot be safely created or resumed."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ordered_all_records(
    records: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for stratum in spec["strata"]:
        label = str(stratum["label"])
        matches = sorted(
            (dict(record) for record in records if record.get("stratum") == label),
            key=lambda record: int(record["selection_rank"]),
        )
        expected = int(stratum["target_n"])
        if len(matches) != expected:
            raise BatchPilotError(f"stratum {label} does not contain its full target")
        selected.extend(matches)
    return selected


def target_records(
    records: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    *,
    all_records: bool,
    per_stratum: int | None,
) -> tuple[str, list[dict[str, Any]]]:
    if all_records == (per_stratum is not None):
        raise BatchPilotError("choose exactly one of all_records or per_stratum")
    if all_records:
        return "all_records", ordered_all_records(records, spec)
    assert per_stratum is not None
    return f"per_stratum_{per_stratum}", select_per_stratum(
        records,
        spec,
        per_stratum=per_stratum,
    )


def clean_evaluator_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise BatchPilotError("evaluator worktree is dirty; run only from a committed checkout")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(commit) != 40:
        raise BatchPilotError("evaluator commit is not a full Git object ID")
    return commit


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    path.chmod(0o700)


def write_private_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def chained_result(
    result: Mapping[str, Any],
    *,
    sequence: int,
    previous_sha256: str | None,
) -> dict[str, Any]:
    envelope = {
        "schema_version": "omicsplorer-metadata-pilot-chain-record-v1",
        "sequence": sequence,
        "previous_record_sha256": previous_sha256,
        "result": dict(result),
    }
    return {**envelope, "record_sha256": sha256_json(envelope)}


def append_private_result(path: Path, envelope: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def load_result_chain(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BatchPilotError("result chain must have mode 0600")
    records: list[dict[str, Any]] = []
    previous: str | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise BatchPilotError(f"result line {line_number} is not a JSON object")
        record = cast(dict[str, Any], raw)
        if record.get("sequence") != len(records) + 1:
            raise BatchPilotError("result sequence is not contiguous")
        if record.get("previous_record_sha256") != previous:
            raise BatchPilotError("result hash chain is broken")
        expected = record.get("record_sha256")
        unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
        if expected != sha256_json(unsigned):
            raise BatchPilotError("result record SHA-256 mismatch")
        result = record.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("record_key_sha256"), str):
            raise BatchPilotError("result payload is incomplete")
        previous = str(expected)
        records.append(record)
    return records


def _plan(
    *,
    mode: str,
    selected: Sequence[Mapping[str, Any]],
    failure_stop: int,
) -> dict[str, Any]:
    if failure_stop <= 0:
        raise BatchPilotError("failure_stop must be positive")
    return {
        "selection_mode": mode,
        "target_n": len(selected),
        "target_record_keys_sha256": sha256_json(
            [record["record_key_sha256"] for record in selected]
        ),
        "target_by_stratum": dict(Counter(str(record["stratum"]) for record in selected)),
        "failure_stop": failure_stop,
        "execution_order": "selection specification stratum order, then selection_rank",
        "parallelism": 1,
    }


def _validate_resume(
    manifest: Mapping[str, Any],
    *,
    immutable: Mapping[str, Any],
    plan: Mapping[str, Any],
    chain: Sequence[Mapping[str, Any]],
    selected: Sequence[Mapping[str, Any]],
) -> None:
    for key, expected in immutable.items():
        if manifest.get(key) != expected:
            raise BatchPilotError(f"resume mismatch: {key}")
    if manifest.get("plan") != plan:
        raise BatchPilotError("resume plan differs from the original run")
    if manifest.get("status") in {"complete", "complete_with_failures"}:
        raise BatchPilotError("completed run cannot be resumed")
    if len(chain) > len(selected):
        raise BatchPilotError("result chain is longer than the target")
    for index, envelope in enumerate(chain):
        result = cast(Mapping[str, Any], envelope["result"])
        if result.get("record_key_sha256") != selected[index].get("record_key_sha256"):
            raise BatchPilotError("result chain does not match the target order")


class StopController:
    def __init__(self) -> None:
        self.requested = False
        self.signal_name: str | None = None

    def install(self) -> None:
        def handler(signum: int, _frame: Any) -> None:
            self.requested = True
            self.signal_name = signal.Signals(signum).name

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


def _outcome_counts(chain: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    values = [
        str(cast(Mapping[str, Any], envelope["result"]).get("outcome"))
        for envelope in chain
    ]
    return dict(Counter(values))


def trailing_failure_count(chain: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for envelope in reversed(chain):
        result = cast(Mapping[str, Any], envelope["result"])
        if result.get("outcome") == "success":
            break
        count += 1
    return count


async def run_batch(
    *,
    repo_root: Path,
    database_url: str,
    selection_manifest: Path,
    selection_spec: Mapping[str, Any],
    contract_dir: Path,
    product_root: Path,
    run_dir: Path,
    ollama_url: str,
    qdrant_url: str,
    opensearch_url: str,
    all_records: bool,
    per_stratum: int | None,
    failure_stop: int,
    resume: bool,
) -> dict[str, Any]:
    evaluator_commit = clean_evaluator_commit(repo_root)
    contract = validate_contract(contract_dir)
    product_commit = clean_product_commit(product_root)
    if product_commit != contract.get("product_git_commit"):
        raise BatchPilotError("product checkout does not match the frozen contract")
    runtime = verify_live_runtime(contract_dir, ollama_url=ollama_url)

    all_selected = load_private_manifest(selection_manifest)
    validate_records(all_selected, selection_spec)
    mode, selected = target_records(
        all_selected,
        selection_spec,
        all_records=all_records,
        per_stratum=per_stratum,
    )
    plan = _plan(mode=mode, selected=selected, failure_stop=failure_stop)
    immutable = {
        "schema_version": "omicsplorer-metadata-pilot-batch-run-v1",
        "evaluator_git_commit": evaluator_commit,
        "product_git_commit": product_commit,
        "contract_manifest_sha256": sha256_bytes(
            (contract_dir / "contract-manifest.json").read_bytes()
        ),
        "selection_manifest_sha256": sha256_bytes(selection_manifest.read_bytes()),
    }
    manifest_path = run_dir / "run-manifest.json"
    results_path = run_dir / "results.private.jsonl"

    if resume:
        if not run_dir.is_dir() or stat.S_IMODE(run_dir.stat().st_mode) != 0o700:
            raise BatchPilotError("resume directory must exist with mode 0700")
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, dict):
            raise BatchPilotError("run manifest must be a JSON object")
        manifest = cast(dict[str, Any], raw_manifest)
        chain = load_result_chain(results_path)
        _validate_resume(
            manifest,
            immutable=immutable,
            plan=plan,
            chain=chain,
            selected=selected,
        )
    else:
        _private_directory(run_dir)
        chain = []
        manifest = {
            **immutable,
            "status": "initializing",
            "interpretation": (
                "write-disabled feasibility batch; no metadata-accuracy or effectiveness claim"
            ),
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "plan": plan,
            "processed_n": 0,
            "outcome_counts": {},
        }
        write_private_json_atomic(manifest_path, manifest)

    activate_product_import_paths(product_root)
    prompt_module, product_module = load_product_modules(product_root)
    frozen_prompt = (contract_dir / "sol4-prompt.txt").read_text(encoding="utf-8")
    if prompt_module.SOL4_PROMPT_TEMPLATE != frozen_prompt:
        raise BatchPilotError("loaded product prompt differs from frozen prompt")
    frozen_schema = json.loads((contract_dir / "sol4-schema.json").read_text(encoding="utf-8"))
    if product_module.SOL4_OUTPUT_SCHEMA != frozen_schema:
        raise BatchPilotError("loaded product schema differs from frozen schema")

    controller = StopController()
    controller.install()
    connection = await asyncpg.connect(database_dsn(database_url))
    run_started = time.perf_counter()
    try:
        await verify_selected_inputs(connection, selected)
        current_stores = await observe_stores(
            connection,
            selected,
            qdrant_url=qdrant_url,
            opensearch_url=opensearch_url,
        )
        if resume:
            if current_stores != manifest.get("store_observation_initial"):
                raise BatchPilotError("stores changed since the batch was created")
        else:
            manifest["store_observation_initial"] = current_stores
            manifest["model_residency_initial"] = observe_model_residency(
                ollama_url, str(runtime["model_tag"])
            )

        manifest["status"] = "running"
        manifest["updated_at_utc"] = utc_now()
        write_private_json_atomic(manifest_path, manifest)

        consecutive_failures = trailing_failure_count(chain)
        previous = str(chain[-1]["record_sha256"]) if chain else None
        for index in range(len(chain), len(selected)):
            if controller.requested:
                break
            selection = selected[index]
            try:
                result = await _run_one(
                    connection,
                    product_module,
                    selection,
                    ollama_url=ollama_url,
                    model_tag=str(runtime["model_tag"]),
                )
                result["schema_version"] = "omicsplorer-metadata-pilot-result-v1"
            except Exception as error:
                result = {
                    "schema_version": "omicsplorer-metadata-pilot-result-v1",
                    "record_key_sha256": selection["record_key_sha256"],
                    "stratum": selection["stratum"],
                    "input_sha256": selection["source_input_sha256"],
                    "outcome": "runner_error",
                    "error_type": type(error).__name__,
                }
            envelope = chained_result(
                result,
                sequence=index + 1,
                previous_sha256=previous,
            )
            append_private_result(results_path, envelope)
            chain.append(envelope)
            previous = str(envelope["record_sha256"])
            consecutive_failures = (
                0 if result.get("outcome") == "success" else consecutive_failures + 1
            )
            manifest.update(
                {
                    "updated_at_utc": utc_now(),
                    "processed_n": len(chain),
                    "last_record_sha256": previous,
                    "outcome_counts": _outcome_counts(chain),
                    "elapsed_seconds_this_process": time.perf_counter() - run_started,
                }
            )
            write_private_json_atomic(manifest_path, manifest)
            if consecutive_failures >= failure_stop:
                manifest["status"] = "paused_failure_threshold"
                break

        final_stores = await observe_stores(
            connection,
            selected,
            qdrant_url=qdrant_url,
            opensearch_url=opensearch_url,
        )
        unchanged = final_stores == manifest["store_observation_initial"]
        if not unchanged:
            status = "failed_write_guard"
        elif manifest.get("status") == "paused_failure_threshold":
            status = "paused_failure_threshold"
        elif controller.requested:
            status = "paused_signal"
        elif len(chain) == len(selected):
            status = (
                "complete"
                if all(
                    cast(Mapping[str, Any], envelope["result"]).get("outcome") == "success"
                    for envelope in chain
                )
                else "complete_with_failures"
            )
        else:
            status = "paused_incomplete"
        manifest.update(
            {
                "status": status,
                "updated_at_utc": utc_now(),
                "processed_n": len(chain),
                "outcome_counts": _outcome_counts(chain),
                "store_observation_latest": final_stores,
                "write_guard_passed": unchanged,
                "stop_signal": controller.signal_name,
                "elapsed_seconds_this_process": time.perf_counter() - run_started,
                "model_residency_latest": observe_model_residency(
                    ollama_url, str(runtime["model_tag"])
                ),
            }
        )
        write_private_json_atomic(manifest_path, manifest)
        return manifest
    except Exception as error:
        manifest.update(
            {
                "status": "aborted",
                "updated_at_utc": utc_now(),
                "processed_n": len(chain),
                "outcome_counts": _outcome_counts(chain),
                "error_type": type(error).__name__,
                "elapsed_seconds_this_process": time.perf_counter() - run_started,
            }
        )
        try:
            write_private_json_atomic(manifest_path, manifest)
        except Exception:
            # Preserve the original exception if even the emergency manifest write fails.
            pass
        raise
    finally:
        await connection.close()
