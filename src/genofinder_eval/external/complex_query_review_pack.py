"""Render a blinded workbook as readable Markdown plus compact score sheets."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from genofinder_eval.external.complex_query_judgment_validation import (
    CONDITION_COLUMNS,
    EDITABLE_COLUMNS,
    EXCLUSION_COLUMN,
    INSUFFICIENT_COLUMN,
    NOTE_COLUMN,
    RELEVANCE_COLUMN,
    validate_judgment_workbook,
)
from genofinder_eval.external.provenance import utc_now

SCORE_COLUMN_MAP = (
    ("검토순서", "순서"),
    ("세션묶음", "세션"),
    ("판정ID", "판정ID"),
    ("질의ID", "질의ID"),
    ("후보코드", "후보코드"),
    (RELEVANCE_COLUMN, "관련성"),
    (CONDITION_COLUMNS[0], "질병"),
    (CONDITION_COLUMNS[1], "조직"),
    (CONDITION_COLUMNS[2], "세포"),
    (CONDITION_COLUMNS[3], "생물종"),
    (CONDITION_COLUMNS[4], "분석법"),
    (CONDITION_COLUMNS[5], "설계"),
    (CONDITION_COLUMNS[6], "비교군"),
    (CONDITION_COLUMNS[7], "시점처치용량"),
    (EXCLUSION_COLUMN, "제외위반"),
    (INSUFFICIENT_COLUMN, "근거부족"),
    (NOTE_COLUMN, "메모"),
)
SCORE_COLUMNS = tuple(target for _source, target in SCORE_COLUMN_MAP)
SCORE_TARGET_BY_SOURCE = dict(SCORE_COLUMN_MAP)
IDENTITY_COLUMNS = ("검토순서", "세션묶음", "판정ID", "질의ID", "후보코드")
Mode = Literal["partial", "complete"]


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


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty score sheet: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SCORE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def _markdown_inline(value: str) -> str:
    if not value:
        return "정보 없음"
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "|", "#"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped.replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ")


def _markdown_quote(value: str) -> str:
    if not value:
        return "> 정보 없음"
    plain = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    escaped = _markdown_inline(plain)
    wrapped = textwrap.wrap(
        escaped,
        width=110,
        break_long_words=False,
        break_on_hyphens=False,
    ) or ["정보 없음"]
    return "\n".join(f"> {line}" for line in wrapped)


def _render_review(batch: str, rows: list[dict[str, str]]) -> str:
    lines = [
        f"# 블라인드 관련성 판정 세션 {int(batch):02d}: 검토 자료",
        "",
        f"후보 수: {len(rows)}개",
        "",
        "이 문서는 읽기 전용 참고 자료다. 점수는 대응하는 `scores-ko.csv`에 입력한다. 후보 제목과 설명은 평가 입력의 원문이며 임의 번역하지 않았다. 시스템명, 원래 순위와 검색 점수는 포함하지 않았다.",
        "",
        "관련성 기준: `3` 명확히 만족, `2` 실제 후보로 유용, `1` 일부만 관련, `0` 무관·제외조건 위반·근거 없음.",
        "",
    ]
    by_query: dict[str, list[dict[str, str]]] = defaultdict(list)
    query_order: list[str] = []
    for row in rows:
        qid = row["질의ID"]
        if qid not in by_query:
            query_order.append(qid)
        by_query[qid].append(row)

    for qid in query_order:
        query_rows = by_query[qid]
        first = query_rows[0]
        lines.extend(
            [
                f"## 질의 {qid} · 난이도 {_markdown_inline(first['난이도'])}",
                "",
                f"**한국어 질의:** {_markdown_inline(first['한국어질의'])}",
                "",
                f"**필수조건:** {_markdown_inline(first['필수조건_한글_요약'])}",
                "",
                f"**제외조건:** {_markdown_inline(first['제외조건_한글_요약'])}",
                "",
            ]
        )
        for row in query_rows:
            lines.extend(
                [
                    f"### {row['판정ID']} · {row['후보코드']} · 검토순서 {row['검토순서']}",
                    "",
                    f"**후보 제목:** {_markdown_inline(row['후보제목'])}",
                    "",
                    "**후보 설명:**",
                    "",
                    _markdown_quote(row["후보설명"]),
                    "",
                    f"- 생물종: {_markdown_inline(row['생물종'])}",
                    f"- 분석법: {_markdown_inline(row['분석법'])}",
                    f"- 공개일: {_markdown_inline(row['공개일'])}",
                    f"- 표본 수: {_markdown_inline(row['표본수'])}",
                    "",
                ]
            )
    return "\n".join(lines)


def _render_links(batch: str, rows: list[dict[str, str]]) -> str:
    lines = [
        f"# 블라인드 관련성 판정 세션 {int(batch):02d}: GEO 링크",
        "",
        "후보 metadata만으로 판단이 어려울 때 원본 GEO record를 확인하기 위한 링크다. accession을 검색 시스템에 다시 입력해 반환 시스템을 추정하지 않는다.",
        "",
    ]
    current_qid = ""
    for row in rows:
        if row["질의ID"] != current_qid:
            current_qid = row["질의ID"]
            lines.extend([f"## 질의 {current_qid}", ""])
        label = f"{row['판정ID']} · {row['후보코드']} · 검토순서 {row['검토순서']}"
        lines.append(f"- [{label}]({row['원본_GEO_링크']})")
    return "\n".join(lines)


def _render_readme(batch_counts: dict[str, int]) -> str:
    lines = [
        "# 복합 질의 블라인드 판정용 분리 자료",
        "",
        "원래 38열 판정표를 사람이 읽기 쉬운 참고 문서와 짧은 점수표로 나눈 비공개 작업 자료다. 시스템명·순위·검색 점수는 포함하지 않는다.",
        "",
        "## 파일 사용법",
        "",
        "각 세션에는 세 파일이 있다.",
        "",
        "1. `session-XX-review-ko.md`: 한국어 질의·조건과 후보 원문 metadata를 읽는다.",
        "2. `session-XX-links-ko.md`: 필요한 경우에만 같은 후보코드의 GEO 링크를 연다.",
        "3. `session-XX-scores-ko.csv`: 관련성 및 조건 판정만 입력한다.",
        "",
        "점수표의 식별 열과 기존 `NA`는 수정하지 않는다. 점수표에는 후보 제목·설명·링크가 없으므로 검토 Markdown과 나란히 열어 후보코드 또는 판정ID를 맞춘다.",
        "",
        "후보 제목과 설명은 평가 왜곡을 막기 위해 번역하지 않고 수집 당시 원문을 사용한다. 한글 질의와 한글 필수·제외 조건을 기준으로 판정한다.",
        "",
        "점수표의 짧은 조건 열에는 해당 조건이 요구될 때 `1` 또는 `0`을 넣고, 미리 들어 있는 `NA`는 유지한다. `관련성`은 `0`–`3`, `제외위반`과 `근거부족`은 `yes`, `no` 또는 허용된 `NA`를 사용한다.",
        "",
        "## 세션 구성",
        "",
        "| 세션 | 후보 수 | 검토 자료 | GEO 링크 | 점수표 |",
        "|---:|---:|---|---|---|",
    ]
    for batch, count in sorted(batch_counts.items(), key=lambda item: int(item[0])):
        prefix = f"session-{int(batch):02d}"
        lines.append(
            f"| {int(batch)} | {count} | [{prefix}-review-ko.md]({prefix}-review-ko.md) | "
            f"[{prefix}-links-ko.md]({prefix}-links-ko.md) | "
            f"`{prefix}-scores-ko.csv` |"
        )
    lines.extend(
        [
            "",
            "완료한 점수표는 GitHub나 온라인 스프레드시트에 올리지 않는다. 세션이 끝나면 점수표와 세션 기록표를 검사한 뒤 원래 739행 워크북으로 병합한다.",
        ]
    )
    return "\n".join(lines)


def export_review_pack(
    *,
    template: Path,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Create blinded session Markdown and score sheets from the frozen template."""
    validation = validate_judgment_workbook(
        workbook=template,
        template=template,
        manifest_path=manifest_path,
        mode="blank",
    )
    if not validation.valid:
        raise ValueError(f"Blank template validation failed: {validation.errors}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Refusing to overwrite non-empty review pack: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)

    _headers, rows = _read_csv(template)
    by_batch: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_batch[row["세션묶음"]].append(row)
    batch_counts = {batch: len(batch_rows) for batch, batch_rows in by_batch.items()}

    for batch in sorted(by_batch, key=int):
        batch_rows = by_batch[batch]
        prefix = f"session-{int(batch):02d}"
        _write_text(output_dir / f"{prefix}-review-ko.md", _render_review(batch, batch_rows))
        _write_text(output_dir / f"{prefix}-links-ko.md", _render_links(batch, batch_rows))
        score_rows = [
            {target: row[source] for source, target in SCORE_COLUMN_MAP}
            for row in batch_rows
        ]
        _write_csv(output_dir / f"{prefix}-scores-ko.csv", score_rows)

    _write_text(output_dir / "README-ko.md", _render_readme(batch_counts))
    generated = sorted(path for path in output_dir.iterdir() if path.is_file())
    manifest: dict[str, Any] = {
        "artifact_type": "blinded_human_review_pack",
        "created_at_utc": utc_now(),
        "source_template_sha256": _sha256(template),
        "source_manifest_sha256": _sha256(manifest_path),
        "row_count": len(rows),
        "query_count": len({row["질의ID"] for row in rows}),
        "session_counts": dict(sorted(batch_counts.items(), key=lambda item: int(item[0]))),
        "candidate_metadata_translation": "none",
        "hidden_fields": ["system", "system_rank", "native_score", "system_count"],
        "files": {path.name: _sha256(path) for path in generated},
    }
    manifest_file = output_dir / "review-pack-manifest.json"
    _write_text(
        manifest_file,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
    )
    checksum_files = sorted(path for path in output_dir.iterdir() if path.is_file())
    checksum_path = output_dir / "REVIEW-PACK-SHA256SUMS"
    _write_text(
        checksum_path,
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_files),
    )
    os.chmod(output_dir, 0o700)
    return manifest


