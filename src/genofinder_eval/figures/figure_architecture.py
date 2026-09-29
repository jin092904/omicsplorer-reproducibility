"""Render the OmicsPlorer lifecycle diagram (Figure 1 of the manuscript).

The four stages are harvest, model-assisted structuring, indexing, and search. The banner
repeats the scope of the corpus identity audit. The command-line entry point writes PNG, PDF,
and a 600-dpi RGB TIFF to build/figures by default.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image

TEAL = "#0d9488"
TEAL_BG = "#d7f0ec"
AMBER = "#f59e0b"
SLATE = "#475569"
INK = "#1c1917"
CARD = "#f8fafc"
BORDER = "#94a3b8"

ROOT = Path(__file__).resolve().parents[3]

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
        "accession + ranking evidence",
        "cohort summary + reuse commands",
    ]),
]


def render(out_dir: Path | None = None) -> None:
    out_dir = out_dir or ROOT / "build" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcdefaults()
    plt.rcParams.update({"font.size": 11, "text.color": INK})

    fig, ax = plt.subplots(figsize=(12, 4.6))
    # Full-width axes with a small margin so rounded card padding and the banner text are not clipped.
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    ax.set_xlim(-1.5, 101.5)
    ax.set_ylim(0, 88)
    ax.axis("off")

    n = len(STAGES)
    gap = 2.0
    box_w = (100 - gap * (n - 1)) / n
    box_h = 64
    y0 = 20
    edges = []
    for i, (title, subtitle, items) in enumerate(STAGES):
        x = i * (box_w + gap)
        ax.add_patch(FancyBboxPatch((x, y0), box_w, box_h,
                     boxstyle="round,pad=0.6,rounding_size=2.5",
                     linewidth=1.4, edgecolor=BORDER, facecolor=CARD, zorder=2))
        # Header strip
        ax.add_patch(FancyBboxPatch((x, y0 + box_h - 13), box_w, 13,
                     boxstyle="round,pad=0.6,rounding_size=2.5",
                     linewidth=0, facecolor=TEAL, zorder=3))
        ax.text(x + box_w / 2, y0 + box_h - 6.5, title, ha="center", va="center",
                fontsize=12.5, fontweight="bold", color="white", zorder=4)
        ax.text(x + box_w / 2, y0 + box_h - 18, subtitle, ha="center", va="center",
                fontsize=9.5, color=SLATE, style="italic", zorder=4)
        for j, item in enumerate(items):
            ax.text(x + box_w / 2, y0 + box_h - 27 - j * 8.0, item, ha="center", va="center",
                    fontsize=9.1, color=INK, zorder=4)
        edges.append((x + box_w, x))

    for i in range(n - 1):
        ax.add_patch(FancyArrowPatch((edges[i][0] + 0.1, y0 + box_h / 2),
                     (edges[i + 1][1] - 0.1, y0 + box_h / 2),
                     arrowstyle="-|>", mutation_scale=20, linewidth=2.2,
                     color=AMBER, zorder=5))

    ax.add_patch(FancyBboxPatch((0, 2), 100, 11,
                 boxstyle="round,pad=0.4,rounding_size=2", linewidth=0,
                 facecolor=TEAL_BG, zorder=1))
    ax.text(50, 7.5,
            "634,485-row intersection  ·  cross-store ID mismatches: 0  ·  metadata accuracy not assessed  ·  EN/KO queries",
            ha="center", va="center", fontsize=11, color="#0f5f57", fontweight="bold", zorder=2)

    # GPB: figure titles and legends belong in the manuscript, not in the image.
    fig.savefig(out_dir / "fig_architecture.png", dpi=300, bbox_inches="tight")
    fig.savefig(
        out_dir / "fig_architecture.pdf",
        dpi=300,
        bbox_inches="tight",
        metadata={"CreationDate": None, "ModDate": None},
    )
    tiff_path = out_dir / "fig_architecture.tiff"
    fig.savefig(
        tiff_path,
        dpi=600,
        bbox_inches="tight",
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
