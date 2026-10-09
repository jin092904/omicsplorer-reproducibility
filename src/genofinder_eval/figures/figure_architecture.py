"""Render the OmicsPlorer lifecycle diagram (Figure 1 of the manuscript).

The four stages are harvest, model-assisted structuring, indexing, and search, drawn as
ggplot2-style facets. The command-line entry point writes PNG, PDF, and a 600-dpi RGB TIFF to
build/figures by default.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from PIL import Image

# ggplot2 theme_gray colours, so the three manuscript figures share one look.
PANEL = "#EBEBEB"  # panel background (grey92)
STRIP = "#D9D9D9"  # facet strip (grey85)
STRIP_TEXT = "#1A1A1A"  # grey10
SUBTITLE = "#4D4D4D"  # grey30
INK = "#333333"  # grey20
ARROW = "#4D4D4D"

STAGES = [
    ("1  Harvest", "incremental harvest", [
        "GEO · SRA/ENA · GDC",
        "public repository APIs",
        "last-success watermark",
        "provenance retained",
    ]),
    ("2  Extract", "model-assisted structuring", [
        "self-hosted model",
        "constrained schema",
        "MONDO · UBERON · CL",
        "deterministic correction",
        "lineage evidence required",
    ]),
    ("3  Index", "relational + search indexes", [
        "PostgreSQL + provenance",
        "→ Qdrant 1024d (dense)",
        "→ OpenSearch (BM25)",
        "checkpoint digests",
    ]),
    ("4  Search", "retrieval + inspection", [
        "KO→EN translation",
        "dense + BM25 → RRF",
        "cross-encoder reranking",
        "ranking evidence",
        "cohort + reuse commands",
    ]),
]

ROOT = Path(__file__).resolve().parents[3]


def render(out_dir: Path | None = None) -> None:
    out_dir = out_dir or ROOT / "build" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcdefaults()
    plt.rcParams.update({"font.size": 7, "text.color": INK})

    # 7.1 in (about 18 cm) is the full text width, so printed text stays at 6–8 pt.
    fig, ax = plt.subplots(figsize=(7.1, 2.25))
    fig.subplots_adjust(left=0.035, right=0.965, top=0.97, bottom=0.03)
    ax.set_xlim(-0.5, 100.5)
    ax.set_ylim(0, 60)
    ax.axis("off")

    n = len(STAGES)
    gap = 3.6
    box_w = (100 - gap * (n - 1)) / n
    y0, box_h, head_h = 1.0, 57, 7.5
    for i, (title, subtitle, items) in enumerate(STAGES):
        x = i * (box_w + gap)
        ax.add_patch(Rectangle((x, y0), box_w, box_h - head_h, linewidth=0,
                               facecolor=PANEL, zorder=2))
        ax.add_patch(Rectangle((x, y0 + box_h - head_h), box_w, head_h, linewidth=0,
                               facecolor=STRIP, zorder=3))
        ax.text(x + box_w / 2, y0 + box_h - head_h / 2, title, ha="center", va="center",
                fontsize=8, color=STRIP_TEXT, zorder=4)
        ax.text(x + box_w / 2, y0 + box_h - head_h - 5.5, subtitle, ha="center", va="center",
                fontsize=6.2, color=SUBTITLE, style="italic", zorder=4)
        for j, item in enumerate(items):
            ax.text(x + box_w / 2, y0 + box_h - head_h - 14 - j * 7.4, item, ha="center",
                    va="center", fontsize=6.2, color=INK, zorder=4)
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((x + box_w + 0.4, y0 + (box_h - head_h) / 2),
                                         (x + box_w + gap - 0.4, y0 + (box_h - head_h) / 2),
                                         arrowstyle="-|>", mutation_scale=10, linewidth=1.4,
                                         color=ARROW, zorder=5))

    # GPB: figure titles and legends belong in the manuscript, not in the image.
    fig.savefig(out_dir / "fig_architecture.png", dpi=300, bbox_inches="tight", pad_inches=0.06)
    fig.savefig(
        out_dir / "fig_architecture.pdf",
        dpi=300,
        bbox_inches="tight",
        pad_inches=0.06,
        metadata={"CreationDate": None, "ModDate": None},
    )
    tiff_path = out_dir / "fig_architecture.tiff"
    fig.savefig(
        tiff_path,
        dpi=600,
        bbox_inches="tight",
        pad_inches=0.06,
        pil_kwargs={"compression": "tiff_lzw"},
    )
    with Image.open(tiff_path) as image:
        image.convert("RGB").save(tiff_path, compression="tiff_lzw", dpi=(600, 600))
    plt.close(fig)
    print(f"  wrote {out_dir / 'fig_architecture'}.{{png,pdf,tiff}}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "build" / "figures",
        help="Output directory for fig_architecture.png, .pdf, and .tiff.",
    )
    args = parser.parse_args()
    render(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