def merge_score_sheets(
    *,
    template: Path,
    manifest_path: Path,
    score_dir: Path,
    output: Path,
    mode: Mode,
    session_log: Path | None = None,
) -> dict[str, object]:
    """Merge compact score sheets into a full workbook and run existing validation."""
    template_headers, template_rows = _read_csv(template)
    score_paths = sorted(score_dir.glob("session-*-scores-ko.csv"))
    if not score_paths:
        raise ValueError(f"No session score sheets found in {score_dir}")
    scores: dict[str, dict[str, str]] = {}
    for path in score_paths:
        headers, rows = _read_csv(path)
        if headers != list(SCORE_COLUMNS):
            raise ValueError(f"Score columns differ from the frozen format: {path.name}")
        for row in rows:
            judgment_id = row["판정ID"]
            if not judgment_id or judgment_id in scores:
                raise ValueError(f"Missing or duplicate judgment ID in {path.name}")
            scores[judgment_id] = row
    if set(scores) != {row["판정ID"] for row in template_rows}:
        raise ValueError("Score sheets do not contain exactly the frozen judgment IDs")

    merged: list[dict[str, str]] = []
    for template_row in template_rows:
        judgment_id = template_row["판정ID"]
        score = scores[judgment_id]
        changed_identity = [
            column
            for column in IDENTITY_COLUMNS
            if score[SCORE_TARGET_BY_SOURCE[column]] != template_row[column]
        ]
        if changed_identity:
            raise ValueError(f"{judgment_id}: score-sheet identity changed: {changed_identity}")
        row = dict(template_row)
        for column in EDITABLE_COLUMNS:
            row[column] = score[SCORE_TARGET_BY_SOURCE[column]]
        merged.append(row)

    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=template_headers)
        writer.writeheader()
        writer.writerows(merged)
    output.chmod(0o600)
    validation = validate_judgment_workbook(
        workbook=output,
        template=template,
        manifest_path=manifest_path,
        mode=mode,
        session_log=session_log,
    )
    if not validation.valid:
        output.unlink()
        raise ValueError(f"Merged workbook validation failed: {validation.errors}")
    return validation.as_dict()
