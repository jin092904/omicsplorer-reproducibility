"""Freeze the exact Sol4 prompt, schema, request options, and local-model runtime."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.request import urlopen

from jsonschema import Draft202012Validator


class MetadataContractError(ValueError):
    """Raised when a supposedly frozen contract cannot be established exactly."""


RETRY_PROMPT_TEMPLATE = (
    "{base_prompt}\n\nYOUR PREVIOUS RESPONSE FAILED VALIDATION. ERROR: "
    "{validation_error_truncated_200}. Re-emit the JSON object correctly. "
    "Output ONLY the JSON object, nothing else."
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(product_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=product_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def clean_product_commit(product_root: Path) -> str:
    if not (product_root / ".git").exists():
        raise MetadataContractError(f"not a Git worktree: {product_root}")
    dirty = _git(product_root, "status", "--porcelain")
    if dirty:
        raise MetadataContractError("product worktree is dirty; refusing to freeze a contract")
    commit = _git(product_root, "rev-parse", "HEAD")
    if len(commit) != 40:
        raise MetadataContractError("product commit is not a full 40-character Git object ID")
    return commit


def _load_module(name: str, path: Path, search_paths: list[Path]) -> ModuleType:
    original = list(sys.path)
    try:
        sys.path[:0] = [str(path) for path in search_paths]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise MetadataContractError(f"cannot load product module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original


def load_product_modules(product_root: Path) -> tuple[ModuleType, ModuleType]:
    workers = product_root / "apps" / "workers"
    scripts = workers / "scripts"
    prompt_module = _load_module(
        "_omicsplorer_sol4_prompt_contract",
        scripts / "sol4_prompt.py",
        [scripts, workers],
    )
    backfill_module = _load_module(
        "_omicsplorer_sol4_backfill_contract",
        scripts / "backfill_tissue_extraction.py",
        [scripts, workers],
    )
    return prompt_module, backfill_module


class _CaptureResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"response": "{}"}


class _CaptureClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any], timeout: float) -> _CaptureResponse:
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        return _CaptureResponse()


async def _capture_request(
    backfill_module: ModuleType,
    *,
    temperature: float,
    prompt_marker: str,
) -> dict[str, Any]:
    client = _CaptureClient()
    generator = getattr(backfill_module, "_ollama_generate", None)
    if generator is None:
        raise MetadataContractError("product _ollama_generate function is missing")
    await generator(client, prompt_marker, temperature=temperature, max_retries=1)
    if len(client.requests) != 1:
        raise MetadataContractError("expected exactly one captured Ollama request")
    return client.requests[0]


def capture_options(
    backfill_module: ModuleType,
    *,
    model_tag: str,
    ollama_url: str,
) -> dict[str, Any]:
    product: Any = backfill_module
    product.OLLAMA_MODEL = model_tag
    product.OLLAMA_URL = ollama_url.rstrip("/")
    source = inspect.getsource(product.llm_extract_sol4)
    required_retry_fragments = (
        "retry_msg[:200]",
        "Re-emit the JSON object correctly.",
        "Output ONLY the JSON object, nothing else.",
        "temperature=0.1",
        "temperature=0.0",
    )
    if any(fragment not in source for fragment in required_retry_fragments):
        raise MetadataContractError("product validation-retry policy no longer matches exporter")

    first = asyncio.run(
        _capture_request(backfill_module, temperature=0.1, prompt_marker="__BASE_PROMPT__")
    )
    retry = asyncio.run(
        _capture_request(backfill_module, temperature=0.0, prompt_marker="__RETRY_PROMPT__")
    )
    return {
        "schema_version": "omicsplorer-sol4-request-options-v1",
        "first_pass_request": first,
        "validation_retry_request": retry,
        "validation_retry_count": 1,
        "validation_retry_prompt_template": RETRY_PROMPT_TEMPLATE,
        "validation_error_truncation_chars": 200,
        "infrastructure_max_attempts": int(product.CB_MAX_RETRIES),
        "output_schema_delivery": "downstream_jsonschema_only",
        "output_schema_omitted_from_ollama_request": True,
        "output_schema_omission_reason": (
            "Ollama 0.23.3 SchemaToGrammar crash observed with the nested schema; "
            "the product validates parsed JSON downstream instead"
        ),
        "code_fence_stripping": True,
        "downstream_validator": {
            "package": "jsonschema",
            "version": importlib.metadata.version("jsonschema"),
            "schema_draft": "https://json-schema.org/draft/2020-12/schema",
        },
    }


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise MetadataContractError(f"expected JSON object from {url}")
    return cast(dict[str, Any], value)


def select_model_entry(tags: Mapping[str, Any], model_tag: str) -> dict[str, Any]:
    models = tags.get("models")
    if not isinstance(models, list):
        raise MetadataContractError("Ollama tags response has no models list")
    matches = [item for item in models if isinstance(item, dict) and item.get("name") == model_tag]
    if len(matches) != 1:
        raise MetadataContractError(f"expected exactly one installed model named {model_tag}")
    model = cast(dict[str, Any], matches[0])
    digest = model.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise MetadataContractError("installed model has no full SHA-256 digest")
    return model


def gpu_descriptor(gpu_index: int) -> dict[str, Any]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [line.split(", ") for line in result.stdout.splitlines() if line.strip()]
    matches = [row for row in rows if len(row) == 4 and int(row[0]) == gpu_index]
    if len(matches) != 1:
        raise MetadataContractError(f"GPU index {gpu_index} is not uniquely available")
    index, name, driver, memory_mib = matches[0]
    return {
        "physical_index": int(index),
        "name": name,
        "driver_version": driver,
        "memory_total_mib": int(memory_mib),
    }


def runtime_contract(
    *,
    ollama_url: str,
    model_tag: str,
    product_commit: str,
    gpu_index: int,
) -> dict[str, Any]:
    version = fetch_json(f"{ollama_url.rstrip('/')}/api/version")
    model = select_model_entry(fetch_json(f"{ollama_url.rstrip('/')}/api/tags"), model_tag)
    details = model.get("details")
    if not isinstance(details, dict):
        raise MetadataContractError("installed model details are missing")
    return {
        "schema_version": "omicsplorer-sol4-runtime-v1",
        "checkpoint": f"{model_tag}@sha256:{model['digest']}",
        "model_tag": model_tag,
        "weight_digest_sha256": model["digest"],
        "model_size_bytes": model.get("size"),
        "format": details.get("format"),
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "serving_engine": f"Ollama {version.get('version')}",
        "ollama_version": version.get("version"),
        "product_git_commit": product_commit,
        "gpu": gpu_descriptor(gpu_index),
        "limitations": (
            "A model tag alone is mutable; eligibility is bound to the full installed-model "
            "digest. Hardware describes this pilot host and does not imply portability or "
            "identical timing on another host."
        ),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_contract(
    *,
    output_dir: Path,
    prompt: str,
    schema: Mapping[str, Any],
    options: Mapping[str, Any],
    runtime: Mapping[str, Any],
    product_root: Path,
    product_commit: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = output_dir / "sol4-prompt.txt"
    schema_path = output_dir / "sol4-schema.json"
    options_path = output_dir / "sol4-options.json"
    runtime_path = output_dir / "sol4-runtime.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    _write_json(schema_path, schema)
    _write_json(options_path, options)
    _write_json(runtime_path, runtime)

    artifact_paths = [prompt_path, schema_path, options_path, runtime_path]
    source_paths = [
        product_root / "apps/workers/scripts/backfill_tissue_extraction.py",
        product_root / "apps/workers/scripts/sol4_prompt.py",
    ]
    manifest = {
        "schema_version": "omicsplorer-sol4-frozen-contract-v1",
        "status": "frozen_for_write_disabled_feasibility_pilot",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "product_git_commit": product_commit,
        "artifacts": {
            path.name: {"sha256": sha256_bytes(path.read_bytes())} for path in artifact_paths
        },
        "product_sources": {
            str(path.relative_to(product_root)): {"sha256": sha256_bytes(path.read_bytes())}
            for path in source_paths
        },
        "interpretation": (
            "This contract fixes the input/output mechanics for a write-disabled feasibility "
            "pilot. It is not metadata-accuracy or effectiveness evidence."
        ),
    }
    _write_json(output_dir / "contract-manifest.json", manifest)
    return manifest


def validate_contract(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "contract-manifest.json"
    if not manifest_path.is_file():
        raise MetadataContractError("frozen contract manifest is missing")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MetadataContractError("frozen contract manifest must be a JSON object")
    manifest = cast(dict[str, Any], value)
    if manifest.get("schema_version") != "omicsplorer-sol4-frozen-contract-v1":
        raise MetadataContractError("unsupported frozen contract schema_version")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise MetadataContractError("frozen contract has no artifact descriptors")
    for name, raw_descriptor in artifacts.items():
        if not isinstance(name, str) or not isinstance(raw_descriptor, dict):
            raise MetadataContractError("invalid artifact descriptor")
        expected = raw_descriptor.get("sha256")
        path = output_dir / name
        if not isinstance(expected, str) or len(expected) != 64 or not path.is_file():
            raise MetadataContractError(f"incomplete artifact descriptor: {name}")
        if sha256_bytes(path.read_bytes()) != expected:
            raise MetadataContractError(f"artifact SHA-256 mismatch: {name}")

    runtime = json.loads((output_dir / "sol4-runtime.json").read_text(encoding="utf-8"))
    options = json.loads((output_dir / "sol4-options.json").read_text(encoding="utf-8"))
    schema = json.loads((output_dir / "sol4-schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    if runtime.get("product_git_commit") != manifest.get("product_git_commit"):
        raise MetadataContractError("runtime and manifest product commits differ")
    if options.get("first_pass_request", {}).get("json", {}).get("model") != runtime.get(
        "model_tag"
    ):
        raise MetadataContractError("request model tag and runtime model tag differ")
    if options.get("validation_retry_request", {}).get("json", {}).get("model") != runtime.get(
        "model_tag"
    ):
        raise MetadataContractError("retry model tag and runtime model tag differ")
    return manifest


def freeze_contract(
    *,
    product_root: Path,
    output_dir: Path,
    ollama_url: str,
    model_tag: str,
    gpu_index: int,
) -> dict[str, Any]:
    product_commit = clean_product_commit(product_root)
    prompt_module, backfill_module = load_product_modules(product_root)
    prompt = getattr(prompt_module, "SOL4_PROMPT_TEMPLATE", None)
    schema = getattr(backfill_module, "SOL4_OUTPUT_SCHEMA", None)
    if not isinstance(prompt, str) or not prompt:
        raise MetadataContractError("product Sol4 prompt is missing")
    if not isinstance(schema, dict) or not schema:
        raise MetadataContractError("product Sol4 schema is missing")
    options = capture_options(
        backfill_module,
        model_tag=model_tag,
        ollama_url=ollama_url,
    )
    runtime = runtime_contract(
        ollama_url=ollama_url,
        model_tag=model_tag,
        product_commit=product_commit,
        gpu_index=gpu_index,
    )
    return write_contract(
        output_dir=output_dir,
        prompt=prompt,
        schema=schema,
        options=options,
        runtime=runtime,
        product_root=product_root,
        product_commit=product_commit,
    )
