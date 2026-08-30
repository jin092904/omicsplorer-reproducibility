"""Render the frozen intersection-corpus identity audit from a public aggregate.

The figure reports row counts and cross-store identity consistency only. It does not
measure metadata accuracy, source completeness, or retrieval effectiveness.

The command-line entry point writes to build/corpus_identity_audit_v1 by default.
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
from matplotlib.patches import FancyBboxPatch

TEAL = "#0d9488"
BLUE = "#2563eb"
AMBER = "#d97706"
SLATE = "#64748b"
PALE_TEAL = "#ccfbf1"
PALE_AMBER = "#fef3c7"
INK = "#1c1917"
GRID = "#d6d3d1"

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


def _box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    *,
    facecolor: str,
    edgecolor: str,
    fontsize: float = 11,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=1.4,
        edgecolor=edgecolor,
        facecolor=facecolor,
        transform=ax.transAxes,
    )
    ax.add_patch(patch)
    ax.text(
        x + width / 2,
        y + height / 2,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=INK,
        fontweight="bold",
        linespacing=1.25,
    )


def render(out_dir: Path | None = None, summary_path: Path = DEFAULT_SUMMARY) -> None:
    summary = load_summary(summary_path)
    counts = summary["counts"]
    retained = counts["retained_rows"]
    mismatch_counts = summary["mismatch_counts"]
    source_counts = {item["source"]: item["rows"] for item in summary["sources"]}
    sources = [(source, source_counts[source]) for source in ("SRA", "GEO", "GDC")]

    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 11,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
        }
    )
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(11.2, 4.8), gridspec_kw={"width_ratios": [1.12, 1]}
    )

    ax_left.set_axis_off()
    ax_left.set_title(
        "A  Frozen intersection and identity audit",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    _box(
        ax_left,
        0.02,
        0.65,
        0.37,
        0.18,
        f"Isolated snapshot\n{counts['isolated_rows']:,} rows",
        facecolor="#f8fafc",
        edgecolor=SLATE,
    )
    _box(
        ax_left,
        0.61,
        0.65,
        0.37,
        0.18,
        f"Frozen intersection\n{retained:,} rows",
        facecolor=PALE_TEAL,
        edgecolor=TEAL,
    )
    ax_left.annotate(
        "",
        xy=(0.59, 0.74),
        xytext=(0.41, 0.74),
        xycoords="axes fraction",
        arrowprops={"arrowstyle": "-|>", "color": SLATE, "lw": 1.8},
    )
    ax_left.text(
        0.50,
        0.87,
        f"exclude {counts['excluded_rows']:,}",
        transform=ax_left.transAxes,
        ha="center",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color=AMBER,
    )
    ax_left.text(
        0.50,
        0.56,
        "not present consistently\nin all three stores",
        transform=ax_left.transAxes,
        ha="center",
        va="center",
        fontsize=9,
        color=SLATE,
        linespacing=1.2,
    )

    store_text = "   ·   ".join(item["store"] for item in summary["stores"])
    _box(
        ax_left,
        0.08,
        0.34,
        0.84,
        0.14,
        f"{store_text}\n{retained:,} dataset IDs in each store",
        facecolor="#eff6ff",
        edgecolor=BLUE,
        fontsize=10.5,
    )
    _box(
        ax_left,
        0.07,
        0.10,
        0.86,
        0.13,
        f"Dataset-ID mismatches: {mismatch_counts['dataset_id']:,}\n"
        "Source-accession membership mismatches: "
        f"{mismatch_counts['source_accession_membership']:,}",
        facecolor=PALE_AMBER,
        edgecolor=AMBER,
        fontsize=9.2,
    )

    labels = [source for source, _ in sources]
    values = [value for _, value in sources]
    y = list(range(len(sources)))
    bars = ax_right.barh(
        y,
        values,
        0.58,
        color=[TEAL, BLUE, AMBER],
        edgecolor="white",
        linewidth=0.7,
    )
    for bar, value in zip(bars, values, strict=True):
        pct = 100 * value / retained
        pct_text = f"{pct:.3f}%" if pct < 0.1 else f"{pct:.1f}%"
        ax_right.annotate(
            f"{value:,}  ({pct_text})",
            (value, bar.get_y() + bar.get_height() / 2),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color=INK,
        )
    ax_right.set_yticks(y)
    ax_right.set_yticklabels(labels)
    ax_right.invert_yaxis()
    ax_right.set_xlim(0, max(values) * 1.34)
    ax_right.set_xlabel("rows in frozen intersection")
    ax_right.set_title(
        "B  Source composition", loc="left", fontsize=13, fontweight="bold", pad=12
    )
    ax_right.grid(axis="x", alpha=0.45, color=GRID)
    ax_right.set_axisbelow(True)
    ax_right.spines["top"].set_visible(False)
    ax_right.spines["right"].set_visible(False)
    ax_right.text(
        0.02,
        0.05,
        "K-BDS was not included in this candidate.",
        transform=ax_right.transAxes,
        fontsize=9.2,
        color=SLATE,
    )

    fig.suptitle(
        "Frozen corpus candidate — cross-store identity consistency",
        fontsize=15,
        fontweight="bold",
        y=1.02,
    )
    fig.text(
        0.5,
        -0.015,
        "Scope: identifier consistency under the recorded intersection rule; not metadata accuracy, source completeness, or retrieval effectiveness.",
        ha="center",
        va="top",
        fontsize=9.2,
        color=SLATE,
    )
    fig.savefig(out_dir / "fig_corpus_overview.png", dpi=300, bbox_inches="tight")
    fig.savefig(out_dir / "fig_corpus_overview.pdf", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / 'fig_corpus_overview'}.{{png,pdf}}")


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
        help="Output directory for fig_corpus_overview.png and .pdf.",
    )
    args = parser.parse_args()
    render(args.out_dir, args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
