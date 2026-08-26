"""Historical corpus-status figure (2026-06-15 project record).

Internal-review artifact: recorded dataset rows, non-stub extraction status, and documented
source counts. Constants must be replaced by an accession-level export for submission.

출력: results/figures/fig_corpus_overview.{png,pdf}
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

TEAL = "#0d9488"
AMBER = "#f59e0b"
SLATE = "#64748b"
LIGHT = "#cbd5e1"
INK = "#1c1917"
GRID = "#d6d3d1"

# 2026-06-15 historical project statistics plus source-count figure constants.
TOTAL = 629_799
SOURCES = [("SRA", 343_186), ("GEO", 286_522), ("K-BDS*", 3_270), ("GDC", 91)]
NON_STUB, STUB = 627_323, 2_476


def render(out_dir: Path | None = None) -> None:
    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 12, "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK})
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(10.4, 4.4), gridspec_kw={"width_ratios": [1, 1.25]}
    )

    # 왼쪽: 추출 커버리지 도넛.
    rich_pct = 100 * NON_STUB / TOTAL
    wedges, _ = ax_left.pie([NON_STUB, STUB], colors=[TEAL, AMBER], startangle=90,
                            counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white"))
    ax_left.text(0, 0.12, f"{rich_pct:.1f}%", ha="center", va="center", fontsize=26,
                 fontweight="bold", color=TEAL)
    ax_left.text(0, -0.18, "non-stub status", ha="center", va="center", fontsize=12, color=INK)
    ax_left.set_title("Extraction-status coverage", fontsize=13, fontweight="bold")
    ax_left.legend(wedges, [f"non-stub  ({NON_STUB:,})", f"stub  ({STUB:,})"],
                   loc="lower center", bbox_to_anchor=(0.5, -0.16), frameon=False,
                   ncol=2, fontsize=10)

    # 오른쪽: 출처별 데이터셋 수 (가로 막대).
    labels = [s for s, _ in SOURCES]
    vals = [c for _, c in SOURCES]
    y = range(len(SOURCES))
    colors = [TEAL, SLATE, "#2563eb", AMBER]
    bars = ax_right.barh(list(y), vals, 0.6, color=colors, edgecolor="white", linewidth=0.6)
    for bar, value in zip(bars, vals, strict=True):
        ax_right.annotate(f"{value:,}", (value, bar.get_y() + bar.get_height() / 2),
                          xytext=(5, 0), textcoords="offset points", va="center",
                          fontsize=11, fontweight="bold", color=INK)
    ax_right.set_yticks(list(y))
    ax_right.set_yticklabels(labels)
    ax_right.invert_yaxis()
    ax_right.set_xlim(0, max(vals) * 1.18)
    ax_right.set_xlabel("documented source memberships")
    ax_right.set_title("Historical non-exclusive source memberships", fontsize=13, fontweight="bold")
    ax_right.grid(axis="x", alpha=0.35, color=GRID)
    ax_right.set_axisbelow(True)
    ax_right.spines["top"].set_visible(False)
    ax_right.spines["right"].set_visible(False)

    fig.suptitle(f"Historical project record — {TOTAL:,} rows, {rich_pct:.1f}% non-stub extraction status",
                 fontsize=15, fontweight="bold", y=1.02)
    fig.text(
        0.52,
        -0.01,
        "* K-BDS is an unverified historical figure constant; no current DB/active-ingester evidence was found.",
        ha="center",
        va="top",
        fontsize=9,
        color=SLATE,
    )
    for stem in ("fig_corpus_overview",):
        fig.savefig(out_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(out_dir / f"{stem}.pdf", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / 'fig_corpus_overview'}.{{png,pdf}}")


if __name__ == "__main__":
    render()
