"""Figure 1 — 4-system ablation (bioCADDIE + Expert-curated 30q).

Left subplot:
    bioCADDIE infNDCG / Recall@100 by mode (grouped bar, 4 mode).
    errorbar = 95% bootstrap CI. 통계적 유의 차이는 * / ** / *** 표기.

Right subplot:
    Expert-curated 30q nDCG@10 / Facet-Sat by mode (grouped bar).
    (TTFR 메트릭은 본 figure 에 포함하지 않음 — TTFR 자체 제외.)

출력:
    results/figures/figure1_ablation.{pdf,png}
    results/figures/figure1_ablation_caption.txt
"""
from __future__ import annotations


def render(*_args: object, **_kwargs: object) -> None:
    # TODO(step-7): matplotlib subplot 2개 → ax.bar + errorbar + significance bracket
    raise NotImplementedError("Step 7 에서 구현.")
