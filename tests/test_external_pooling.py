from genofinder_eval.external.models import SearchHit, SearchResponse
from genofinder_eval.external.pooling import build_pool


def _response(system: str, hits: list[SearchHit]) -> SearchResponse:
    return SearchResponse(
        system=system,
        qid="q1",
        query_text="lung cancer",
        corpus="geo",
        requested_top_k=10,
        hits=hits,
        wall_latency_ms=10,
        fetched_at_utc="2026-07-20T00:00:00Z",
        endpoint="https://example.test",
        request_parameters={},
        raw_sha256="0" * 64,
        raw_response={},
        http_status=200,
        adapter_version="test",
    )


def test_pool_deduplicates_accession_and_hides_system_from_blind_sheet() -> None:
    responses = [
        _response(
            "a",
            [SearchHit(rank=1, canonical_id="GSE1", native_id="1", title="Short")],
        ),
        _response(
            "b",
            [
                SearchHit(
                    rank=3,
                    canonical_id="GSE1",
                    native_id="GSE1",
                    title="Better title",
                    description="Longer public description",
                ),
                SearchHit(rank=4, canonical_id="GSE2", native_id="GSE2"),
            ],
        ),
    ]
    blind, key = build_pool(responses, salt="fixed")

    assert len(blind) == 2
    assert len(key) == 2
    first_blind = next(row for row in blind if row["title"] == "Better title")
    first_key = next(row for row in key if row["canonical_id"] == "GSE1")
    assert first_blind["candidate_code"] == first_key["candidate_code"]
    assert "system" not in first_blind
    assert first_key["systems"] == "a|b"
    assert first_key["ranks_json"] == '{"a":1,"b":3}'


def test_candidate_codes_are_deterministic_for_restricted_salt() -> None:
    responses = [_response("a", [SearchHit(rank=1, canonical_id="GSE1", native_id="1")])]
    blind_a, _ = build_pool(responses, salt="same")
    blind_b, _ = build_pool(responses, salt="same")
    blind_c, _ = build_pool(responses, salt="different")
    assert blind_a[0]["candidate_code"] == blind_b[0]["candidate_code"]
    assert blind_a[0]["candidate_code"] != blind_c[0]["candidate_code"]
