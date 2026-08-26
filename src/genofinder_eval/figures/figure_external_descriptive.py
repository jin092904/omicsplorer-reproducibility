"""Render objective external-search descriptors; never label them relevance quality."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

NAMES = {"omicsplorer_geo": "OmicsPlorer", "ncbi_geo": "NCBI GEO", "omicsdi_geo": "OmicsDI"}
COLORS = {"omicsplorer_geo": "#0d9488", "ncbi_geo": "#64748b", "omicsdi_geo": "#f59e0b"}


def render(data_dir: Path, out_dir: Path) -> None:
    systems = pd.read_csv(data_dir / "descriptive_systems.csv")
    overlap = pd.read_csv(data_dir / "descriptive_overlap.csv")
    completeness = pd.read_csv(data_dir / "descriptive_completeness.csv")
    exclusive = pd.read_csv(data_dir / "descriptive_exclusive.csv")
    preferred = ["omicsplorer_geo", "ncbi_geo", "omicsdi_geo"]
    order = [value for value in preferred if value in set(systems["system"])]
    systems = systems.set_index("system").loc[order].reset_index()
    labels = [NAMES.get(value, value) for value in order]
    colors = [COLORS.get(value, "#94a3b8") for value in order]

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    ax = axes[0, 0]
    values = systems["zero_result_rate"].astype(float) * 100
    ax.bar(labels, values, color=colors)
    for index, (value, returned) in enumerate(zip(values, systems["mean_returned"], strict=True)):
        ax.text(index, value + 1, f"{value:.0f}%\nmean returned {returned:.1f}", ha="center", fontsize=9)
    ax.set_ylabel("Queries with zero results (%)")
    ax.set_title("A. Retrieval availability (30 pilot queries)")
    ax.set_ylim(0, max(10, float(values.max()) * 1.28))

    ax = axes[0, 1]
    matrix = np.eye(len(order))
    for _, row in overlap.iterrows():
        i, j = order.index(row["system_a"]), order.index(row["system_b"])
        matrix[i, j] = matrix[j, i] = row["mean_jaccard_at_10"]
    image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(order)), labels, rotation=25, ha="right")
    ax.set_yticks(range(len(order)), labels)
    for i in range(len(order)):
        for j in range(len(order)):
            ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center")
    ax.set_title("B. Mean top-10 accession Jaccard")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)

    ax = axes[1, 0]
    pivot = completeness.pivot(index="field", columns="system", values="completeness").reindex(columns=order)
    image = ax.imshow(pivot.values * 100, cmap="YlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(order)), labels, rotation=25, ha="right")
    ax.set_yticks(range(len(pivot.index)), [value.replace("_", " ").title() for value in pivot.index])
    for i in range(len(pivot.index)):
        for j in range(len(order)):
            ax.text(j, i, f"{pivot.iloc[i, j]*100:.0f}%", ha="center", va="center", fontsize=9)
    ax.set_title("C. Returned-hit metadata completeness")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="Present (%)")

    ax = axes[1, 1]
    exclusive = exclusive.set_index("system").reindex(order).reset_index()
    values = exclusive["exclusive_share"].astype(float) * 100
    ax.bar(labels, values, color=colors)
    for index, (_, row) in enumerate(exclusive.iterrows()):
        ax.text(index, values.iloc[index] + 1, f"{values.iloc[index]:.0f}%\n{int(row['exclusive_hits'])} hits", ha="center", fontsize=9)
    ax.set_ylabel("Share not returned by either comparator (%)")
    ax.set_title("D. Unique discovery contribution")
    ax.set_ylim(0, max(10, float(values.max()) * 1.28))

    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "External GEO search: descriptive discovery profile\n"
        "Same free-text queries and GEO corpus · no relevance judgments · not a quality ranking",
        fontsize=16,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.92))
    out_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(out_dir / f"fig_external_descriptive.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    render(args.data_dir, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
