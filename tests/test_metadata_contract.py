from __future__ import annotations

import json
from pathlib import Path

import pytest

from genofinder_eval.metadata_contract import (
    MetadataContractError,
    select_model_entry,
    sha256_bytes,
    validate_contract,
    write_contract,
)


def test_select_model_entry_requires_one_full_digest() -> None:
    model = select_model_entry(
        {
            "models": [
                {
                    "name": "gemma4:31b",
                    "digest": "a" * 64,
                    "details": {"quantization_level": "Q4_K_M"},
                }
            ]
        },
        "gemma4:31b",
    )
    assert model["digest"] == "a" * 64


def test_select_model_entry_rejects_mutable_tag_without_digest() -> None:
    with pytest.raises(MetadataContractError, match="digest"):
        select_model_entry({"models": [{"name": "gemma4:31b", "digest": "short"}]}, "gemma4:31b")


def test_write_contract_hashes_every_artifact(tmp_path: Path) -> None:
    product = tmp_path / "product"
    script_dir = product / "apps/workers/scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "backfill_tissue_extraction.py").write_text("backfill\n", encoding="utf-8")
    (script_dir / "sol4_prompt.py").write_text("prompt source\n", encoding="utf-8")
    output = tmp_path / "contract"

    manifest = write_contract(
        output_dir=output,
        prompt="exact prompt",
        schema={"type": "object"},
        options={
            "first_pass_request": {"json": {"model": "gemma4:31b"}},
            "validation_retry_request": {"json": {"model": "gemma4:31b"}},
        },
        runtime={
            "model_tag": "gemma4:31b",
            "product_git_commit": "b" * 40,
            "weight_digest_sha256": "a" * 64,
        },
        product_root=product,
        product_commit="b" * 40,
    )

    assert set(manifest["artifacts"]) == {
        "sol4-prompt.txt",
        "sol4-schema.json",
        "sol4-options.json",
        "sol4-runtime.json",
    }
    for name, descriptor in manifest["artifacts"].items():
        assert descriptor["sha256"] == sha256_bytes((output / name).read_bytes())
    persisted = json.loads((output / "contract-manifest.json").read_text(encoding="utf-8"))
    assert persisted["interpretation"].endswith("effectiveness evidence.")
    assert validate_contract(output)["product_git_commit"] == "b" * 40


def test_validate_contract_rejects_tampered_artifact(tmp_path: Path) -> None:
    product = tmp_path / "product"
    script_dir = product / "apps/workers/scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "backfill_tissue_extraction.py").write_text("backfill\n", encoding="utf-8")
    (script_dir / "sol4_prompt.py").write_text("prompt source\n", encoding="utf-8")
    output = tmp_path / "contract"
    write_contract(
        output_dir=output,
        prompt="exact prompt",
        schema={"type": "object"},
        options={
            "first_pass_request": {"json": {"model": "gemma4:31b"}},
            "validation_retry_request": {"json": {"model": "gemma4:31b"}},
        },
        runtime={"model_tag": "gemma4:31b", "product_git_commit": "b" * 40},
        product_root=product,
        product_commit="b" * 40,
    )
    (output / "sol4-prompt.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(MetadataContractError, match="SHA-256 mismatch"):
        validate_contract(output)
