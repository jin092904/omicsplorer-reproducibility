from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from genofinder_eval.metadata_pilot_runner import (
    PilotRunnerError,
    load_private_manifest,
    select_per_stratum,
    smoke_status,
    write_private_json,
)


def _spec() -> dict:
    return {
        "strata": [
            {"label": "sra", "target_n": 2},
            {"label": "geo", "target_n": 2},
        ]
    }


def test_select_per_stratum_preserves_declared_order() -> None:
    records = [
        {"stratum": "geo", "selection_rank": 1},
        {"stratum": "sra", "selection_rank": 1},
        {"stratum": "geo", "selection_rank": 2},
        {"stratum": "sra", "selection_rank": 2},
    ]
    selected = select_per_stratum(records, _spec(), per_stratum=1)
    assert [record["stratum"] for record in selected] == ["sra", "geo"]
    assert [record["selection_rank"] for record in selected] == [1, 1]


def test_load_private_manifest_requires_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "selection.private.jsonl"
    path.write_text(json.dumps({"stratum": "geo"}) + "\n", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(PilotRunnerError, match="0600"):
        load_private_manifest(path)


def test_write_private_json_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "result.private.json"
    write_private_json(path, {"status": "first"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_json(path, {"status": "second"})


def test_smoke_status_distinguishes_execution_failure_from_write_guard() -> None:
    assert (
        smoke_status(
            preflight_only=False,
            unchanged=True,
            results=[{"outcome": "model_or_validation_error"}],
        )
        == "complete_with_failures"
    )
    assert (
        smoke_status(preflight_only=False, unchanged=False, results=[{"outcome": "success"}])
        == "failed_write_guard"
    )
