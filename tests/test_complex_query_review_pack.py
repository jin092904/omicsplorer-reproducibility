import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from genofinder_eval.external.complex_query_review_pack import (
    SCORE_COLUMNS,
    export_review_pack,
    merge_score_sheets,
)


def _rows() -> list[dict[str, str]]:
    base = {
        "난이도": "simple",
        "한국어질의": "한글 질의",
        "영어질의": "English query",
        "필수조건_한글_요약": "질병: 예시 / 분석법: RNA-seq",
        "제외조건_한글_요약": "없음",
        "필수_질병_상태": "disease",
        "필수_조직_검체": "",
        "필수_세포유형": "",
        "필수_생물종": "",
        "필수_분석법": "RNA-seq",
        "필수_연구설계": "",
        "필수_비교군": "",
        "필수_시점_처치_용량": "",
        "제외조건": "",
        "후보설명": "Original description with *markup* and <tag>.",
        "생물종": "Homo sapiens",
        "분석법": "RNA-seq",
        "공개일": "2026-01-01",
        "표본수": "12",
        "관련성_0_3": "",
        "질병_상태_충족_1_0_NA": "",
        "조직_검체_충족_1_0_NA": "NA",
        "세포유형_충족_1_0_NA": "NA",
        "생물종_충족_1_0_NA": "NA",
        "분석법_충족_1_0_NA": "",
        "연구설계_충족_1_0_NA": "NA",
        "비교군_충족_1_0_NA": "NA",
        "시점_처치_용량_충족_1_0_NA": "NA",
        "제외조건_위반_yes_no_NA": "NA",
        "근거부족_yes_no": "",
        "판정근거_메모": "",
    }
    return [
        {
            "검토순서": "1",
            "세션묶음": "1",
            "판정ID": "J0001",
            "질의ID": "S01",
            **base,
            "후보코드": "CONE",
            "후보제목": "First | title",
            "원본_GEO_링크": "https://example.test/GSE1",
        },
        {
            "검토순서": "2",
            "세션묶음": "2",
            "판정ID": "J0002",
            "질의ID": "S02",
            **base,
            "후보코드": "CTWO",
            "후보제목": "Second title",
            "원본_GEO_링크": "https://example.test/GSE2",
        },
    ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    template = tmp_path / "template.csv"
    _write_csv(template, _rows())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_count": 2,
                "query_count": 2,
                "session_batch_counts": {"1": 1, "2": 1},
                "session_maximum_rows": 100,
                "workbook_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return template, manifest


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_review_pack_separates_reading_links_and_scores(tmp_path: Path) -> None:
    template, manifest = _fixture(tmp_path)
    output = tmp_path / "pack"
    result = export_review_pack(
        template=template,
        manifest_path=manifest,
        output_dir=output,
    )

    review = (output / "session-01-review-ko.md").read_text()
    links = (output / "session-01-links-ko.md").read_text()
    scores = _read_csv(output / "session-01-scores-ko.csv")
    assert result["row_count"] == 2
    assert "한글 질의" in review
    assert "First \\| title" in review
    assert "https://example.test/GSE1" not in review
    assert "https://example.test/GSE1" in links
    assert list(scores[0]) == list(SCORE_COLUMNS)
    assert "후보제목" not in scores[0]
    assert scores[0]["조직"] == "NA"
    assert os.stat(output / "session-01-review-ko.md").st_mode & 0o777 == 0o600


def test_merge_score_sheets_restores_full_partial_workbook(tmp_path: Path) -> None:
    template, manifest = _fixture(tmp_path)
    pack = tmp_path / "pack"
    export_review_pack(template=template, manifest_path=manifest, output_dir=pack)
    first = _read_csv(pack / "session-01-scores-ko.csv")
    first[0].update(
        {
            "관련성": "2",
            "질병": "1",
            "분석법": "1",
            "근거부족": "no",
        }
    )
    _write_csv(pack / "session-01-scores-ko.csv", first)

    output = tmp_path / "merged.csv"
    result = merge_score_sheets(
        template=template,
        manifest_path=manifest,
        score_dir=pack,
        output=output,
        mode="partial",
    )
    merged = _read_csv(output)
    assert result["completed_rows"] == 1
    assert merged[0]["후보제목"] == "First | title"
    assert merged[0]["관련성_0_3"] == "2"
    assert merged[1]["관련성_0_3"] == ""


def test_merge_rejects_changed_identity(tmp_path: Path) -> None:
    template, manifest = _fixture(tmp_path)
    pack = tmp_path / "pack"
    export_review_pack(template=template, manifest_path=manifest, output_dir=pack)
    first = _read_csv(pack / "session-01-scores-ko.csv")
    first[0]["후보코드"] = "CHANGED"
    _write_csv(pack / "session-01-scores-ko.csv", first)

    with pytest.raises(ValueError, match="identity changed"):
        merge_score_sheets(
            template=template,
            manifest_path=manifest,
            score_dir=pack,
            output=tmp_path / "merged.csv",
            mode="partial",
        )


def test_export_refuses_to_overwrite_existing_scores(tmp_path: Path) -> None:
    template, manifest = _fixture(tmp_path)
    pack = tmp_path / "pack"
    export_review_pack(template=template, manifest_path=manifest, output_dir=pack)
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        export_review_pack(template=template, manifest_path=manifest, output_dir=pack)
