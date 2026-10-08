"""Render the blinded relevance comparison (Figure 3 of the manuscript).

Panel A shows what filled each system's ten result slots per query: graded relevant candidates,
candidates graded not relevant, and slots left empty because the system returned fewer than ten
results. Panel B shows mean nDCG@10 and panel C strict Success@10, where a hit must meet every
required condition. Values and 95% bootstrap intervals are read from
results/complex_query_evaluation_v1/derived/, so the figure always matches the committed tables. The command-line entry point writes PNG, PDF, and
a 600-dpi RGB TIFF to build/complex_query_evaluation_v1 by default.
"""
from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import MultipleLocator
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DERIVED = ROOT / "results" / "complex_query_evaluation_v1" / "derived"

SYSTEMS = ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")
LABELS = ("OmicsPlorer", "NCBI GEO", "OmicsDI")
COLORS = ("#0072B2", "#6E7781", "#D55E00")


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float


@dataclass(frozen=True)
class PanelValues:
    n_queries: int
    nonempty_queries: tuple[int, ...]
    nonempty_fraction: tuple[float, ...]
    ndcg_at_10: tuple[Estimate, ...]
    strict_success_at_10: tuple[Estimate, ...]
    # Per-query means of grade-3, grade-2, and grade-0/1 candidates in each system's top 10.
    slot_composition: tuple[tuple[float, float, float], ...]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _rows(table: list[dict[str, str]], metric: str) -> list[dict[str, str]]:
    rows = []
    for system in SYSTEMS:
        matches = [row for row in table if row["system"] == system and row["metric"] == metric]
        if len(matches) != 1:
            raise ValueError(f"expected one row for {system}/{metric}, found {len(matches)}")
        rows.append(matches[0])
    return rows


def _estimates(rows: list[dict[str, str]]) -> tuple[Estimate, ...]:
    return tuple(
        Estimate(float(row["mean"]), float(row["ci95_low"]), float(row["ci95_high"]))
        for row in rows
    )


def load_panel_values(derived_dir: Path = DEFAULT_DERIVED) -> PanelValues:
    nonempty = _rows(_read(derived_dir / "response_availability_summary.csv"), "nonempty_response")
    ndcg = _rows(_read(derived_dir / "metrics_summary.csv"), "ndcg_at_10")
    strict = _rows(
        _read(derived_dir / "condition_metrics_summary.csv"),
        "strict_all_conditions_success_at_10",
    )
    yield_rows = [
        row
        for row in _read(derived_dir / "posthoc_returned_candidate_yield.csv")
        if row["scope"] == "all"
    ]
    yields = []
    for system in SYSTEMS:
        matches = [row for row in yield_rows if row["system"] == system]
        if len(matches) != 1:
            raise ValueError(f"expected one candidate-yield row for {system}, found {len(matches)}")
        yields.append(matches[0])
    query_counts = {int(row["n_queries"]) for row in nonempty + ndcg + strict + yields}
    if len(query_counts) != 1:
        raise ValueError(f"panels use different query counts: {sorted(query_counts)}")
    n_queries = query_counts.pop()
    fractions = tuple(float(row["mean"]) for row in nonempty)
    return PanelValues(
        n_queries=n_queries,
        nonempty_queries=tuple(round(fraction * n_queries) for fraction in fractions),
        nonempty_fraction=fractions,
        ndcg_at_10=_estimates(ndcg),
        strict_success_at_10=_estimates(strict),
        slot_composition=tuple(_slot_composition(row, n_queries) for row in yields),
    )


def _slot_composition(row: dict[str, str], n_queries: int) -> tuple[float, float, float]:
    returned = int(row["returned_candidates"])
    relevant = int(row["relevant_candidates"])
    grade3 = int(row["grade3_candidates"])
    if not 0 <= grade3 <= relevant <= returned <= 10 * n_queries:
        raise ValueError(f"inconsistent candidate counts for {row['system']}")
    return (
        grade3 / n_queries,
        (relevant - grade3) / n_queries,
        (returned - relevant) / n_queries,
    )


