from genofinder_eval.external.normalize import canonical_geo_series, plain_text, unique_strings


def test_canonical_geo_series_only_accepts_series() -> None:
    assert canonical_geo_series("gse00123") == "GSE123"
    assert canonical_geo_series("prefix GSE 42 suffix") == "GSE42"
    assert canonical_geo_series("GSM123") is None
    assert canonical_geo_series("GDS123") is None


def test_public_metadata_text_normalization() -> None:
    assert plain_text("<p>A&nbsp; B</p>\n C") == "A B C"
    assert unique_strings(["Human", "human", "", None, "Mouse"]) == ["Human", "Mouse"]
