"""Render production Sol4 shadow tail latency and safety outcomes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

LABELS = {
    "dataset_total_ms": "Dataset total",
    "llm_ms": "Gemma extraction",
    "normalization_merge_ms": "OLS4 + safe merge",
    "sample_fetch_ms": "Sample metadata fetch",
    "candidate_count_ms": "Candidate pool count",
    "candidate_select_ms": "Priority selection",
}


def render(data_dir: Path, out_dir: Path) -> None:
    frame = pd.read_csv(data_dir / "sol4_stage_summary.csv")
    summary = json.loads((data_dir / "sol4_run_summary.json").read_text(encoding="utf-8"))
    order = [value for value in LABELS if value in set(frame["stage"])]
    frame = frame.set_index("stage").loc[order].reset_index()

    fig, (ax, info) = plt.subplots(1, 2, figsize=(13, 6.5), gridspec_kw={"width_ratios": [2.1, 1]})
    y = range(len(frame))
    for offset, field, color, label in (
        (-0.18, "p50_ms", "#94a3b8", "P50"),
        (0.0, "p95_ms", "#0d9488", "P95"),
        (0.18, "max_ms", "#b91c1c", "Observed max"),
    ):
        values = frame[field].astype(float) / 1000
        ax.barh([value + offset for value in y], values, height=0.16, color=color, label=label)
    for position, (_, row) in enumerate(frame.iterrows()):
        ax.text(
            float(row["max_ms"]) / 1000 + 0.35,
            position,
            f"P95 {float(row['p95_ms'])/1000:.1f}s",
            va="center",
            fontsize=8.5,
            color="#0f766e",
        )
    ax.set_yticks(list(y), [f"{LABELS[value]}\n(n={int(n)})" for value, n in zip(frame["stage"], frame["n"], strict=True)])
    ax.invert_yaxis()
    ax.set_xlabel("Production shadow-run latency (seconds)")
    ax.set_title("A. Tail latency by pipeline stage")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)

    info.axis("off")
    changed_rate = summary["n_changed"] / summary["n_datasets"] * 100
    info.text(0.02, 0.90, "B. Safety and yield", fontsize=14, fontweight="bold")
    lines = [
        f"Mode: {summary['mode']} (DB writes: {summary['database_writes']})",
        f"Model: {summary['model']}",
        f"Datasets: {summary['n_datasets']}",
        f"Would change: {summary['n_changed']} ({changed_rate:.0f}%)",
        f"Errors: {summary['n_errors']}",
        f"New CURIEs proposed: {summary['new_curies_total']}",
        f"Observed throughput: {summary['throughput_per_hour']:.1f}/hour",
        "Safe merge policy: never-shrink",
    ]
    info.text(0.02, 0.78, "\n\n".join(lines), va="top", fontsize=11.5)
    info.text(
        0.02,
        0.06,
        "Pilot n=10. P95/max are descriptive, not an SLA.\n"
        "Shadow mode executes LLM + OLS4 + merge diff, but commits no dataset changes.",
        fontsize=9,
        color="#b45309",
    )
    fig.suptitle("LLM self-healing enrichment — measured production shadow run", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(out_dir / f"fig_sol4_shadow.{suffix}", dpi=300, bbox_inches="tight")
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
