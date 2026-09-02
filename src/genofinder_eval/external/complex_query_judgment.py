"""Create a blinded Korean relevance-judgment workbook from a completed run.

The public code writes two classes of artifacts: files that can be given to the
annotator, and ``*.restricted.*`` files that must remain hidden until all primary
judgments are frozen.  Candidate records are processed mechanically; no model is
used to assign relevance labels.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import secrets
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from genofinder_eval.external.complex_query_input import load_reviewed_query_specs
from genofinder_eval.external.models import SearchHit, SearchResponse
from genofinder_eval.external.provenance import utc_now

EXPECTED_SYSTEMS = {"omicsplorer_geo", "ncbi_geo", "omicsdi_geo"}
EXPECTED_QUERY_COUNT = 60
EXPECTED_RESPONSE_COUNT = 180
EXPECTED_TOP_K = 10
DEFAULT_SEED = 20260902

CRITERIA_COLUMNS = (
    "required_disease",
    "required_tissue",
    "required_cell_type",
    "required_organism",
    "required_modality",
    "required_design",
    "required_comparison_groups",
    "required_time_treatment_or_dose",
)

CRITERIA_OUTPUT_COLUMNS = {
    "required_disease": "필수_질병_상태",
    "required_tissue": "필수_조직_검체",
    "required_cell_type": "필수_세포유형",
    "required_organism": "필수_생물종",
    "required_modality": "필수_분석법",
    "required_design": "필수_연구설계",
    "required_comparison_groups": "필수_비교군",
    "required_time_treatment_or_dose": "필수_시점_처치_용량",
}

RATING_COLUMNS = {
    "required_disease": "질병_상태_충족_1_0_NA",
    "required_tissue": "조직_검체_충족_1_0_NA",
    "required_cell_type": "세포유형_충족_1_0_NA",
    "required_organism": "생물종_충족_1_0_NA",
    "required_modality": "분석법_충족_1_0_NA",
    "required_design": "연구설계_충족_1_0_NA",
    "required_comparison_groups": "비교군_충족_1_0_NA",
    "required_time_treatment_or_dose": "시점_처치_용량_충족_1_0_NA",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_order(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _candidate_code(qid: str, canonical_id: str, salt: str) -> str:
    return f"C{_hash_order(salt, qid, canonical_id)[:12].upper()}"


def _spreadsheet_safe(value: str) -> str:
    """Prevent untrusted public metadata from becoming a spreadsheet formula."""
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _display_quality(hit: SearchHit) -> tuple[Any, ...]:
    """Rank public display completeness without consulting system rank or score."""
    public_record = {
        "title": hit.title,
        "description": hit.description,
        "organism": sorted(hit.organism),
        "assay": sorted(hit.assay),
        "publication_date": hit.publication_date or "",
        "sample_count": hit.sample_count,
    }
    deterministic_tie_break = json.dumps(
        public_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        bool(hit.title),
        len(hit.description),
        bool(hit.organism),
        bool(hit.assay),
        bool(hit.publication_date),
        hit.sample_count is not None,
        deterministic_tie_break,
    )


def _load_prespec(
    query_csv: Path,
    criteria_csv: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    # Reuse the collection-time validator before reading display fields.
    load_reviewed_query_specs(query_csv, criteria_csv)
    queries = _read_csv(query_csv)
    criteria = _read_csv(criteria_csv)
    return (
        {row["query_id"]: row for row in queries},
        {row["query_id"]: row for row in criteria},
    )


def _load_korean_review(
    review_ko: Path,
    query_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Load the human-approved Korean view without treating it as official input."""
    rows: dict[str, dict[str, str]] = {}
    for line in review_ko.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if len(cells) != 5 or not re.fullmatch(r"[SMC]\d{2}", cells[0]):
            continue
        qid, query_ko, required, exclusion, _review = cells
        if qid in rows:
            raise ValueError(f"Duplicate Korean review row: {qid}")
        rows[qid] = {
            "query_ko": query_ko,
            "required_ko": re.sub(r"<br\s*/?>", " / ", required, flags=re.IGNORECASE),
            "exclusion_ko": re.sub(r"<br\s*/?>", " / ", exclusion, flags=re.IGNORECASE),
        }
    if set(rows) != set(query_rows):
        raise ValueError("Korean review view does not contain the same 60 query IDs")
    for qid, row in rows.items():
        if row["query_ko"] != query_rows[qid]["query_ko"]:
            raise ValueError(f"Korean review query mismatch for {qid}")
    return rows


