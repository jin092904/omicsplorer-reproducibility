"""Render objective known-item retrieval metrics with pilot caveat."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

NAMES = {"omicsplorer_geo": "OmicsPlorer", "ncbi_geo": "NCBI GEO", "omicsdi_geo": "OmicsDI"}
COLORS = {"omicsplorer_geo": "#0d9488", "ncbi_geo": "#64748b", "omicsdi_geo": "#f59e0b"}


def render(summary_csv: Path, out_dir: Path) -> None:
    frame = pd.read_csv(summary_csv).set_index("system")
    order = [value for value in ("omicsplorer_geo", "ncbi_geo", "omicsdi_geo") if value in frame.index]
    frame = frame.loc[order]
    metrics = ["mrr_at_50", "hit_at_1", "hit_at_5", "hit_at_10", "hit_at_50"]
    labels = ["MRR@50", "Hit@1", "Hit@5", "Hit@10", "Hit@50"]
    x = list(range(len(metrics)))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    for index, system in enumerate(order):
        offset = (index - (len(order) - 1) / 2) * width
        values = [float(frame.loc[system, metric]) for metric in metrics]
        bars = ax.bar(
            [position + offset for position in x],
            values,
            width=width,
            color=COLORS[system],
            label=NAMES[system],
        )
        ax.bar_label(bars, labels=[f"{value:.2f}" for value in values], fontsize=8, padding=2)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Score / hit fraction")
    ax.set_title(
        "GEO known-item title retrieval (pilot)\n"
        "Target accession removed from query · higher is better",
        fontsize=15,
        fontweight="bold",
    )
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=3, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(
        0.01,
        0.01,
        "Selection frame: accessions seen in both NCBI GEO and OmicsDI pilot pools. "
        "This measures target retrievability, not human topical relevance.",
        fontsize=8.5,
        color="#b45309",
    )
    failure_text = " · ".join(
        f"{NAMES[system]} failures {float(frame.loc[system, 'request_failure_rate'])*100:.0f}%"
        for system in order
    )
    fig.text(0.01, 0.045, failure_text, fontsize=8.5, color="#475569")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    out_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(out_dir / f"fig_known_item.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    render(args.summary, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
