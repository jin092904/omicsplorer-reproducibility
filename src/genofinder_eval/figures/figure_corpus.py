"""Render the frozen intersection-corpus identity audit from a public aggregate.

The figure reports row counts and cross-store identity consistency only. It does not
measure metadata accuracy, source completeness, or retrieval effectiveness.

This is Figure 2 of the manuscript. The command-line entry point writes PNG, PDF, and a
600-dpi RGB TIFF to build/corpus_identity_audit_v1 by default.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypedDict, cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator, NullLocator
from PIL import Image

# ggplot2 theme_gray colours, so the three manuscript figures share one look.
PANEL = "#EBEBEB"  # panel background (grey92)
STRIP = "#D9D9D9"  # facet strip (grey85)
BAR = "#595959"  # geom_col default fill (grey35)
INK = "#1A1A1A"  # grey10
AXIS_TEXT = "#4D4D4D"  # grey30
TICK = "#333333"  # grey20
ARROW = "#4D4D4D"

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUMMARY = (
    ROOT / "results" / "corpus_identity_audit_v1" / "corpus_identity_audit_summary.json"
)


class CorpusCounts(TypedDict):
    isolated_rows: int
    excluded_rows: int
    retained_rows: int


class SourceCount(TypedDict):
    source: str
    rows: int


class StoreCount(TypedDict):
    store: str
    dataset_id_count: int


class MismatchCounts(TypedDict):
    dataset_id: int
    source_accession_membership: int


class CorpusSummary(TypedDict):
    schema_version: str
    candidate_id: str
    snapshot_date: str
    counts: CorpusCounts
    sources: list[SourceCount]
    stores: list[StoreCount]
    mismatch_counts: MismatchCounts


def load_summary(path: Path = DEFAULT_SUMMARY) -> CorpusSummary:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("corpus identity summary must be a JSON object")
    summary = cast(CorpusSummary, raw)
    if summary["schema_version"] != "corpus-identity-audit-summary-v1":
        raise ValueError("unsupported corpus identity summary schema")

    counts = summary["counts"]
    if counts["isolated_rows"] - counts["excluded_rows"] != counts["retained_rows"]:
        raise ValueError("intersection counts do not reconcile")
    if sum(item["rows"] for item in summary["sources"]) != counts["retained_rows"]:
        raise ValueError("source counts do not sum to retained rows")
    if {item["source"] for item in summary["sources"]} != {"SRA", "GEO", "GDC"}:
        raise ValueError("unexpected source set in corpus identity summary")
    if {item["store"] for item in summary["stores"]} != {
        "PostgreSQL",
        "Qdrant",
        "OpenSearch",
    }:
        raise ValueError("unexpected store set in corpus identity summary")
    if any(item["dataset_id_count"] != counts["retained_rows"] for item in summary["stores"]):
        raise ValueError("store dataset-ID counts do not match retained rows")
    if any(value != 0 for value in summary["mismatch_counts"].values()):
        raise ValueError("corpus identity summary reports a nonzero mismatch")
    return summary


def _gg_axes(ax: Axes) -> None:
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(which="major", color="white", linewidth=0.6)
    ax.grid(which="minor", color="white", linewidth=0.3)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TICK, labelcolor=AXIS_TEXT, length=2.5, width=0.5, labelsize=6.5)


def _tag(ax: Axes, letter: str, title: str) -> None:
    ax.text(0, 1.03, letter, transform=ax.transAxes, fontsize=9, fontweight="bold",
            ha="left", va="bottom", color=INK)
    ax.text(0.06, 1.03, title, transform=ax.transAxes, fontsize=7.5, ha="left", va="bottom",
            color=INK)


def _box(
    ax: Axes, x: float, y: float, width: float, height: float, text: str, facecolor: str
) -> None:
    ax.add_patch(Rectangle((x, y), width, height, linewidth=0, facecolor=facecolor, zorder=2))
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=6.8,
            color=INK, linespacing=1.35, zorder=3)


def render(out_dir: Path | None = None, summary_path: Path = DEFAULT_SUMMARY) -> None:
    summary = load_summary(summary_path)
    counts = summary["counts"]
    retained = counts["retained_rows"]
    mismatch_counts = summary["mismatch_counts"]
    source_counts = {item["source"]: item["rows"] for item in summary["sources"]}
    sources = [(source, source_counts[source]) for source in ("SRA", "GEO", "GDC")]

    isolated = counts["isolated_rows"]
    excluded = counts["excluded_rows"]
    stores = [item["store"] for item in summary["stores"]]
    id_mismatches = mismatch_counts["dataset_id"]
    accession_mismatches = mismatch_counts["source_accession_membership"]
    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcdefaults()
    plt.rcParams.update({"font.size": 7, "text.color": INK})
    # 7.1 in (about 18 cm) is the full text width, so printed text stays at 6–8 pt.
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(7.1, 2.7), gridspec_kw={"width_ratios": [1, 1], "wspace": 0.26}
    )
    fig.subplots_adjust(left=0.035, right=0.965, top=0.88, bottom=0.16)

    # Panel A: predeclared common-store intersection rule and identity audit.
    ax_left.set_xlim(0, 100)
    ax_left.set_ylim(0, 100)
    ax_left.set_axis_off()
    _tag(ax_left, "A", "Identity audit across the three stores")
    _box(ax_left, 2, 64, 37, 30, f"Isolated snapshot\n{isolated:,} rows", PANEL)
    _box(ax_left, 61, 64, 37, 30, f"Retained in all\nthree stores\n{retained:,} rows", STRIP)
    ax_left.add_patch(FancyArrowPatch((41, 79), (59, 79), arrowstyle="-|>", mutation_scale=9,
                                      linewidth=1.2, color=ARROW))
    ax_left.text(50, 86, f"−{excluded:,}", ha="center", va="bottom", fontsize=6.8, color=INK)
    ax_left.text(50, 72, "not in all\nthree stores", ha="center", va="top", fontsize=5.8,
                 color=AXIS_TEXT, linespacing=1.2)
    store_text = "  ·  ".join(stores)
    _box(ax_left, 2, 33, 96, 22, f"{store_text}\n{retained:,} dataset IDs in each store", PANEL)
    _box(
        ax_left,
        2,
        2,
        96,
        22,
        f"Dataset-ID mismatches: {id_mismatches:,}\n"
        f"Source-accession membership mismatches: {accession_mismatches:,}",
        STRIP,
    )

    # Panel B: mutually exclusive source rows in the retained derivative.
    _gg_axes(ax_right)
    labels = [source for source, _ in sources]
    values = [value for _, value in sources]
    y = list(range(len(sources)))
    bars = ax_right.barh(y, values, 0.62, color=BAR, zorder=3)
    for bar, value in zip(bars, values, strict=True):
        pct = 100 * value / retained
        pct_text = f"{pct:.3f}%" if pct < 0.1 else f"{pct:.1f}%"
        ax_right.annotate(
            f"{value:,} ({pct_text})",
            (value, bar.get_y() + bar.get_height() / 2),
            xytext=(3, 0),
            textcoords="offset points",
            va="center",
            fontsize=6.5,
            color=INK,
        )
    ax_right.set_yticks(y)
    ax_right.set_yticklabels(labels)
    ax_right.invert_yaxis()
    ax_right.set_xlim(0, 500_000)
    ax_right.xaxis.set_major_locator(MultipleLocator(100_000))
    ax_right.xaxis.set_minor_locator(MultipleLocator(50_000))
    ax_right.yaxis.set_minor_locator(NullLocator())
    ax_right.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{int(value):,}"))
    ax_right.set_xlabel("Rows in the retained corpus", fontsize=7, color=INK, labelpad=3)
    ax_right.grid(axis="y", which="major", color="white", linewidth=0.6)
    ax_right.tick_params(which="minor", length=0)
    _tag(ax_right, "B", "Source composition")

    # GPB: figure titles and legends belong in the manuscript, not in the image.
    fig.savefig(out_dir / "fig_corpus_overview.png", dpi=300, bbox_inches="tight", pad_inches=0.06)
    fig.savefig(
        out_dir / "fig_corpus_overview.pdf",
        dpi=300,
        bbox_inches="tight",
        pad_inches=0.06,
        metadata={"CreationDate": None, "ModDate": None},
    )
    tiff_path = out_dir / "fig_corpus_overview.tiff"
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
    print(f"  wrote {out_dir / 'fig_corpus_overview'}.{{png,pdf,tiff}}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="Public aggregate JSON to validate and render.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "build" / "corpus_identity_audit_v1",
        help="Output directory for fig_corpus_overview.png, .pdf, and .tiff.",
    )
    args = parser.parse_args()
    render(args.out_dir, args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
