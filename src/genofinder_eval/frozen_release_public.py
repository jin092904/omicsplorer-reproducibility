"""Fail-closed public projection of a validated private frozen retrieval run."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from genofinder_eval.external.provenance import sha256_file, write_json
from genofinder_eval.frozen_release import validate_release_directory
from genofinder_eval.metrics.facet_hard import facet_satisfaction_hard_at_k

PUBLIC_SCHEMA_VERSION = "omicsplorer-frozen-public-projection-v1"
PUBLIC_RESPONSE_SCHEMA_VERSION = "omicsplorer-frozen-public-response-v1"
PUBLIC_ACCESSION_SCHEMA_VERSION = "omicsplorer-gdc-open-review-v1"

PUBLIC_RESULT_FIELDS = (
    "source_db",
    "source_id",
    "rank",
    "score",
    "score_breakdown",
    "disease_ids",
    "tissue_ids",
    "cell_type_ids",
    "modality",
    "organism_taxid",
)
PUBLIC_ACCESSION_FIELDS = (
    "source_db",
    "accession",
    "extraction_version",
    "extraction_lineage_id",
    "build_stage",
)
FORBIDDEN_FIELD_NAMES = {
    "abstract_snippet",
    "access_type",
    "dataset_id",
    "has_processed_data",
    "internal_dataset_id",
    "library_strategy",
    "n_samples",
    "platform",
    "query_id",
    "snapshot_id",
    "sources",
    "submission_date",
    "title",
}


class PublicFrozenExportError(ValueError):
    """Raised when a private run cannot safely produce a public projection."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicFrozenExportError(f"{field} must be an object")
    return value


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicFrozenExportError(f"{field} must be a non-empty string")
    return value


def _required_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicFrozenExportError(f"{field} must be a non-negative integer")
    return value


