"""Validate blank, in-progress, or completed blinded judgment workbooks."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Mode = Literal["blank", "partial", "complete"]

RELEVANCE_COLUMN = "관련성_0_3"
CONDITION_COLUMNS = (
    "질병_상태_충족_1_0_NA",
    "조직_검체_충족_1_0_NA",
    "세포유형_충족_1_0_NA",
    "생물종_충족_1_0_NA",
    "분석법_충족_1_0_NA",
    "연구설계_충족_1_0_NA",
    "비교군_충족_1_0_NA",
    "시점_처치_용량_충족_1_0_NA",
)
EXCLUSION_COLUMN = "제외조건_위반_yes_no_NA"
INSUFFICIENT_COLUMN = "근거부족_yes_no"
NOTE_COLUMN = "판정근거_메모"
EDITABLE_COLUMNS = {
    RELEVANCE_COLUMN,
    *CONDITION_COLUMNS,
    EXCLUSION_COLUMN,
    INSUFFICIENT_COLUMN,
    NOTE_COLUMN,
}
SYSTEM_IDENTIFIERS = ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")
MAX_ERRORS = 50


@dataclass(frozen=True)
class ValidationResult:
    mode: Mode
    valid: bool
    row_count: int
    completed_rows: int
    remaining_rows: int
    query_count: int
    session_count: int
    workbook_sha256: str
    template_sha256: str
    errors: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _append_error(errors: list[str], message: str) -> None:
    if len(errors) < MAX_ERRORS:
        errors.append(message)
    elif len(errors) == MAX_ERRORS:
        errors.append("Additional errors omitted")


def _manifest_batch_counts(manifest: dict[str, object]) -> dict[str, int]:
    raw = manifest.get("session_batch_counts")
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, int):
            counts[key] = value
    return counts


def _validate_identity_and_structure(
    *,
    headers: list[str],
    rows: list[dict[str, str]],
    template_headers: list[str],
    template_rows: list[dict[str, str]],
    manifest: dict[str, object],
    errors: list[str],
) -> None:
    if headers != template_headers:
        _append_error(errors, "Workbook columns or column order differ from the template")
        return
    required_headers = {
        "검토순서",
        "세션묶음",
        "판정ID",
        "질의ID",
        "후보코드",
        *EDITABLE_COLUMNS,
    }
    missing = sorted(required_headers - set(headers))
    if missing:
        _append_error(errors, f"Required columns are missing: {missing}")
        return
    if len(rows) != len(template_rows):
        _append_error(errors, "Workbook row count differs from the frozen template")
    if len(rows) != manifest.get("candidate_count"):
        _append_error(errors, "Workbook row count differs from the manifest")

    immutable = [header for header in headers if header not in EDITABLE_COLUMNS]
    for position, (row, template) in enumerate(
        zip(rows, template_rows, strict=False), start=1
    ):
        judgment_id = template.get("판정ID", f"row {position}")
        if row.get("검토순서") != str(position):
            _append_error(errors, f"{judgment_id}: randomized row order was changed")
        changed = [field for field in immutable if row.get(field) != template.get(field)]
        if changed:
            _append_error(
                errors,
                f"{judgment_id}: protected source fields were changed: {changed}",
            )

    ids = [row.get("판정ID", "") for row in rows]
    codes = [row.get("후보코드", "") for row in rows]
    if not all(ids) or len(ids) != len(set(ids)):
        _append_error(errors, "Judgment IDs must be non-empty and unique")
    if not all(codes) or len(codes) != len(set(codes)):
        _append_error(errors, "Candidate codes must be non-empty and unique")
    if len({row.get("질의ID", "") for row in rows}) != manifest.get("query_count"):
        _append_error(errors, "Workbook query count differs from the manifest")

    observed_batches = Counter(row.get("세션묶음", "") for row in rows)
    expected_batches = _manifest_batch_counts(manifest)
    if dict(sorted(observed_batches.items())) != dict(sorted(expected_batches.items())):
        _append_error(errors, "Session batch counts differ from the manifest")
    raw_maximum = manifest.get("session_maximum_rows", 100)
    maximum = raw_maximum if isinstance(raw_maximum, int) else 100
    if observed_batches and max(observed_batches.values()) > maximum:
        _append_error(errors, "A session batch exceeds the preregistered maximum")


def _validate_rating_row(
    *,
    row: dict[str, str],
    template: dict[str, str],
    mode: Mode,
    errors: list[str],
    warnings: list[str],
) -> bool:
    judgment_id = row.get("판정ID", "unknown row")
    relevance = row.get(RELEVANCE_COLUMN, "")
    completed = relevance != ""
    if relevance not in {"", "0", "1", "2", "3"}:
        _append_error(errors, f"{judgment_id}: relevance must be 0, 1, 2, or 3")

    if mode == "blank" and completed:
        _append_error(errors, f"{judgment_id}: blank template already contains a judgment")
    if mode == "complete" and not completed:
        _append_error(errors, f"{judgment_id}: relevance judgment is missing")

    for column in CONDITION_COLUMNS:
        expected_na = template.get(column) == "NA"
        value = row.get(column, "")
        if expected_na:
            if value != "NA":
                _append_error(errors, f"{judgment_id}: {column} must remain NA")
        elif completed:
            if value not in {"0", "1"}:
                _append_error(errors, f"{judgment_id}: {column} must be 0 or 1")
        elif value:
            _append_error(errors, f"{judgment_id}: condition was entered before relevance")

    exclusion = row.get(EXCLUSION_COLUMN, "")
    exclusion_is_na = template.get(EXCLUSION_COLUMN) == "NA"
    if exclusion_is_na:
        if exclusion != "NA":
            _append_error(errors, f"{judgment_id}: exclusion field must remain NA")
    elif completed:
        if exclusion not in {"yes", "no", "NA"}:
            _append_error(errors, f"{judgment_id}: exclusion must be yes, no, or NA")
    elif exclusion:
        _append_error(errors, f"{judgment_id}: exclusion was entered before relevance")

    insufficient = row.get(INSUFFICIENT_COLUMN, "")
    if completed and insufficient not in {"yes", "no"}:
        _append_error(errors, f"{judgment_id}: insufficient evidence must be yes or no")
    if not completed and insufficient:
        _append_error(errors, f"{judgment_id}: evidence flag was entered before relevance")

    if relevance == "3":
        required_values = [
            row[column]
            for column in CONDITION_COLUMNS
            if template.get(column) != "NA"
        ]
        if any(value != "1" for value in required_values):
            warnings.append(f"{judgment_id}: relevance 3 has a required condition below 1")
        if exclusion not in {"no", "NA"}:
            warnings.append(f"{judgment_id}: relevance 3 has an exclusion warning")
        if insufficient != "no":
            warnings.append(f"{judgment_id}: relevance 3 is marked insufficient evidence")
    return completed


def _validate_session_log(
    *,
    session_log: Path,
    manifest: dict[str, object],
    require_complete: bool,
    errors: list[str],
) -> None:
    headers, rows = _read_csv(session_log)
    expected_headers = [
        "세션묶음",
        "예정행수",
        "시작시각_KST",
        "종료시각_KST",
        "완료한_검토순서_범위",
        "메모",
    ]
    if headers != expected_headers:
        _append_error(errors, "Session log columns differ from the template")
        return
    expected_counts = {
        key: str(value) for key, value in _manifest_batch_counts(manifest).items()
    }
    observed_counts = {row["세션묶음"]: row["예정행수"] for row in rows}
    if observed_counts != expected_counts:
        _append_error(errors, "Session log batch counts differ from the manifest")
    if require_complete:
        for row in rows:
            batch = row["세션묶음"]
            for column in ("시작시각_KST", "종료시각_KST", "완료한_검토순서_범위"):
                if not row[column]:
                    _append_error(errors, f"Session {batch}: {column} is missing")


def validate_judgment_workbook(
    *,
    workbook: Path,
    template: Path,
    manifest_path: Path,
    mode: Mode,
    session_log: Path | None = None,
) -> ValidationResult:
    """Validate progress without reading or using the restricted unblinding key."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workbook_sha = _sha256(workbook)
    template_sha = _sha256(template)
    errors: list[str] = []
    warnings: list[str] = []
    if template_sha != manifest.get("workbook_sha256"):
        _append_error(errors, "Blank template SHA-256 differs from the frozen manifest")
    if mode == "blank" and workbook_sha != template_sha:
        _append_error(errors, "Blank workbook differs from the frozen template")

    raw_lower = workbook.read_text(encoding="utf-8-sig").lower()
    if any(identifier in raw_lower for identifier in SYSTEM_IDENTIFIERS):
        _append_error(errors, "Workbook contains a hidden system identifier")

    template_headers, template_rows = _read_csv(template)
    headers, rows = _read_csv(workbook)
    _validate_identity_and_structure(
        headers=headers,
        rows=rows,
        template_headers=template_headers,
        template_rows=template_rows,
        manifest=manifest,
        errors=errors,
    )

    completed_rows = 0
    if headers == template_headers:
        for row, template_row in zip(rows, template_rows, strict=False):
            completed_rows += int(
                _validate_rating_row(
                    row=row,
                    template=template_row,
                    mode=mode,
                    errors=errors,
                    warnings=warnings,
                )
            )
    if session_log is not None:
        _validate_session_log(
            session_log=session_log,
            manifest=manifest,
            require_complete=mode == "complete",
            errors=errors,
        )
    elif mode == "complete":
        _append_error(errors, "Completed validation requires the session log")

    return ValidationResult(
        mode=mode,
        valid=not errors,
        row_count=len(rows),
        completed_rows=completed_rows,
        remaining_rows=max(0, len(rows) - completed_rows),
        query_count=len({row.get("질의ID", "") for row in rows}),
        session_count=len({row.get("세션묶음", "") for row in rows}),
        workbook_sha256=workbook_sha,
        template_sha256=template_sha,
        errors=errors,
        warnings=warnings[:MAX_ERRORS],
    )
