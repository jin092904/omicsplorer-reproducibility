"""Production browser tail latency by preregistered query category."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def render(category_csv: Path, out_dir: Path) -> None:
    if not category_csv.exists():
        raise FileNotFoundError(f"Measured category summary required: {category_csv}")
    frame = pd.read_csv(category_csv)
    required = {"category", "metric", "n", "p50_ms", "p95_ms", "p99_ms", "max_ms"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Category summary missing columns: {missing}")
    frame = frame[frame["metric"] == "search_first_result_ms"].copy()
    if frame.empty:
        raise ValueError("No search_first_result_ms category rows")
    frame = frame.sort_values("p95_ms")
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9.2, max(4.8, 0.9 * len(frame) + 2.2)))
    positions = list(range(len(frame)))
    p50 = frame["p50_ms"].astype(float) / 1000
    p95 = frame["p95_ms"].astype(float) / 1000
    p99 = frame["p99_ms"].astype(float) / 1000
    maximum = frame["max_ms"].astype(float) / 1000

    for position, low, high in zip(positions, p50, p95, strict=True):
        ax.plot([low, high], [position, position], color="#94a3b8", linewidth=5, solid_capstyle="round")
    ax.scatter(p50, positions, s=55, color="#334155", label="P50", zorder=3)
    ax.scatter(p95, positions, s=70, color="#0d9488", label="P95", zorder=3)
    ax.scatter(p99, positions, s=70, color="#f59e0b", marker="D", label="P99", zorder=3)
    ax.scatter(maximum, positions, s=65, color="#b91c1c", marker="x", linewidth=2, label="Observed max")

    last_position = positions[-1]
    for position, (_, row) in zip(positions, frame.iterrows(), strict=True):
        vertical_offset = 12 if position == last_position else -13
        ax.annotate(
            f"P95 {float(row['p95_ms'])/1000:.1f}s · n={int(row['n'])}",
            (float(row["p95_ms"]) / 1000, position),
            xytext=(7, vertical_offset),
            textcoords="offset points",
            fontsize=8.5,
            color="#0f766e",
            va="bottom" if position == last_position else "top",
        )

    ax.set_yticks(positions)
    ax.set_yticklabels([str(value).replace("_", " ").title() for value in frame["category"]])
    ax.invert_yaxis()
    ax.set_xlabel("Production browser click-to-first-result (seconds)")
    ax.set_title("Tail latency by query category", fontsize=15, fontweight="bold", pad=14)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, 0.055))
    if int(frame["n"].min()) < 100:
        fig.text(
            0.01,
            0.01,
            "Category P99 values have <100 observations and are descriptive, not SLA estimates.",
            fontsize=8.5,
            color="#b45309",
        )
    fig.tight_layout(rect=(0, 0.14, 1, 0.95))
    for suffix in ("png", "pdf"):
        fig.savefig(
            out_dir / f"fig_tail_latency_by_category.{suffix}",
            dpi=300,
            bbox_inches="tight",
            metadata={"Title": "Production browser tail latency by query category"},
        )
    plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    render(args.summary, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