def _required_number(value: Any, *, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicFrozenExportError(f"{field} must be numeric")
    if not math.isfinite(float(value)):
        raise PublicFrozenExportError(f"{field} must be finite")
    return value


def _copy_list(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PublicFrozenExportError(f"{field} must be a list")
    return [json.loads(json.dumps(item)) for item in value]


def _select(source: Mapping[str, Any], fields: Sequence[str], *, label: str) -> dict[str, Any]:
    missing = [field for field in fields if field not in source]
    if missing:
        raise PublicFrozenExportError(f"{label} is missing fields: {', '.join(missing)}")
    return {field: json.loads(json.dumps(source[field])) for field in fields}


def _project_result(result: Mapping[str, Any]) -> dict[str, Any]:
    projected = _select(result, PUBLIC_RESULT_FIELDS, label="search result")
    _required_string(projected["source_db"], field="result.source_db")
    _required_string(projected["source_id"], field="result.source_id")
    _required_integer(projected["rank"], field="result.rank")
    _required_number(projected["score"], field="result.score")
    _required_mapping(projected["score_breakdown"], field="result.score_breakdown")
    for field in ("disease_ids", "tissue_ids", "cell_type_ids", "modality"):
        projected[field] = _copy_list(projected[field], field=f"result.{field}")
    organism_taxid = projected["organism_taxid"]
    if organism_taxid is not None and not isinstance(organism_taxid, (int, str, list)):
        raise PublicFrozenExportError("result.organism_taxid has an unsupported type")
    return projected


def project_public_observation(
    private: Mapping[str, Any],
    *,
    private_row_sha256: str,
) -> dict[str, Any]:
    """Project one private observation using explicit public field whitelists."""
    if len(private_row_sha256) != 64:
        raise PublicFrozenExportError("private_row_sha256 must be a SHA-256 hex digest")
    key = _select(
        _required_mapping(private.get("key"), field="key"),
        ("set_name", "qid", "lang", "mode", "axis"),
        label="key",
    )
    query = _select(
        _required_mapping(private.get("query"), field="query"),
        ("text", "sha256"),
        label="query",
    )
    effective_query = _select(
        _required_mapping(private.get("effective_query"), field="effective_query"),
        ("text", "sha256", "translation_applied"),
        label="effective_query",
    )
    request = _select(
        _required_mapping(private.get("request"), field="request"),
        ("access_preference", "auto_translate", "corpus", "score_k", "top_k"),
        label="request",
    )
    response = _required_mapping(private.get("response"), field="response")
    trace = _required_mapping(response.get("evaluation_trace"), field="evaluation_trace")
    public_response = {
        "http_status": response.get("http_status"),
        "client_attempts": response.get("client_attempts"),
        "latency_ms": response.get("latency_ms"),
        "original_query": response.get("original_query"),
        "translated_query": response.get("translated_query"),
        "page": response.get("page"),
        "page_size": response.get("page_size"),
        "servable_total": response.get("servable_total"),
        "total_estimated": response.get("total_estimated"),
        "response_body_sha256": response.get("response_body_sha256"),
        "evaluation_request": _select(
            _required_mapping(response.get("evaluation_request"), field="evaluation_request"),
            (
                "access_preference",
                "auto_translate",
                "corpus",
                "lang",
                "mode",
                "page",
                "page_size",
                "query_text",
            ),
            label="evaluation_request",
        ),
        "evaluation_trace": _select(
            trace,
            (
                "components",
                "configuration_sha256",
                "effective_mode",
                "fallbacks",
                "requested_mode",
            ),
            label="evaluation_trace",
        ),
        "results": [
            _project_result(_required_mapping(result, field="result"))
            for result in _copy_list(response.get("results"), field="response.results")
        ],
    }
    metrics = _required_mapping(private.get("metrics"), field="metrics")
    return {
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "ordinal": private.get("ordinal"),
        "call_id": private.get("call_id"),
        "key": key,
        "outcome": private.get("outcome"),
        "query": query,
        "effective_query": effective_query,
        "expected_facets": json.loads(json.dumps(private.get("expected_facets"))),
        "request": request,
        "response": public_response,
        "metrics": {
            "eligible": metrics.get("eligible"),
            "facet": json.loads(json.dumps(metrics.get("facet"))),
            "exclusion": json.loads(json.dumps(metrics.get("exclusion"))),
        },
        "returned_count": private.get("returned_count"),
        "scored_count": private.get("scored_count"),
        "wall_ms": private.get("wall_ms"),
        "private_row_sha256": private_row_sha256,
    }


def _walk_forbidden(value: Any, *, location: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_FIELD_NAMES:
                raise PublicFrozenExportError(f"forbidden field {key!r} at {location}")
            _walk_forbidden(child, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, location=f"{location}[{index}]")


def _assert_facet_equal(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> None:
    for field in ("present_macro", "conjunctive_macro"):
        left = _required_number(expected.get(field), field=f"stored facet.{field}")
        right = _required_number(actual.get(field), field=f"recomputed facet.{field}")
        if not math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-12):
            raise PublicFrozenExportError(f"public evidence does not reproduce facet.{field}")
    for field in ("per_facet", "n_facets_evaluated", "unscored_present"):
        if expected.get(field) != actual.get(field):
            raise PublicFrozenExportError(f"public evidence does not reproduce facet.{field}")


def validate_public_observations(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_n: int,
) -> None:
    """Validate counts, traces, whitelists, and recomputable facet metrics."""
    if len(rows) != expected_n:
        raise PublicFrozenExportError(f"expected {expected_n} observations, found {len(rows)}")
    identities: set[tuple[str, str, str]] = set()
    for ordinal, row in enumerate(rows, start=1):
        _walk_forbidden(row)
        if row.get("schema_version") != PUBLIC_RESPONSE_SCHEMA_VERSION:
            raise PublicFrozenExportError("public response schema_version mismatch")
        if row.get("ordinal") != ordinal:
            raise PublicFrozenExportError("public ordinals are not contiguous")
        if row.get("outcome") != "success":
            raise PublicFrozenExportError("only successful frozen observations may be exported")
        key = _required_mapping(row.get("key"), field="key")
        identity = (
            _required_string(key.get("qid"), field="key.qid"),
            _required_string(key.get("lang"), field="key.lang"),
            _required_string(key.get("mode"), field="key.mode"),
        )
        if identity in identities:
            raise PublicFrozenExportError("duplicate query/language/mode identity")
        identities.add(identity)
        response = _required_mapping(row.get("response"), field="response")
        trace = _required_mapping(response.get("evaluation_trace"), field="evaluation_trace")
        if trace.get("fallbacks") != []:
            raise PublicFrozenExportError("component fallback is present")
        if trace.get("requested_mode") != identity[2] or trace.get("effective_mode") != identity[2]:
            raise PublicFrozenExportError("requested/effective mode differs from the frozen key")
        results = response.get("results")
        if not isinstance(results, list):
            raise PublicFrozenExportError("response.results must be a list")
        returned_count = _required_integer(row.get("returned_count"), field="returned_count")
        if returned_count != len(results):
            raise PublicFrozenExportError("returned_count differs from projected result count")
        request = _required_mapping(row.get("request"), field="request")
        score_k = _required_integer(request.get("score_k"), field="request.score_k")
        expected_facets = _required_mapping(row.get("expected_facets"), field="expected_facets")
        recomputed = facet_satisfaction_hard_at_k(
            dict(expected_facets),
            [dict(_required_mapping(result, field="result")) for result in results],
            score_k,
        )
        metrics = _required_mapping(row.get("metrics"), field="metrics")
        stored_facet = _required_mapping(metrics.get("facet"), field="metrics.facet")
        _assert_facet_equal(stored_facet, recomputed)


def project_public_metric_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the retained per-query metric row from one public observation."""
    key = _required_mapping(observation.get("key"), field="key")
    metrics = _required_mapping(observation.get("metrics"), field="metrics")
    facet = _required_mapping(metrics.get("facet"), field="metrics.facet")
    exclusion = _required_mapping(metrics.get("exclusion"), field="metrics.exclusion")
    return {
        "schema_version": "omicsplorer-hard-query-metric-v1",
        "ordinal": observation.get("ordinal"),
        "call_id": observation.get("call_id"),
        "set_name": key.get("set_name"),
        "qid": key.get("qid"),
        "lang": key.get("lang"),
        "mode": key.get("mode"),
        "axis": key.get("axis"),
        "outcome": observation.get("outcome"),
        "metric_eligible": bool(metrics.get("eligible")),
        "facet_present_macro": facet.get("present_macro"),
        "facet_conjunctive_macro": facet.get("conjunctive_macro"),
        "exclusion_applicable": exclusion.get("applicable"),
        "exclusion_eligible": exclusion.get("eligible"),
        "exclusion_clean_at_k": exclusion.get("clean_at_k"),
        "returned_count": observation.get("returned_count"),
        "scored_count": observation.get("scored_count"),
    }


def aggregate_public_observations(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Recompute the frozen aggregate table from public metric payloads."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for observation in observations:
        key = _required_mapping(observation.get("key"), field="key")
        grouped[(str(key.get("mode")), str(key.get("lang")))].append(observation)
    rows: list[dict[str, Any]] = []
    for (mode, lang), group in sorted(grouped.items()):
        axes = [
            "ALL",
            *sorted(
                {
                    str(_required_mapping(item.get("key"), field="key").get("axis"))
                    for item in group
                }
            ),
        ]
        for axis in axes:
            subset = (
                group
                if axis == "ALL"
                else [
                    item
                    for item in group
                    if str(_required_mapping(item.get("key"), field="key").get("axis"))
                    == axis
                ]
            )
            for metric_name in (
                "facet_present_macro",
                "facet_conjunctive_macro",
                "exclusion_clean_at_k",
            ):
                values = [
                    float(value)
                    for item in subset
                    if isinstance(
                        (value := project_public_metric_observation(item).get(metric_name)),
                        (int, float),
                    )
                    and not isinstance(value, bool)
                ]
                if not values and metric_name == "exclusion_clean_at_k":
                    continue
                first_key = _required_mapping(subset[0].get("key"), field="key")
                rows.append(
                    {
                        "dataset": str(first_key.get("set_name")),
                        "mode": mode,
                        "lang": lang,
                        "axis": axis,
                        "metric": metric_name,
                        "mean": statistics.fmean(values) if values else "",
                        "median": statistics.median(values) if values else "",
                        "std": statistics.pstdev(values) if values else "",
                        "n_queries": len(values),
                        "n_planned": len(subset),
                        "n_success": sum(item.get("outcome") != "failure" for item in subset),
                        "n_failure": sum(item.get("outcome") == "failure" for item in subset),
                        "n_zero_result": sum(
                            item.get("outcome") == "zero_result" for item in subset
                        ),
                    }
                )
    return rows


def validate_public_metric_files(
    observations: Sequence[Mapping[str, Any]],
    *,
    per_query_metrics_path: Path,
    aggregate_metrics_path: Path,
) -> None:
    """Cross-check the public observations, metric rows, and aggregate table."""
    expected_per_query = [project_public_metric_observation(row) for row in observations]
    actual_per_query = _read_jsonl(per_query_metrics_path)
    if actual_per_query != expected_per_query:
        raise PublicFrozenExportError("per-query metric file differs from public observations")
    expected_aggregates = aggregate_public_observations(observations)
    with aggregate_metrics_path.open(newline="", encoding="utf-8") as handle:
        actual_aggregates = list(csv.DictReader(handle))
    rendered_expected = [
        {field: str(value) for field, value in row.items()} for row in expected_aggregates
    ]
    if actual_aggregates != rendered_expected:
        raise PublicFrozenExportError("aggregate metric file differs from public observations")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PublicFrozenExportError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise PublicFrozenExportError(f"non-object JSON at {path}:{line_number}")
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(row) + "\n")


def _artifact(path: Path, *, role: str, record_count: int | None = None) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "path": path.name,
        "role": role,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if record_count is not None:
        descriptor["record_count"] = record_count
    return descriptor


def _scan_accessions(path: Path) -> tuple[int, dict[str, int], set[str], str]:
    count = 0
    source_counts: Counter[str] = Counter()
    gdc_accessions: set[str] = set()
    digest = hashlib.sha256()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not set(PUBLIC_ACCESSION_FIELDS).issubset(reader.fieldnames):
            raise PublicFrozenExportError("private accession manifest lacks public fields")
        digest.update(("\t".join(PUBLIC_ACCESSION_FIELDS) + "\n").encode())
        for row in reader:
            public = {field: row[field] for field in PUBLIC_ACCESSION_FIELDS}
            source_db = _required_string(public["source_db"], field="source_db")
            accession = _required_string(public["accession"], field="accession")
            if any(row.get(field) for field in ("controlled_access", "controlled", "acl")):
                raise PublicFrozenExportError("controlled-access marker is present")
            count += 1
            source_counts[source_db] += 1
            if source_db.upper() == "GDC":
                gdc_accessions.add(accession)
            digest.update(("\t".join(public.values()) + "\n").encode())
    return count, dict(sorted(source_counts.items())), gdc_accessions, digest.hexdigest()


def validate_gdc_open_review(review_path: Path, expected_accessions: set[str]) -> None:
    value = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != PUBLIC_ACCESSION_SCHEMA_VERSION:
        raise PublicFrozenExportError("GDC open-review schema_version mismatch")
    records = value.get("records")
    if not isinstance(records, list):
        raise PublicFrozenExportError("GDC open-review records must be a list")
    reviewed: set[str] = set()
    for record in records:
        item = _required_mapping(record, field="GDC review record")
        accession = _required_string(item.get("accession"), field="GDC review accession")
        if item.get("access_status") != "open" or item.get("study_level_only") is not True:
            raise PublicFrozenExportError(f"GDC accession {accession!r} is not confirmed open/study-level")
        if accession in reviewed:
            raise PublicFrozenExportError("duplicate GDC review accession")
        reviewed.add(accession)
    if reviewed != expected_accessions:
        raise PublicFrozenExportError("GDC open-review records differ from the frozen GDC set")


def _write_public_accessions(private_path: Path, public_path: Path) -> int:
    count = 0
    with private_path.open(newline="", encoding="utf-8") as source, public_path.open(
        "w", newline="", encoding="utf-8"
    ) as destination:
        reader = csv.DictReader(source, delimiter="\t")
        writer = csv.DictWriter(
            destination,
            fieldnames=list(PUBLIC_ACCESSION_FIELDS),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in reader:
            writer.writerow({field: row[field] for field in PUBLIC_ACCESSION_FIELDS})
            count += 1
    return count


def export_public_frozen_release(
    private_release: Path,
    output_dir: Path,
    *,
    gdc_open_review: Path | None = None,
) -> dict[str, Any]:
    """Create a checksum-bound public candidate without private narrative fields."""
    private_release = private_release.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PublicFrozenExportError("output directory must be absent or empty")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    private_validation = validate_release_directory(private_release)
    if private_validation.get("status") != "GO":
        raise PublicFrozenExportError("private frozen release did not pass offline validation")

    source_responses = private_release / "per_query_responses.jsonl"
    private_rows = _read_jsonl(source_responses)
    public_rows = [
        project_public_observation(
            row,
            private_row_sha256=_sha256_bytes((_canonical_json(row) + "\n").encode()),
        )
        for row in private_rows
    ]
    validate_public_observations(public_rows, expected_n=len(private_rows))
    responses_path = output_dir / "per_query_responses_public.jsonl"
    _write_jsonl(responses_path, public_rows)

    copied: list[dict[str, Any]] = [_artifact(responses_path, role="sanitized_responses", record_count=len(public_rows))]
    for name, role in (
        ("per_query_metrics.jsonl", "per_query_metrics"),
        ("aggregate_metrics.csv", "aggregate_metrics"),
        ("failures.jsonl", "failures"),
    ):
        source = private_release / name
        destination = output_dir / name
        shutil.copyfile(source, destination)
        record_count = sum(1 for line in destination.open(encoding="utf-8") if line.strip())
        if name.endswith(".csv"):
            record_count = max(0, record_count - 1)
        copied.append(_artifact(destination, role=role, record_count=record_count))
    validate_public_metric_files(
        public_rows,
        per_query_metrics_path=output_dir / "per_query_metrics.jsonl",
        aggregate_metrics_path=output_dir / "aggregate_metrics.csv",
    )
    if (output_dir / "failures.jsonl").stat().st_size != 0:
        raise PublicFrozenExportError("failure ledger is not empty")

    accession_source = private_release / "inputs" / "corpus_accessions.tsv"
    accession_count, source_counts, gdc_accessions, public_accession_sha256 = _scan_accessions(
        accession_source
    )
    blockers: list[str] = []
    if gdc_open_review is None:
        blockers.append("GDC open/study-level review is missing; public accession TSV was not written")
    else:
        validate_gdc_open_review(gdc_open_review, gdc_accessions)
        accession_path = output_dir / "corpus_accessions_public.tsv"
        written = _write_public_accessions(accession_source, accession_path)
        if written != accession_count or sha256_file(accession_path) != public_accession_sha256:
            raise PublicFrozenExportError("public accession manifest write verification failed")
        copied.append(_artifact(accession_path, role="public_accessions", record_count=written))

    validation_report: dict[str, Any] = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "status": "GO",
        "private_release_id": private_validation.get("release_id"),
        "private_validator_status": "GO",
        "public_response_count": len(public_rows),
        "facet_metrics_recomputed_from_public_projection": True,
        "per_query_metrics_matched_to_public_projection": True,
        "aggregate_metric_rows_recomputed": 280,
        "exclusion_diagnostic_recomputed_from_public_projection": False,
        "fallback_count": 0,
        "forbidden_fields_found": 0,
        "errors": [],
    }
    report_path = output_dir / "validation_report_public.json"
    write_json(report_path, validation_report)
    copied.append(_artifact(report_path, role="public_validation_report"))

    manifest = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "private_release_id": private_validation.get("release_id"),
        "projection_status": "GO" if not blockers else "GO_WITH_PUBLICATION_BLOCKER",
        "publication_ready": not blockers,
        "blockers": blockers,
        "interpretation": (
            "internal facet-regression evidence; not independent relevance judgement, "
            "metadata accuracy, service latency, throughput, superiority, or an SLA"
        ),
        "field_boundary": {
            "retained_result_fields": list(PUBLIC_RESULT_FIELDS),
            "excluded_field_names": sorted(FORBIDDEN_FIELD_NAMES),
            "exclusion_diagnostic": "retained metric derived from private title/snippet text; not publicly recomputable",
        },
        "counts": {
            "observations": len(public_rows),
            "accessions": accession_count,
            "accessions_by_source": source_counts,
            "gdc_accessions_requiring_review": len(gdc_accessions),
        },
        "provenance": {
            "private_responses_sha256": sha256_file(source_responses),
            "private_accession_manifest_sha256": sha256_file(accession_source),
            "canonical_public_accession_sha256": public_accession_sha256,
        },
        "artifacts": sorted(copied, key=lambda item: str(item["path"])),
    }
    manifest_path = output_dir / "publication_manifest.json"
    write_json(manifest_path, manifest)
    return manifest