# ggplot2 theme_gray colours, so the three manuscript figures share one look.
PANEL = "#EBEBEB"  # panel background (grey92)
STRIP = "#D9D9D9"  # facet strip (grey85)
INK = "#1A1A1A"  # grey10
AXIS_TEXT = "#4D4D4D"  # grey30
TICK = "#333333"  # grey20


def _gg_axes(axis: Axes) -> None:
    axis.set_facecolor(PANEL)
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.grid(axis="y", which="major", color="white", linewidth=0.6)
    axis.grid(axis="y", which="minor", color="white", linewidth=0.3)
    axis.yaxis.set_minor_locator(MultipleLocator(0.1))
    axis.set_axisbelow(True)
    axis.tick_params(colors=TICK, labelcolor=AXIS_TEXT, length=2.5, width=0.5, labelsize=6.3)
    axis.tick_params(which="minor", length=0)
    axis.tick_params(axis="x", length=0)


def _strip(axis: Axes, title: str, label: str) -> None:
    """Draw a facet strip above the panel with the panel letter to its left."""
    axis.add_patch(Rectangle((0, 1.0), 1, 0.11, transform=axis.transAxes, facecolor=STRIP,
                             linewidth=0, clip_on=False))
    axis.text(0.5, 1.055, title, transform=axis.transAxes, ha="center", va="center",
              fontsize=7, color=INK)
    axis.text(-0.2, 1.055, label, transform=axis.transAxes, ha="left", va="center",
              fontsize=9, fontweight="bold", color=INK)


def _bars(
    axis: Axes,
    means: list[float],
    labels: list[str],
    lows: list[float] | None = None,
    highs: list[float] | None = None,
) -> None:
    x = np.arange(len(SYSTEMS))
    yerr = None
    if lows is not None and highs is not None:
        yerr = np.array(
            [
                [mean - low for mean, low in zip(means, lows, strict=True)],
                [high - mean for mean, high in zip(means, highs, strict=True)],
            ]
        )
    axis.bar(
        x,
        means,
        width=0.7,
        color=COLORS,
        zorder=3,
        yerr=yerr,
        capsize=2.5,
        error_kw={"elinewidth": 0.7, "capthick": 0.7, "ecolor": TICK},
    )
    # Labels sit above the upper confidence limit so they never touch the error bar.
    tops = highs if highs is not None else means
    for position, top, label in zip(x, tops, labels, strict=True):
        axis.text(position, min(1.02, top + 0.03), label, ha="center", va="bottom",
                  fontsize=6.3, color=INK)
    axis.set_xticks(x, LABELS)
    axis.set_ylim(0, 1.08)
    axis.set_xlim(-0.6, 2.6)


# Panel A shades: graded relevant (2–3) in blues, not relevant (0–1) in grey; an unfilled slot is
# shown only by the dashed outline of the ten-slot list.
SLOT_SEGMENTS = (
    ("Highly relevant (grade 3)", "#08519C"),
    ("Relevant (grade 2)", "#6BAED6"),
    ("Not relevant (grade 0–1)", "#BDBDBD"),
)
SLOT_OUTLINE = "#7F7F7F"


def _slots(axis: Axes, composition: list[tuple[float, float, float]]) -> None:
    """Stack the per-query mean of each grade class inside a dashed ten-slot outline."""
    x = np.arange(len(SYSTEMS))
    for position, segments in zip(x, composition, strict=True):
        bottom = 0.0
        for (_, colour), value in zip(SLOT_SEGMENTS, segments, strict=True):
            axis.bar(position, value, 0.62, bottom=bottom, color=colour, zorder=3)
            bottom += value
        axis.add_patch(Rectangle((position - 0.31, 0), 0.62, 10, fill=False,
                                 edgecolor=SLOT_OUTLINE, linewidth=0.6,
                                 linestyle=(0, (2, 2)), zorder=4))
        axis.text(position, 10.25, f"{segments[0] + segments[1]:.1f}", ha="center",
                  va="bottom", fontsize=6.3, color=SLOT_SEGMENTS[0][1], fontweight="bold")
    axis.set_xticks(x, LABELS)
    axis.set_ylim(0, 11.6)
    axis.set_xlim(-0.6, 2.6)
    axis.set_yticks([0, 2, 4, 6, 8, 10])
    axis.yaxis.set_minor_locator(MultipleLocator(1))


