import csv
import hashlib
import json
from pathlib import Path

from genofinder_eval.external.complex_query_judgment_validation import (
    validate_judgment_workbook,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    rows = [
        {
            "검토순서": "1",
            "세션묶음": "1",
            "판정ID": "J0001",
            "질의ID": "S01",
            "후보코드": "CONE",
            "후보제목": "public title",
            "관련성_0_3": "",
            "질병_상태_충족_1_0_NA": "",
            "조직_검체_충족_1_0_NA": "NA",
            "세포유형_충족_1_0_NA": "",
            "생물종_충족_1_0_NA": "NA",
            "분석법_충족_1_0_NA": "",
            "연구설계_충족_1_0_NA": "NA",
            "비교군_충족_1_0_NA": "NA",
            "시점_처치_용량_충족_1_0_NA": "NA",
            "제외조건_위반_yes_no_NA": "NA",
            "근거부족_yes_no": "",
            "판정근거_메모": "",
        },
        {
            "검토순서": "2",
            "세션묶음": "1",
            "판정ID": "J0002",
            "질의ID": "S02",
            "후보코드": "CTWO",
            "후보제목": "another title",
            "관련성_0_3": "",
            "질병_상태_충족_1_0_NA": "",
            "조직_검체_충족_1_0_NA": "",
            "세포유형_충족_1_0_NA": "NA",
            "생물종_충족_1_0_NA": "NA",
            "분석법_충족_1_0_NA": "",
            "연구설계_충족_1_0_NA": "NA",
            "비교군_충족_1_0_NA": "NA",
            "시점_처치_용량_충족_1_0_NA": "NA",
            "제외조건_위반_yes_no_NA": "",
            "근거부족_yes_no": "",
            "판정근거_메모": "",
        },
    ]
    template = tmp_path / "template.csv"
    workbook = tmp_path / "workbook.csv"
    _write_csv(template, rows)
    _write_csv(workbook, rows)
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_count": 2,
                "query_count": 2,
                "session_batch_counts": {"1": 2},
                "session_maximum_rows": 100,
                "workbook_sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    session = tmp_path / "session.csv"
    _write_csv(
        session,
        [
            {
                "세션묶음": "1",
                "예정행수": "2",
                "시작시각_KST": "",
                "종료시각_KST": "",
                "완료한_검토순서_범위": "",
                "메모": "",
            }
        ],
    )
    return template, workbook, manifest, session


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_blank_template_passes(tmp_path: Path) -> None:
    template, workbook, manifest, session = _fixture(tmp_path)
    result = validate_judgment_workbook(
        workbook=workbook,
        template=template,
        manifest_path=manifest,
        mode="blank",
        session_log=session,
    )
    assert result.valid
    assert result.completed_rows == 0
    assert result.remaining_rows == 2


def test_partial_mode_accepts_one_complete_row(tmp_path: Path) -> None:
    template, workbook, manifest, session = _fixture(tmp_path)
    rows = _read_rows(workbook)
    rows[0].update(
        {
            "관련성_0_3": "2",
            "질병_상태_충족_1_0_NA": "1",
            "세포유형_충족_1_0_NA": "1",
            "분석법_충족_1_0_NA": "1",
            "근거부족_yes_no": "no",
        }
    )
    _write_csv(workbook, rows)
    result = validate_judgment_workbook(
        workbook=workbook,
        template=template,
        manifest_path=manifest,
        mode="partial",
        session_log=session,
    )
    assert result.valid
    assert result.completed_rows == 1
    assert result.remaining_rows == 1


def test_invalid_value_and_protected_edit_fail(tmp_path: Path) -> None:
    template, workbook, manifest, _ = _fixture(tmp_path)
    rows = _read_rows(workbook)
    rows[0]["관련성_0_3"] = "4"
    rows[0]["후보제목"] = "changed"
    _write_csv(workbook, rows)
    result = validate_judgment_workbook(
        workbook=workbook,
        template=template,
        manifest_path=manifest,
        mode="partial",
    )
    assert not result.valid
    assert any("protected source fields" in error for error in result.errors)
    assert any("relevance must be" in error for error in result.errors)


def test_complete_mode_requires_every_row_and_session_record(tmp_path: Path) -> None:
    template, workbook, manifest, session = _fixture(tmp_path)
    result = validate_judgment_workbook(
        workbook=workbook,
        template=template,
        manifest_path=manifest,
        mode="complete",
        session_log=session,
    )
    assert not result.valid
    assert any("relevance judgment is missing" in error for error in result.errors)
    assert any("시작시각_KST is missing" in error for error in result.errors)
