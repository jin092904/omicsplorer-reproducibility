"""Serial, resumable external-service collection runner."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import httpx

from genofinder_eval.external.clients import (
    NCBIGeoClient,
    OmicsDIGeoClient,
    OmicsPlorerClient,
    SearchClient,
)
from genofinder_eval.external.models import QuerySpec, RunFailure, SearchResponse
from genofinder_eval.external.provenance import build_manifest, utc_now, write_json

PROTOCOL_VERSION = "external-services-v1.0.0"
SYSTEMS = ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")


def load_queries(path: Path) -> list[QuerySpec]:
    queries: list[QuerySpec] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                query = QuerySpec.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"Invalid query at {path}:{line_number}: {exc}") from exc
            if query.qid in seen:
                raise ValueError(f"Duplicate qid: {query.qid}")
            seen.add(query.qid)
            queries.append(query)
    if not queries:
        raise ValueError(f"No queries found in {path}")
    return queries


def _make_clients(names: list[str]) -> dict[str, SearchClient]:
    clients: dict[str, SearchClient] = {}
    for name in names:
        if name == "omicsplorer_geo":
            clients[name] = OmicsPlorerClient()
        elif name == "ncbi_geo":
            clients[name] = NCBIGeoClient()
        elif name == "omicsdi_geo":
            clients[name] = OmicsDIGeoClient()
        else:
            raise ValueError(f"Unknown system: {name}")
    return clients


async def _collect_one(
    client: SearchClient,
    query: QuerySpec,
    *,
    top_k: int,
    attempts: int = 3,
) -> SearchResponse | RunFailure:
    started = time.perf_counter()
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await client.search(query, top_k=top_k)
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError, KeyError) as exc:
            last_error = exc
            retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if not retryable or attempt == attempts:
                break
            retry_after = 0.0
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    retry_after = float(exc.response.headers.get("Retry-After", "0"))
                except ValueError:
                    retry_after = 0.0
            await asyncio.sleep(max(retry_after, float(2 ** (attempt - 1))))

    elapsed_ms = (time.perf_counter() - started) * 1000
    message = str(last_error or "unknown error")
    api_key = os.environ.get("NCBI_API_KEY", "")
    if api_key:
        message = message.replace(api_key, "<redacted>")
    return RunFailure(
        system=client.system,
        qid=query.qid,
        error_type=type(last_error).__name__ if last_error else "UnknownError",
        message=message[:1000],
        fetched_at_utc=utc_now(),
        elapsed_ms=elapsed_ms,
        retry_count=max(0, attempts - 1),
    )


async def collect_run(
    *,
    repo: Path,
    query_file: Path,
    output_dir: Path,
    systems: list[str],
    top_k: int,
    seed: int,
    force: bool,
) -> dict[str, Any]:
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if len(systems) != len(set(systems)):
        raise ValueError("systems contains duplicates")
    unknown = sorted(set(systems) - set(SYSTEMS))
    if unknown:
        raise ValueError(f"Unknown systems: {unknown}")

    queries = load_queries(query_file)
    manifest_path = output_dir / "run_manifest.json"
    if manifest_path.exists() and not force:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("query_file_sha256") != build_manifest(
            repo=repo,
            query_file=query_file,
            systems=systems,
            top_k=top_k,
            seed=seed,
            protocol_version=PROTOCOL_VERSION,
            api_key_used=bool(os.environ.get("NCBI_API_KEY")),
        )["query_file_sha256"]:
            raise ValueError("Existing run has a different query file; choose another output dir")

    manifest = build_manifest(
        repo=repo,
        query_file=query_file,
        systems=systems,
        top_k=top_k,
        seed=seed,
        protocol_version=PROTOCOL_VERSION,
        api_key_used=bool(os.environ.get("NCBI_API_KEY")),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(manifest_path, manifest)

    rng = random.Random(seed)
    rng.shuffle(queries)
    clients = _make_clients(systems)
    responses = 0
    failures = 0
    try:
        for query_index, query in enumerate(queries):
            rotated = systems[query_index % len(systems):] + systems[:query_index % len(systems)]
            for system in rotated:
                raw_dir = output_dir / "raw" / system
                response_path = raw_dir / f"{query.qid}.json"
                failure_path = raw_dir / f"{query.qid}.failure.json"
                if response_path.exists() and not force:
                    responses += 1
                    continue
                result = await _collect_one(clients[system], query, top_k=top_k)
                if isinstance(result, SearchResponse):
                    write_json(response_path, result.model_dump(mode="json"))
                    if failure_path.exists():
                        failure_path.unlink()
                    responses += 1
                else:
                    write_json(failure_path, result.model_dump(mode="json"))
                    failures += 1
                manifest["responses"] = responses
                manifest["failures"] = failures
                write_json(manifest_path, manifest)
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))

    manifest["status"] = "complete" if failures == 0 else "complete_with_failures"
    manifest["completed_at_utc"] = utc_now()
    manifest["responses"] = responses
    manifest["failures"] = failures
    write_json(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--systems", nargs="+", choices=SYSTEMS, default=list(SYSTEMS))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = asyncio.run(
        collect_run(
            repo=args.repo.resolve(),
            query_file=args.queries.resolve(),
            output_dir=args.output.resolve(),
            systems=list(args.systems),
            top_k=args.top_k,
            seed=args.seed,
            force=args.force,
        )
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["failures"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