def _slot_legend(fig: Figure) -> None:
    handles = [Patch(color=colour, label=label) for label, colour in SLOT_SEGMENTS]
    handles.append(Patch(facecolor="none", edgecolor=SLOT_OUTLINE, linestyle=(0, (2, 2)),
                         label="Slot not filled"))
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=6,
               bbox_to_anchor=(0.5, 0.0), handlelength=1.4)


def render(out_dir: Path | None = None, derived_dir: Path = DEFAULT_DERIVED) -> PanelValues:
    values = load_panel_values(derived_dir)
    out_dir = out_dir or ROOT / "build" / "complex_query_evaluation_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    def series(estimates: tuple[Estimate, ...]) -> tuple[list[float], ...]:
        return tuple(
            [getattr(item, name) for item in estimates] for name in ("mean", "low", "high")
        )

    ndcg = series(values.ndcg_at_10)
    strict = series(values.strict_success_at_10)
    slots = list(values.slot_composition)

    plt.rcdefaults()
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7, "text.color": INK})
    # 7.1 in (about 18 cm) is the full text width, so printed text stays at 6–8 pt.
    fig, axes = plt.subplots(1, 3, figsize=(7.1, 2.9))
    fig.subplots_adjust(left=0.075, right=0.975, top=0.86, bottom=0.24, wspace=0.34)
    for axis in axes:
        _gg_axes(axis)

    _slots(axes[0], slots)
    axes[0].set_ylabel("Candidates per query (top 10)", fontsize=7, color=INK)
    _strip(axes[0], "What the 10 slots contained", "A")

    _bars(axes[1], ndcg[0], [f"{mean:.3f}" for mean in ndcg[0]], ndcg[1], ndcg[2])
    axes[1].set_ylabel("Mean nDCG@10", fontsize=7, color=INK)
    _strip(axes[1], "Graded relevance ranking", "B")

    _bars(axes[2], strict[0], [f"{mean:.3f}" for mean in strict[0]], strict[1], strict[2])
    axes[2].set_ylabel("Strict Success@10", fontsize=7, color=INK)
    _strip(axes[2], "Strict condition success", "C")
    _slot_legend(fig)

    # GPB: figure titles and legends belong in the manuscript, not in the image.
    stem = out_dir / "fig_complex_query_relevance"
    fig.savefig(
        stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.06, facecolor="white"
    )
    fig.savefig(
        stem.with_suffix(".pdf"),
        bbox_inches="tight",
        pad_inches=0.06,
        facecolor="white",
        metadata={"CreationDate": None, "ModDate": None},
    )
    buffer = io.BytesIO()
    fig.savefig(
        buffer, format="png", dpi=600, bbox_inches="tight", pad_inches=0.06, facecolor="white"
    )
    plt.close(fig)
    buffer.seek(0)
    with Image.open(buffer) as image:
        image.convert("RGB").save(
            stem.with_suffix(".tiff"), format="TIFF", compression="tiff_lzw", dpi=(600, 600)
        )
    print(f"  wrote {stem}.{{png,pdf,tiff}}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--derived",
        type=Path,
        default=DEFAULT_DERIVED,
        help="Directory with the committed summary tables.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "build" / "complex_query_evaluation_v1",
        help="Output directory for fig_complex_query_relevance.png, .pdf, and .tiff.",
    )
    args = parser.parse_args()
    render(args.out_dir, args.derived)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
