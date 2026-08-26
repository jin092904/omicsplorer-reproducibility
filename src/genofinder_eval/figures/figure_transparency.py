"""점수 투명성 피겨 (2026-06-15 라이브 실측).

데모/발표용: "블랙박스 아님" — 모든 결과가 의미(semantic)·키워드(lexical) 근거를
노출. 어떤 결과는 의미검색만으로, 어떤 결과는 키워드만으로 표면화되고 RRF 가 융합,
교차 인코더가 최종 순위를 정함. 하이브리드 검색의 가치를 한 그림으로.

쿼리: "single-cell RNA-seq of human pancreatic islets" 의 top-5 (라이브 score_breakdown).
출력: results/figures/fig_score_transparency.{png,pdf}
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

TEAL = "#0d9488"
SLATE = "#64748b"
INK = "#1c1917"
GRID = "#d6d3d1"
MUTE = "#9ca3af"

QUERY = "single-cell RNA-seq of human pancreatic islets"
# (source_id, final_rank, semantic cosine|None, BM25 lexical|None)
ROWS = [
    ("GSE73727", 1, 0.846, None),
    ("GSE214517", 2, 0.822, 36.51),
    ("GSE207632", 3, None, 37.08),
    ("GSE268013", 4, 0.804, 28.45),
    ("GSE97655", 5, None, 29.62),
]


def render(out_dir: Path | None = None) -> None:
    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 12, "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK})

    lex_max = max(v for _, _, _, v in ROWS if v is not None)
    labels = [f"#{r}\n{sid}" for sid, r, _, _ in ROWS]
    sem = [s if s is not None else 0.0 for _, _, s, _ in ROWS]
    lex = [(lexical / lex_max) if lexical is not None else 0.0
           for _, _, _, lexical in ROWS]
    x = range(len(ROWS))
    w = 0.38

    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.bar([xi - w / 2 for xi in x], sem, w, label="semantic (meaning, cosine)",
           color=TEAL, edgecolor="white", linewidth=0.6)
    ax.bar([xi + w / 2 for xi in x], lex, w, label="lexical (keyword, BM25 norm.)",
           color=SLATE, edgecolor="white", linewidth=0.6)

    # 값 라벨 + "not retrieved by this method" 표시.
    for xi, (_, _, semantic, lexical) in zip(x, ROWS, strict=True):
        if semantic is None:
            ax.annotate("dense\nmiss", (xi - w / 2, 0.02), ha="center", va="bottom",
                        fontsize=8, color=MUTE, style="italic")
        else:
            ax.annotate(f"{semantic:.2f}", (xi - w / 2, semantic), xytext=(0, 2),
                        textcoords="offset points", ha="center", fontsize=9, color=INK)
        if lexical is None:
            ax.annotate("lexical\nmiss", (xi + w / 2, 0.02), ha="center", va="bottom",
                        fontsize=8, color=MUTE, style="italic")
        else:
            ax.annotate(f"{lexical:.0f}", (xi + w / 2, lexical / lex_max), xytext=(0, 2),
                        textcoords="offset points", ha="center", fontsize=9, color=INK)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("evidence strength (each signal normalized 0–1)")
    ax.set_title("Ranking transparency — every result shows its evidence\n"
                 f"top-5 for: “{QUERY}”  ·  no black box",
                 fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.35, color=GRID)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # 핵심 메시지 주석.
    ax.annotate("#1 surfaced by MEANING alone\n(no keyword overlap)",
                (0 - w / 2, 0.846), xytext=(0.35, 1.06), textcoords="data",
                fontsize=9, color=TEAL, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=TEAL, lw=1.2))

    for stem in ("fig_score_transparency",):
        fig.savefig(out_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(out_dir / f"{stem}.pdf", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / 'fig_score_transparency'}.{{png,pdf}}")


if __name__ == "__main__":
    render()
