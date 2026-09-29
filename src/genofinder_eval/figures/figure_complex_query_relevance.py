"""Render the blinded relevance comparison (Figure 3 of the manuscript).

Panel A shows how many of the 60 queries returned at least one GEO Series, panel B mean
nDCG@10, and panel C strict Success@10, where a hit must meet every required condition. Values
and 95% bootstrap intervals are read from results/complex_query_evaluation_v1/derived/, so the
figure always matches the committed tables. The command-line entry point writes PNG, PDF, and
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
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DERIVED = ROOT / "results" / "complex_query_evaluation_v1" / "derived"

SYSTEMS = ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo")
LABELS = ("OmicsPlorer", "NCBI GEO", "OmicsDI")
COLORS = ("#0072B2", "#6E7781", "#D55E00")
TEXT = "#263238"


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
    query_counts = {int(row["n_queries"]) for row in nonempty + ndcg + strict}
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
    )


def _panel_label(axis: Axes, label: str) -> None:
    axis.text(
        -0.12,
        1.08,
        label,
        transform=axis.transAxes,
        fontsize=15,
        fontweight="bold",
        va="top",
    )


def _style(axis: Axes) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", color="#D9DEE3", linewidth=0.8, alpha=0.8)
    axis.set_axisbelow(True)
    axis.tick_params(axis="x", labelrotation=18)


def _ci_bars(axis: Axes, estimates: tuple[Estimate, ...], *, title: str, ylabel: str) -> None:
    x = np.arange(len(SYSTEMS))
    means = [estimate.mean for estimate in estimates]
    errors = np.array(
        [
            [estimate.mean - estimate.low for estimate in estimates],
            [estimate.high - estimate.mean for estimate in estimates],
        ]
    )
    bars = axis.bar(
        x,
        means,
        width=0.68,
        color=COLORS,
        edgecolor="white",
        linewidth=0.8,
        yerr=errors,
        capsize=4,
        error_kw={"elinewidth": 1.2, "capthick": 1.2, "ecolor": TEXT},
    )
    axis.set_xticks(x, LABELS)
    axis.set_ylim(0, 1.08)
    axis.set_ylabel(ylabel)
    axis.set_title(title, fontsize=11.5, fontweight="bold")
    # Labels sit above the upper confidence limit so they never touch the error bar.
    for bar, estimate in zip(bars, estimates, strict=True):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            min(1.03, estimate.high + 0.03),
            f"{estimate.mean:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )
    _style(axis)


def render(out_dir: Path | None = None, derived_dir: Path = DEFAULT_DERIVED) -> PanelValues:
    values = load_panel_values(derived_dir)
    out_dir = out_dir or ROOT / "build" / "complex_query_evaluation_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    plt.rcdefaults()
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.labelcolor": TEXT,
            "xtick.color": TEXT,
            "ytick.color": TEXT,
            "text.color": TEXT,
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.25))

    x = np.arange(len(SYSTEMS))
    bars = axes[0].bar(
        x, values.nonempty_fraction, width=0.68, color=COLORS, edgecolor="white", linewidth=0.8
    )
    axes[0].set_xticks(x, LABELS)
    axes[0].set_ylim(0, 1.08)
    axes[0].set_ylabel(f"Fraction of {values.n_queries} queries")
    axes[0].set_title("Queries with ≥1 result", fontsize=11.5, fontweight="bold")
    for bar, count in zip(bars, values.nonempty_queries, strict=True):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            min(1.03, bar.get_height() + 0.04),
            f"{count}/{values.n_queries}",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )
    _style(axes[0])
    _panel_label(axes[0], "A")

    _ci_bars(axes[1], values.ndcg_at_10, title="Graded relevance ranking", ylabel="Mean nDCG@10")
    _panel_label(axes[1], "B")
    _ci_bars(
        axes[2], values.strict_success_at_10, title="Strict condition success", ylabel="Success@10"
    )
    _panel_label(axes[2], "C")

    # GPB: figure titles and legends belong in the manuscript, not in the image.
    fig.subplots_adjust(left=0.065, right=0.99, top=0.88, bottom=0.18, wspace=0.34)

    stem = out_dir / "fig_complex_query_relevance"
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(
        stem.with_suffix(".pdf"),
        bbox_inches="tight",
        facecolor="white",
        metadata={"CreationDate": None, "ModDate": None},
    )
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=600, bbox_inches="tight", facecolor="white")
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
