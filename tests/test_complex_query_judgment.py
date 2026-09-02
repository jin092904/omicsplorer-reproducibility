import csv
import io

from genofinder_eval.external.complex_query_judgment import (
    build_judgment_rows,
    retest_sample_size,
)
from genofinder_eval.external.models import SearchHit, SearchResponse


def _response(system: str, hits: list[SearchHit]) -> SearchResponse:
    return SearchResponse(
        system=system,
        qid="S01",
        query_text="English frozen query",
        corpus="geo",
        requested_top_k=10,
        hits=hits,
        wall_latency_ms=10,
        fetched_at_utc="2026-09-02T00:00:00Z",
        endpoint="https://example.test",
        request_parameters={},
        raw_sha256="0" * 64,
        raw_response={},
        http_status=200,
        adapter_version="test",
    )


def _query_rows() -> dict[str, dict[str, str]]:
    return {
        "S01": {
            "query_id": "S01",
            "difficulty": "simple",
            "query_ko": "고정된 한국어 질의",
            "query_en": "English frozen query",
        }
    }


def _criteria_rows() -> dict[str, dict[str, str]]:
    return {
        "S01": {
            "required_disease": "disease",
            "required_tissue": "",
            "required_cell_type": "cell",
            "required_organism": "",
            "required_modality": "RNA-seq",
            "required_design": "",
            "required_comparison_groups": "",
            "required_time_treatment_or_dose": "",
            "must_not_contain_or_condition": "excluded condition",
        }
    }


def _korean_review_rows() -> dict[str, dict[str, str]]:
    return {
        "S01": {
            "query_ko": "고정된 한국어 질의",
            "required_ko": "질병: 예시 / 분석법: RNA-seq",
            "exclusion_ko": "없음",
        }
    }


def _build(salt: str = "restricted-test-salt") -> tuple[list[dict], list[dict]]:
    responses = [
        _response(
            "omicsplorer_geo",
            [SearchHit(rank=1, canonical_id="GSE1", native_id="one", title="Short")],
        ),
        _response(
            "ncbi_geo",
            [
                SearchHit(
                    rank=7,
                    canonical_id="GSE1",
                    native_id="GSE1",
                    title="Rich public title",
                    description="A longer public description",
                    organism=["Homo sapiens"],
                    sample_count=12,
                ),
                SearchHit(rank=2, canonical_id="GSE2", native_id="GSE2"),
            ],
        ),
    ]
    blind, key, _ = build_judgment_rows(
        responses=responses,
        query_rows=_query_rows(),
        criteria_rows=_criteria_rows(),
        korean_review_rows=_korean_review_rows(),
        seed=20260902,
        salt=salt,
    )
    return blind, key


def test_blind_workbook_deduplicates_and_hides_system_fields() -> None:
    blind, key = _build()
    assert len(blind) == 2
    assert len(key) == 2
    row = next(item for item in blind if item["후보제목"] == "Rich public title")
    hidden = next(item for item in key if item["canonical_id"] == "GSE1")
    assert row["후보코드"] == hidden["후보코드"]
    assert hidden["systems"] == "ncbi_geo|omicsplorer_geo"
    headers = {str(field).lower() for field in row}
    assert not any(
        forbidden in header
        for header in headers
        for forbidden in ("system", "rank", "score", "canonical", "native_id")
    )


def test_rating_cells_prefill_na_only_when_condition_is_not_required() -> None:
    blind, _ = _build()
    row = blind[0]
    assert row["질병_상태_충족_1_0_NA"] == ""
    assert row["세포유형_충족_1_0_NA"] == ""
    assert row["조직_검체_충족_1_0_NA"] == "NA"
    assert row["제외조건_위반_yes_no_NA"] == ""
    assert row["관련성_0_3"] == ""


def test_fixed_seed_and_salt_produce_identical_blind_csv_bytes() -> None:
    first, _ = _build("same")
    second, _ = _build("same")
    different, _ = _build("different")

    def render(rows: list[dict]) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode()

    assert render(first) == render(second)
    assert render(first) != render(different)


def test_retest_sample_size_matches_frozen_protocol() -> None:
    assert retest_sample_size(739) == 74
