"""Figure 3 — Score decomposition case study.

2-3 개 representative query 의 top-5 result 의 score_breakdown 을 시각화.
각 result 의 semantic / lexical / rrf / rerank 신호를 stacked bar 또는 grouped bar.

manuscript §6 (차별화 포인트 #3 "점수 가시화 / black-box 거부") 의 정량 근거.

출력:
    results/figures/figure3_score_decomp.{pdf,png}
"""
from __future__ import annotations


def render(*_args: object, **_kwargs: object) -> None:
    # TODO(step-7): SearchResponse.results[].score_breakdown 의 4개 신호 → bar
    raise NotImplementedError("Step 7 에서 구현.")
