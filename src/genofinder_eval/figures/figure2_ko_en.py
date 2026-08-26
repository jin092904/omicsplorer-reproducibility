"""Figure 2 — Korean / English parity.

xy scatter:
    x = expert-curated 30 query 의 EN nDCG@10
    y = 동일 query 의 KO nDCG@10
    y=x diagonal 표시 — 위쪽이면 KO 우세, 아래쪽이면 EN 우세

또는 paired bar (Short / Medium / Complex × KO / EN).

v0.8 baseline 비교는 Step 11 (Optional) 에서 추가. first submission 에서는 v1.0 단독.

출력:
    results/figures/figure2_ko_en.{pdf,png}
"""
from __future__ import annotations


def render(*_args: object, **_kwargs: object) -> None:
    # TODO(step-7): scatter + diagonal + paired bar 둘 다 시도, 보기 좋은 쪽 채택
    raise NotImplementedError("Step 7 에서 구현.")
