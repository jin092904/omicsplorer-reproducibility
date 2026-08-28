from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from genofinder_eval.metadata_pilot_batch import (
    BatchPilotError,
    append_private_result,
    chained_result,
    load_result_chain,
    ordered_all_records,
    target_records,
    trailing_failure_count,
    write_private_json_atomic,
)


def _spec() -> dict:
    return {
        "strata": [
            {"label": "sra", "target_n": 2},
            {"label": "gdc", "target_n": 1},
        ]
    }


def _records() -> list[dict]:
    return [
        {"stratum": "gdc", "selection_rank": 1, "record_key_sha256": "g1"},
        {"stratum": "sra", "selection_rank": 2, "record_key_sha256": "s2"},
        {"stratum": "sra", "selection_rank": 1, "record_key_sha256": "s1"},
    ]


def test_ordered_all_records_uses_spec_then_rank() -> None:
    selected = ordered_all_records(_records(), _spec())
    assert [record["record_key_sha256"] for record in selected] == ["s1", "s2", "g1"]


def test_target_records_requires_exactly_one_mode() -> None:
    with pytest.raises(BatchPilotError, match="exactly one"):
        target_records(_records(), _spec(), all_records=False, per_stratum=None)
    mode, selected = target_records(_records(), _spec(), all_records=True, per_stratum=None)
    assert mode == "all_records"
    assert len(selected) == 3


def test_result_chain_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    path = tmp_path / "results.private.jsonl"
    first = chained_result(
        {"record_key_sha256": "s1", "outcome": "success"},
        sequence=1,
        previous_sha256=None,
    )
    second = chained_result(
        {"record_key_sha256": "s2", "outcome": "success"},
        sequence=2,
        previous_sha256=first["record_sha256"],
    )
    append_private_result(path, first)
    append_private_result(path, second)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(load_result_chain(path)) == 2

    lines = path.read_text(encoding="utf-8").splitlines()
    changed = json.loads(lines[0])
    changed["result"]["outcome"] = "edited"
    lines[0] = json.dumps(changed)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(BatchPilotError, match="SHA-256 mismatch"):
        load_result_chain(path)


def test_atomic_manifest_is_private(tmp_path: Path) -> None:
    path = tmp_path / "run-manifest.json"
    write_private_json_atomic(path, {"status": "running"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "running"


def test_trailing_failure_count_survives_resume_boundary() -> None:
    chain = [
        {"result": {"outcome": "runner_error"}},
        {"result": {"outcome": "success"}},
        {"result": {"outcome": "validation_failed"}},
        {"result": {"outcome": "runner_error"}},
    ]
    assert trailing_failure_count(chain) == 2
    assert trailing_failure_count(chain[:2]) == 0
    assert trailing_failure_count([]) == 0
