"""Historical exploratory hard/balanced aggregate figures.

입력: results/aggregated/{hard,balanced}_queries_results.csv
      (long-form: dataset, mode, lang, axis, metric, mean, median, std, n_queries)
      metric ∈ {facet_present_macro, facet_conjunctive_macro, exclusion_clean_at_k}
      mode   ∈ {bm25_only, dense_only, rrf, rrf_rerank}; lang ∈ {en, ko}

출력 (results/figures/, 300dpi PDF+PNG):
  A. ablation_present       — 4모드별 facet_present_macro (hard vs balanced, EN)
  B. present_vs_conjunctive — hard 축별 present vs conjunctive (rrf_rerank, EN) ★핵심
  C. ko_en_parity           — 4모드별 present_macro EN vs KO (hard)
  D. exclusion_by_axis      — 축별 exclusion_clean_at_k (부정/제외 축, EN vs KO)
  E. gpb_retrieval          — GPB 본문용 A/B composite (ablation + EN/KO)

데이터 없으면 해당 피겨만 조용히 건너뜀(부분 결과에도 동작).
The retained inputs lack per-query outputs and a complete run manifest. Figures therefore describe
historical facet-tag regression aggregates, not relevance, accuracy, or statistical superiority.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.container import BarContainer
from matplotlib.figure import Figure

MODE_ORDER = ["bm25_only", "dense_only", "rrf", "rrf_rerank"]
MODE_LABEL = {
    "bm25_only": "BM25-based",
    "dense_only": "Dense-based",
    "rrf": "RRF",
    "rrf_rerank": "RRF+Rerank",
}

# 사람이 읽기 좋은 축 라벨.
AXIS_LABEL = {
    "abbrev_standard": "Abbrev (standard)",
    "abbrev_ambiguous": "Abbrev (ambiguous)",
    "abbrev_tcga": "Abbrev (TCGA)",
    "cardinality_and": "Cardinality (AND)",
    "celltype_x_tissue": "Cell-type × tissue",
    "dose_response": "Dose–response",
    "dual_disease": "Dual disease",
    "exclusion_extended": "Exclusion (extended)",
    "lessons_wildcard": "Wildcard (lessons)",
    "longitudinal": "Longitudinal",
    "multi_omics": "Multi-omics",
    "multi_organism": "Multi-organism",
    "negation": "Negation",
    "paired_multi_tissue": "Paired multi-tissue",
}

# 프로젝트 팔레트 (teal 계열 + 보조색). 색약 고려 + 인쇄 친화.
TEAL = "#0d9488"
AMBER = "#f59e0b"
SLATE = "#64748b"
CORAL = "#e1564b"
INK = "#1c1917"
GRID = "#d6d3d1"


def _style() -> None:
    plt.rcParams.update({
        "font.size": 12,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
        "axes.edgecolor": "#57534e",
        "axes.linewidth": 1.0,
        "xtick.color": INK,
        "ytick.color": INK,
        "text.color": INK,
        "axes.labelcolor": INK,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })


def _despine(ax: Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _label_bars(
    ax: Axes,
    bars: BarContainer,
    *,
    fmt: str = "{:.2f}",
    fontsize: int = 9,
    color: str = INK,
) -> None:
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, h),
                    xytext=(0, 2), textcoords="offset points",
                    ha="center", va="bottom", fontsize=fontsize, color=color)


def _ax_label(a: str) -> str:
    return AXIS_LABEL.get(a, a.replace("_", " "))


def _load(results_dir: Path) -> pd.DataFrame:
    frames = []
    for name in ("hard_queries", "balanced_queries"):
        p = results_dir / "aggregated" / f"{name}_results.csv"
        if p.exists():
            df = pd.read_csv(p)
            df["set"] = name.replace("_queries", "")
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _save(fig: Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{stem}.pdf", dpi=300, bbox_inches="tight")
    fig.savefig(out_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / stem}.{{pdf,png}}")


def _fig_ablation(df: pd.DataFrame, out_dir: Path) -> None:
    d = df[(df.metric == "facet_present_macro") & (df.axis == "ALL") & (df.lang == "en")]
    if d.empty:
        return
    sets = [s for s in ("balanced", "hard") if s in set(d["set"].unique())]
    colors = {"balanced": TEAL, "hard": AMBER}
    x = range(len(MODE_ORDER))
    w = 0.8 / max(1, len(sets))
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, s in enumerate(sets):
        ds = d[d["set"] == s].set_index("mode")
        vals = [float(ds.loc[m, "mean"]) if m in ds.index else 0.0 for m in MODE_ORDER]
        set_label = "balanced draft" if s == "balanced" else "hard internal"
        bars = ax.bar([xi + i * w for xi in x], vals, w, label=set_label, color=colors.get(s, SLATE),
                      edgecolor="white", linewidth=0.6)
        _label_bars(ax, bars)
    ax.set_xticks([xi + w * (len(sets) - 1) / 2 for xi in x])
    ax.set_xticklabels([MODE_LABEL[m] for m in MODE_ORDER])
    ax.set_ylabel("Historical facet present@10 (macro)")
    ax.set_ylim(0, 1.08)
    ax.set_title("Exploratory facet-tag regression by mode (EN)\n"
                 "aggregate only; run configuration incomplete", fontsize=12)
    ax.legend(title="query set", loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    ax.grid(axis="y", alpha=0.35, color=GRID)
    ax.set_axisbelow(True)
    _despine(ax)
    _save(fig, out_dir, "fig_ablation_present")


def _fig_present_vs_conjunctive(df: pd.DataFrame, out_dir: Path) -> None:
    d = df[(df["set"] == "hard") & (df["mode"] == "rrf_rerank") & (df.lang == "en") & (df.axis != "ALL")]
    if d.empty:
        return
    pres = d[d.metric == "facet_present_macro"].set_index("axis")["mean"]
    conj = d[d.metric == "facet_conjunctive_macro"].set_index("axis")["mean"]
    axes_ = [a for a in pres.index if a in conj.index]
    if not axes_:
        return
    # gap 큰 순(=paired/cardinality 약점) 정렬.
    axes_ = sorted(axes_, key=lambda a: float(pres[a]) - float(conj[a]), reverse=True)
    x = range(len(axes_))
    fig, ax = plt.subplots(figsize=(max(8.5, len(axes_) * 0.62), 4.8))
    ax.bar([xi - 0.21 for xi in x], [float(pres[a]) for a in axes_], 0.42,
           label="values present across top-10", color=TEAL, edgecolor="white", linewidth=0.5)
    ax.bar([xi + 0.21 for xi in x], [float(conj[a]) for a in axes_], 0.42,
           label="within-facet values in one result", color=SLATE, edgecolor="white", linewidth=0.5)
    # gap 이 있는 축만 작은 라벨.
    for xi, a in zip(x, axes_, strict=True):
        gap = float(pres[a]) - float(conj[a])
        if gap >= 0.05:
            ax.annotate(f"−{gap:.2f}", (xi, max(float(pres[a]), float(conj[a]))),
                        xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=8, color=CORAL, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels([_ax_label(a) for a in axes_], rotation=40, ha="right", fontsize=9)
    ax.set_ylabel("macro score @10")
    ax.set_ylim(0, 1.08)
    ax.set_title("Historical hard set: present vs within-facet co-occurrence\n"
                 "This metric does not test whether different facet types co-occur in one dataset",
                 fontsize=12)
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="y", alpha=0.35, color=GRID)
    ax.set_axisbelow(True)
    _despine(ax)
    _save(fig, out_dir, "fig_present_vs_conjunctive_hard")


def _fig_ko_en_parity(df: pd.DataFrame, out_dir: Path) -> None:
    d = df[(df["set"] == "hard") & (df.metric == "facet_present_macro") & (df.axis == "ALL")]
    if d.empty:
        return
    x = range(len(MODE_ORDER))
    colors = {"en": TEAL, "ko": AMBER}
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    vals_by = {}
    for i, lang in enumerate(("en", "ko")):
        dl = d[d.lang == lang].set_index("mode")
        vals = [float(dl.loc[m, "mean"]) if m in dl.index else 0.0 for m in MODE_ORDER]
        vals_by[lang] = vals
        bars = ax.bar([xi + i * 0.4 for xi in x], vals, 0.4, label=lang.upper(),
                      color=colors[lang], edgecolor="white", linewidth=0.6)
        _label_bars(ax, bars, fontsize=8)
    # Describe the smallest observed aggregate gap without calling it parity or improvement.
    if vals_by.get("en") and vals_by.get("ko"):
        gaps = [abs(e - k) for e, k in zip(vals_by["en"], vals_by["ko"], strict=True)]
        j = min(range(len(gaps)), key=lambda i: gaps[i])
        ax.annotate(f"smallest observed gap\n{gaps[j]*100:.1f} pp; scores also lower vs RRF",
                    (j + 0.2, 1.0),
                    xytext=(0, 0), textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, color=TEAL, fontweight="bold")
    ax.set_xticks([xi + 0.2 for xi in x])
    ax.set_xticklabels([MODE_LABEL[m] for m in MODE_ORDER])
    ax.set_ylabel("Historical facet present@10 (macro)")
    ax.set_ylim(0, 1.12)
    ax.set_title("Exploratory English–Korean aggregates (internal hard set)\n"
                 "aggregate only; run configuration incomplete", fontsize=12)
    ax.legend(title="language", loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    ax.grid(axis="y", alpha=0.35, color=GRID)
    ax.set_axisbelow(True)
    _despine(ax)
    _save(fig, out_dir, "fig_ko_en_parity_hard")


def _fig_gpb_retrieval(df: pd.DataFrame, out_dir: Path) -> None:
    """Render the two panels used as logical Figure 3 in the GPB draft."""
    all_rows = df[(df.metric == "facet_present_macro") & (df.axis == "ALL")]
    panel_a = all_rows[all_rows.lang == "en"]
    panel_b = all_rows[all_rows["set"] == "hard"]
    if panel_a.empty or panel_b.empty:
        return

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(13.6, 5.2), sharey=True)
    x = list(range(len(MODE_ORDER)))
    width = 0.38

    query_sets = (
        ("hard", "hard internal (n=49)", AMBER),
        ("balanced", "balanced draft (n=30)", TEAL),
    )
    for index, (query_set, label, color) in enumerate(query_sets):
        values = panel_a[panel_a["set"] == query_set].set_index("mode")
        heights = [float(values.loc[mode, "mean"]) for mode in MODE_ORDER]
        bars = ax_a.bar(
            [position + (index - 0.5) * width for position in x],
            heights,
            width,
            label=label,
            color=color,
            edgecolor="white",
            linewidth=0.6,
        )
        _label_bars(ax_a, bars, fmt="{:.3f}", fontsize=8)

    languages = (("en", "English (n=49)", TEAL), ("ko", "Korean (n=49)", AMBER))
    values_by_language: dict[str, list[float]] = {}
    for index, (language, label, color) in enumerate(languages):
        values = panel_b[panel_b.lang == language].set_index("mode")
        heights = [float(values.loc[mode, "mean"]) for mode in MODE_ORDER]
        values_by_language[language] = heights
        bars = ax_b.bar(
            [position + (index - 0.5) * width for position in x],
            heights,
            width,
            label=label,
            color=color,
            edgecolor="white",
            linewidth=0.6,
        )
        _label_bars(ax_b, bars, fmt="{:.3f}", fontsize=8)

    gaps = [
        abs(en_value - ko_value)
        for en_value, ko_value in zip(
            values_by_language["en"], values_by_language["ko"], strict=True
        )
    ]
    smallest_index = min(range(len(gaps)), key=gaps.__getitem__)
    ax_b.annotate(
        f"smallest observed gap: {gaps[smallest_index] * 100:.1f} pp\n"
        "both values lower than RRF",
        (smallest_index, 1.015),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color="#0f5f57",
        fontweight="bold",
    )

    for panel_label, axis, title in (
        ("A", ax_a, "English aggregates by internal query set"),
        ("B", ax_b, "Hard-set aggregates by query language"),
    ):
        axis.set_xticks(x)
        axis.set_xticklabels([MODE_LABEL[mode] for mode in MODE_ORDER], fontsize=9)
        axis.set_ylim(0, 1.12)
        axis.set_title(title, fontsize=11.5)
        axis.legend(loc="lower left", frameon=False, fontsize=8.5)
        axis.grid(axis="y", alpha=0.35, color=GRID)
        axis.set_axisbelow(True)
        axis.text(
            0.01,
            1.08,
            panel_label,
            transform=axis.transAxes,
            fontsize=15,
            fontweight="bold",
            va="top",
        )
        _despine(axis)

    ax_a.set_ylabel("Historical facet present@10 (query-level macro mean)")
    fig.suptitle("Exploratory facet-tag retrieval aggregates", fontsize=14, fontweight="bold")
    fig.text(
        0.5,
        0.01,
        "Aggregate CSVs only; per-query outputs and a complete run manifest were not retained. "
        "No expert relevance assessment or inferential test was performed; frozen rerun required.",
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=SLATE,
    )
    fig.subplots_adjust(top=0.82, bottom=0.20, wspace=0.12)
    _save(fig, out_dir, "fig_gpb_retrieval")


def _fig_exclusion(df: pd.DataFrame, out_dir: Path) -> None:
    base = df[(df.metric == "exclusion_clean_at_k") & (df["mode"] == "rrf_rerank") & (df.axis != "ALL")]
    if base.empty:
        return
    en = base[base.lang == "en"].set_index("axis")["mean"]
    ko = base[base.lang == "ko"].set_index("axis")["mean"]
    axes_ = sorted(set(en.index) | set(ko.index), key=lambda a: float(en.get(a, 0)))
    y = range(len(axes_))
    h = 0.38
    fig, ax = plt.subplots(figsize=(7.6, max(3.2, len(axes_) * 0.7)))
    b_en = ax.barh([yi + h / 2 for yi in y], [float(en.get(a, 0)) for a in axes_], h,
                   label="EN", color=TEAL, edgecolor="white", linewidth=0.5)
    b_ko = ax.barh([yi - h / 2 for yi in y], [float(ko.get(a, 0)) for a in axes_], h,
                   label="KO", color=AMBER, edgecolor="white", linewidth=0.5)
    for bars in (b_en, b_ko):
        for b in bars:
            w = b.get_width()
            ax.annotate(f"{w:.2f}", (w, b.get_y() + b.get_height() / 2),
                        xytext=(3, 0), textcoords="offset points", va="center",
                        fontsize=8, color=INK)
    ax.set_yticks(list(y))
    ax.set_yticklabels([_ax_label(a) for a in axes_])
    ax.set_xlabel("historical snippet clean fraction (empty/failed results were scored 1.0)")
    ax.set_xlim(0, 1.12)
    ax.set_title("Diagnostic only — not negation accuracy (RRF+Rerank)")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", alpha=0.35, color=GRID)
    ax.set_axisbelow(True)
    _despine(ax)
    _save(fig, out_dir, "fig_exclusion_by_axis")


def render(results_dir: Path | None = None, out_dir: Path | None = None) -> None:
    results_dir = results_dir or Path("results")
    out_dir = out_dir or (results_dir / "figures")
    df = _load(results_dir)
    if df.empty:
        print("no result CSVs found — run the eval first")
        return
    _style()
    print(f"loaded {len(df)} rows; rendering figures → {out_dir}")
    _fig_ablation(df, out_dir)
    _fig_present_vs_conjunctive(df, out_dir)
    _fig_ko_en_parity(df, out_dir)
    _fig_exclusion(df, out_dir)
    _fig_gpb_retrieval(df, out_dir)
    print("figures done")


def main() -> None:
    render()


if __name__ == "__main__":
    main()
