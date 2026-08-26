"""Production browser tail-latency figure — raw measurements required.

The previous implementation embedded ten warm API measurements in source code and
labelled them "all interactive (≈1 s)".  That cannot represent user-perceived page
loading.  This renderer accepts only the summary produced by
``genofinder_eval.external.browser_latency`` and emphasizes p95/p99/max plus failure
rate.  It deliberately has no fallback constants.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

COLORS = {"p50_ms": "#94a3b8", "p95_ms": "#0d9488", "p99_ms": "#f59e0b"}
LABELS = {
    "search_first_result_ms": "Search: first result visible",
    "search_settled_ms": "Search: page settled",
    "ai_pick_cache_hit_ms": "AI Pick: cache hit",
    "ai_pick_cache_miss_ms": "AI Pick: cache miss",
    "ai_pick_forced_refresh_ms": "AI Pick: forced refresh",
    "ai_pick_ms": "AI Pick: not available",
}


def _load(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Measured browser summary is required: {path}. "
            "Run genofinder_eval.external.browser_latency against the production URL first."
        )
    frame = pd.read_csv(path)
    required = {
        "metric", "n", "n_success", "n_timeout", "n_error", "success_rate",
        "p50_ms", "p95_ms", "p99_ms", "max_ms",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Browser summary is missing columns: {missing}")
    frame = frame[frame["n"] > 0].copy()
    if frame.empty:
        raise ValueError("Browser summary has no observations")
    return frame


def render(summary_csv: Path, out_dir: Path | None = None) -> None:
    frame = _load(summary_csv)
    out_dir = out_dir or Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = list(frame["metric"])
    y_positions = list(range(len(metrics)))
    bar_height = 0.22
    fig_height = max(5.4, 1.4 * len(metrics) + 2.6)
    fig, ax = plt.subplots(figsize=(10.2, fig_height))

    for offset, column in zip((-bar_height, 0.0, bar_height), COLORS, strict=True):
        seconds = frame[column].astype(float) / 1000.0
        ax.barh(
            [position + offset for position in y_positions],
            seconds,
            height=bar_height * 0.88,
            color=COLORS[column],
            label=column.replace("_ms", "").upper(),
        )
        largest_bar = max(float(frame[name].max()) for name in COLORS) / 1000.0
        for position, value in zip(y_positions, seconds, strict=True):
            if not math.isnan(value):
                place_outside = value < largest_bar * 0.08
                ax.annotate(
                    f"{value:.1f}s",
                    (value, position + offset),
                    xytext=(5 if place_outside else -5, 0),
                    textcoords="offset points",
                    ha="left" if place_outside else "right",
                    va="center",
                    fontsize=9,
                    color="#172033" if place_outside or column == "p50_ms" else "white",
                    fontweight="bold",
                )

    max_seconds = frame["max_ms"].astype(float) / 1000.0
    ax.scatter(max_seconds, y_positions, marker="x", s=55, color="#b91c1c", label="Observed max")
    ax.set_yticks(y_positions)
    tick_labels = []
    for metric, (_, row) in zip(metrics, frame.iterrows(), strict=True):
        failed = int(row["n_timeout"]) + int(row["n_error"])
        failure_rate = (1 - float(row["success_rate"])) * 100
        tick_labels.append(
            f"{LABELS.get(metric, metric)}\n"
            f"n={int(row['n'])}; failures={failed} ({failure_rate:.1f}%)"
        )
    ax.set_yticklabels(tick_labels)
    ax.invert_yaxis()
    ax.set_xlabel("Production browser click-to-render latency (seconds)")
    ax.set_title(
        "User-perceived tail latency\n"
        "P95/P99 and failures are primary; API-internal time is not substituted",
        fontsize=15,
        fontweight="bold",
    )
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    largest = max(float(frame[column].max()) for column in (*COLORS, "max_ms")) / 1000.0
    ax.set_xlim(0, largest * 1.10)
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        frameon=False,
        ncol=4,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.055),
    )

    if int(frame["n"].max()) < 100:
        fig.text(
            0.01,
            0.01,
            "Caution: fewer than 100 observations; P99 is an observed quantile, not an SLA estimate.",
            fontsize=8.5,
            color="#b45309",
        )
    fig.tight_layout(rect=(0, 0.14, 1, 0.95))

    for suffix in ("png", "pdf"):
        fig.savefig(
            out_dir / f"fig_latency_by_type.{suffix}",
            dpi=300,
            bbox_inches="tight",
            metadata={"Title": "Production browser tail latency", "Subject": str(summary_csv)},
        )
    plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    render(args.summary, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