def _load_validated_responses(
    run_dir: Path,
    query_rows: dict[str, dict[str, str]],
) -> list[SearchResponse]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("failures") != 0:
        raise ValueError("Run manifest is not a complete zero-failure run")
    if manifest.get("responses") != EXPECTED_RESPONSE_COUNT:
        raise ValueError("Run manifest does not declare exactly 180 responses")
    if set(manifest.get("systems", [])) != EXPECTED_SYSTEMS:
        raise ValueError("Run manifest systems differ from the preregistered systems")
    if manifest.get("top_k") != EXPECTED_TOP_K:
        raise ValueError("Run manifest top_k must be 10")

    failures = sorted((run_dir / "raw").glob("*/*.failure.json"))
    if failures:
        raise ValueError(f"Run contains {len(failures)} failure records")

    paths = sorted((run_dir / "raw").glob("*/*.json"))
    if len(paths) != EXPECTED_RESPONSE_COUNT:
        raise ValueError(f"Expected 180 response files; observed {len(paths)}")

    responses: list[SearchResponse] = []
    observed_pairs: list[tuple[str, str]] = []
    for path in paths:
        response = SearchResponse.model_validate_json(path.read_text(encoding="utf-8"))
        if path.parent.name != response.system or path.stem != response.qid:
            raise ValueError(f"Response path and embedded identity differ: {path}")
        if response.system not in EXPECTED_SYSTEMS:
            raise ValueError(f"Unexpected system in {path.name}")
        if response.qid not in query_rows:
            raise ValueError(f"Unexpected query ID in {path.name}")
        if response.query_text != query_rows[response.qid]["query_en"]:
            raise ValueError(f"Frozen query text mismatch for {response.qid}")
        if response.http_status != 200:
            raise ValueError(f"Non-200 response for {response.system}/{response.qid}")
        raw_bytes = json.dumps(
            response.raw_response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if hashlib.sha256(raw_bytes).hexdigest() != response.raw_sha256:
            raise ValueError(f"Raw payload checksum mismatch for {response.system}/{response.qid}")
        if response.requested_top_k != EXPECTED_TOP_K:
            raise ValueError(f"Unexpected requested_top_k for {response.system}/{response.qid}")
        if len(response.hits) > EXPECTED_TOP_K:
            raise ValueError(f"More than 10 hits for {response.system}/{response.qid}")
        canonical_ids = [hit.canonical_id for hit in response.hits]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError(f"Duplicate canonical ID in {response.system}/{response.qid}")
        observed_pairs.append((response.system, response.qid))
        responses.append(response)

    expected_pairs = {(system, qid) for system in EXPECTED_SYSTEMS for qid in query_rows}
    if set(observed_pairs) != expected_pairs or len(observed_pairs) != len(expected_pairs):
        raise ValueError("Each system must have exactly one response for every query")
    return responses


def _assign_batches(
    query_order: list[str],
    candidates_by_query: dict[str, list[dict[str, Any]]],
    maximum: int = 100,
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    rows: list[dict[str, Any]] = []
    batch = 1
    batch_size = 0
    counts: Counter[int] = Counter()
    for qid in query_order:
        query_rows = candidates_by_query[qid]
        if len(query_rows) > maximum:
            raise ValueError(f"{qid} alone exceeds the session maximum")
        if batch_size and batch_size + len(query_rows) > maximum:
            batch += 1
            batch_size = 0
        for row in query_rows:
            row["세션묶음"] = batch
            rows.append(row)
            counts[batch] += 1
            batch_size += 1
    for position, row in enumerate(rows, start=1):
        row["검토순서"] = position
        row["판정ID"] = f"J{position:04d}"
    return rows, dict(sorted(counts.items()))


def build_judgment_rows(
    *,
    responses: list[SearchResponse],
    query_rows: dict[str, dict[str, str]],
    criteria_rows: dict[str, dict[str, str]],
    korean_review_rows: dict[str, dict[str, str]],
    seed: int,
    salt: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, int]]:
    """Deduplicate candidates and return blind rows, restricted key, and batches."""
    grouped: dict[tuple[str, str], list[tuple[str, SearchHit]]] = defaultdict(list)
    for response in responses:
        for hit in response.hits:
            grouped[(response.qid, hit.canonical_id)].append((response.system, hit))

    candidates_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    key_rows: list[dict[str, Any]] = []
    for (qid, canonical_id), system_hits in grouped.items():
        query = query_rows[qid]
        criteria = criteria_rows[qid]
        display = max((hit for _, hit in system_hits), key=_display_quality)
        candidate_code = _candidate_code(qid, canonical_id, salt)
        systems = sorted({system for system, _ in system_hits})
        ranks = {
            system: min(
                hit.rank for observed_system, hit in system_hits if observed_system == system
            )
            for system in systems
        }

        blind: dict[str, Any] = {
            "검토순서": 0,
            "세션묶음": 0,
            "판정ID": "",
            "질의ID": qid,
            "난이도": query["difficulty"],
            "한국어질의": query["query_ko"],
            "영어질의": query["query_en"],
            "필수조건_한글_요약": korean_review_rows[qid]["required_ko"],
            "제외조건_한글_요약": korean_review_rows[qid]["exclusion_ko"],
        }
        for source, output in CRITERIA_OUTPUT_COLUMNS.items():
            blind[output] = criteria[source]
        exclusion = criteria["must_not_contain_or_condition"]
        blind.update(
            {
                "제외조건": exclusion,
                "후보코드": candidate_code,
                "후보제목": _spreadsheet_safe(display.title),
                "후보설명": _spreadsheet_safe(display.description),
                "생물종": " | ".join(display.organism),
                "분석법": " | ".join(display.assay),
                "공개일": display.publication_date or "",
                "표본수": "" if display.sample_count is None else display.sample_count,
                "원본_GEO_링크": (
                    "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc="
                    + quote(canonical_id, safe="")
                ),
                "관련성_0_3": "",
            }
        )
        for source, output in RATING_COLUMNS.items():
            blind[output] = "" if criteria[source] else "NA"
        blind.update(
            {
                "제외조건_위반_yes_no_NA": "" if exclusion else "NA",
                "근거부족_yes_no": "",
                "판정근거_메모": "",
            }
        )
        candidates_by_query[qid].append(blind)
        key_rows.append(
            {
                "질의ID": qid,
                "후보코드": candidate_code,
                "canonical_id": canonical_id,
                "systems": "|".join(systems),
                "ranks_json": json.dumps(ranks, sort_keys=True, separators=(",", ":")),
                "native_ids": "|".join(sorted({hit.native_id for _, hit in system_hits})),
            }
        )

    if set(candidates_by_query) != set(query_rows):
        missing = sorted(set(query_rows) - set(candidates_by_query))
        raise ValueError(f"Queries with no pooled candidates: {missing}")

    query_order = sorted(
        candidates_by_query,
        key=lambda qid: _hash_order(salt, str(seed), "query", qid),
    )
    for qid, rows in candidates_by_query.items():
        rows.sort(
            key=lambda row: _hash_order(
                salt, str(seed), "candidate", qid, str(row["후보코드"])
            )
        )
    blind_rows, batch_counts = _assign_batches(query_order, candidates_by_query)
    key_rows.sort(key=lambda row: (str(row["질의ID"]), str(row["후보코드"])))
    return blind_rows, key_rows, batch_counts


def _write_csv(path: Path, rows: list[dict[str, Any]], *, bom: bool = False) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    encoding = "utf-8-sig" if bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _session_rows(batch_counts: dict[int, int]) -> list[dict[str, Any]]:
    return [
        {
            "세션묶음": batch,
            "예정행수": count,
            "시작시각_KST": "",
            "종료시각_KST": "",
            "완료한_검토순서_범위": "",
            "메모": "",
        }
        for batch, count in batch_counts.items()
    ]


def retest_sample_size(candidate_count: int) -> int:
    """Return the preregistered 10% whole-row sample (739 -> 74)."""
    if candidate_count < 1:
        raise ValueError("candidate_count must be positive")
    return round(candidate_count * 0.10)


def export_judgment_workbook(
    *,
    run_dir: Path,
    query_csv: Path,
    criteria_csv: Path,
    review_ko: Path,
    output_dir: Path,
    seed: int = DEFAULT_SEED,
    salt: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and write blinded and restricted judgment artifacts."""
    query_rows, criteria_rows = _load_prespec(query_csv, criteria_csv)
    if len(query_rows) != EXPECTED_QUERY_COUNT:
        raise ValueError("Expected exactly 60 frozen queries")
    korean_review_rows = _load_korean_review(review_ko, query_rows)
    responses = _load_validated_responses(run_dir, query_rows)
    restricted_salt = salt or secrets.token_hex(32)
    blind_rows, key_rows, batch_counts = build_judgment_rows(
        responses=responses,
        query_rows=query_rows,
        criteria_rows=criteria_rows,
        korean_review_rows=korean_review_rows,
        seed=seed,
        salt=restricted_salt,
    )
    if len(blind_rows) != len(key_rows):
        raise ValueError("Blind workbook and restricted key have different lengths")

    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    workbook_path = output_dir / "judgment-workbook-ko.csv"
    session_path = output_dir / "session-log-ko.csv"
    key_path = output_dir / "pool-key.restricted.csv"
    retest_path = output_dir / "retest-selection.restricted.csv"
    safe_manifest_path = output_dir / "workbook-manifest.json"
    restricted_manifest_path = output_dir / "pool-manifest.restricted.json"

    _write_csv(workbook_path, blind_rows, bom=True)
    _write_csv(session_path, _session_rows(batch_counts), bom=True)
    _write_csv(key_path, key_rows)

    retest_count = retest_sample_size(len(blind_rows))
    selected = sorted(
        key_rows,
        key=lambda row: _hash_order(
            restricted_salt, str(seed), "retest", str(row["후보코드"])
        ),
    )[:retest_count]
    retest_rows = [
        {
            "질의ID": row["질의ID"],
            "후보코드": row["후보코드"],
            "공개_가능_최초일": "첫 판정 완료일로부터 7일 후",
        }
        for row in selected
    ]
    _write_csv(retest_path, retest_rows)

    safe_manifest: dict[str, Any] = {
        "artifact_type": "single_annotator_blinded_judgment_workbook",
        "created_at_utc": utc_now(),
        "query_count": len({row["질의ID"] for row in blind_rows}),
        "candidate_count": len(blind_rows),
        "retest_count_restricted": len(retest_rows),
        "randomization_seed": seed,
        "salt_sha256": hashlib.sha256(restricted_salt.encode()).hexdigest(),
        "session_maximum_rows": 100,
        "session_batch_counts": {str(key): value for key, value in batch_counts.items()},
        "source_query_csv_sha256": _sha256(query_csv),
        "source_criteria_csv_sha256": _sha256(criteria_csv),
        "source_korean_review_sha256": _sha256(review_ko),
        "source_run_manifest_sha256": _sha256(run_dir / "run_manifest.json"),
        "workbook_sha256": _sha256(workbook_path),
        "session_log_sha256": _sha256(session_path),
        "blinding": ["system", "system_rank", "native_score", "system_count"],
        "warning": "The workbook contains no relevance judgments until completed by the annotator.",
    }
    _write_json(safe_manifest_path, safe_manifest)
    _write_json(
        restricted_manifest_path,
        {
            "artifact_type": "restricted_unblinding_material",
            "created_at_utc": safe_manifest["created_at_utc"],
            "salt": restricted_salt,
            "salt_sha256": safe_manifest["salt_sha256"],
            "pool_key_sha256": _sha256(key_path),
            "retest_selection_sha256": _sha256(retest_path),
            "warning": (
                "Do not open or give this file, the pool key, or retest selection "
                "to the annotator before the protocol permits unblinding."
            ),
        },
    )

    checksum_paths = sorted(
        path for path in output_dir.iterdir() if path.is_file()
    )
    checksum_path = output_dir / "PRIVATE-SHA256SUMS"
    checksum_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    checksum_path.chmod(0o600)
    os.chmod(output_dir, 0o700)
    return safe_manifest
