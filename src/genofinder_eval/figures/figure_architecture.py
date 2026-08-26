"""시스템 아키텍처/파이프라인 다이어그램 (논문 Figure 1 + 덱 보완).

데이터 흐름 한 장: Harvest → Extract(LLM) → Index → Search. 각 단계 핵심 컴포넌트/모델.
출력: results/figures/fig_architecture.{png,pdf}
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

TEAL = "#0d9488"
TEAL_BG = "#d7f0ec"
AMBER = "#f59e0b"
SLATE = "#475569"
INK = "#1c1917"
CARD = "#f8fafc"
BORDER = "#94a3b8"

STAGES = [
    ("1  HARVEST", "scheduled / incremental harvest", [
        "GEO · SRA/ENA · GDC adapters",
        "public repository APIs",
        "last-success watermark",
        "source provenance retained",
    ]),
    ("2  EXTRACT", "model-assisted structuring", [
        "self-hosted model endpoint",
        "constrained metadata schema",
        "MONDO · UBERON · Cell Ontology",
        "deterministic correction",
        "lineage evidence required",
    ]),
    ("3  INDEX", "relational + dual search index", [
        "PostgreSQL + provenance",
        "→ Qdrant 1024d (dense)",
        "→ OpenSearch BM25 (lexical)",
        "checkpoint/digest to freeze",
    ]),
    ("4  SEARCH", "hybrid retrieval + inspection", [
        "KO→EN configured translation",
        "dense + BM25 → RRF (k=60)",
        "optional cross-encoder reranking",
        "source accession + ranking evidence",
        "cohort summary + reuse commands",
    ]),
]


def render(out_dir: Path | None = None) -> None:
    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 11, "text.color": INK})

    fig, ax = plt.subplots(figsize=(12, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    n = len(STAGES)
    gap = 2.0
    box_w = (100 - gap * (n - 1)) / n
    box_h = 64
    y0 = 20
    centers = []
    for i, (title, subtitle, items) in enumerate(STAGES):
        x = i * (box_w + gap)
        # 카드
        ax.add_patch(FancyBboxPatch((x, y0), box_w, box_h,
                     boxstyle="round,pad=0.6,rounding_size=2.5",
                     linewidth=1.4, edgecolor=BORDER, facecolor=CARD, zorder=2))
        # 헤더 띠
        ax.add_patch(FancyBboxPatch((x, y0 + box_h - 13), box_w, 13,
                     boxstyle="round,pad=0.6,rounding_size=2.5",
                     linewidth=0, facecolor=TEAL, zorder=3))
        ax.text(x + box_w / 2, y0 + box_h - 6.5, title, ha="center", va="center",
                fontsize=12.5, fontweight="bold", color="white", zorder=4)
        ax.text(x + box_w / 2, y0 + box_h - 18, subtitle, ha="center", va="center",
                fontsize=10.5, color=SLATE, style="italic", zorder=4)
        for j, it in enumerate(items):
            ax.text(x + box_w / 2, y0 + box_h - 27 - j * 8.0, it, ha="center", va="center",
                    fontsize=9.6, color=INK, zorder=4)
        centers.append((x + box_w, x))

    # 단계 간 화살표
    for i in range(n - 1):
        x_end = centers[i][0]
        x_next = centers[i + 1][1]
        ax.add_patch(FancyArrowPatch((x_end + 0.1, y0 + box_h / 2),
                     (x_next - 0.1, y0 + box_h / 2),
                     arrowstyle="-|>", mutation_scale=20, linewidth=2.2,
                     color=AMBER, zorder=5))

    # 상단 타이틀
    ax.text(50, 95, "OmicsPlorer — harvest → extract → index → search",
            ha="center", fontsize=15, fontweight="bold", color=INK)
    # 하단 배너
    ax.add_patch(FancyBboxPatch((0, 2), 100, 11,
                 boxstyle="round,pad=0.4,rounding_size=2", linewidth=0,
                 facecolor=TEAL_BG, zorder=1))
    ax.text(50, 7.5,
            "historical 629,799-row record  ·  99.6% non-stub status (not accuracy)  ·  bilingual queries  ·  visible ranking evidence",
            ha="center", va="center", fontsize=11, color="#0f5f57", fontweight="bold", zorder=2)

    for stem in ("fig_architecture",):
        fig.savefig(out_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(out_dir / f"{stem}.pdf", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / 'fig_architecture'}.{{png,pdf}}")


if __name__ == "__main__":
    render()
