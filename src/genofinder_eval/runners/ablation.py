"""4-system ablation 결과 통합 + paired bootstrap significance test.

흐름:
  1. per-query metric (예: nDCG@10) 의 두 list (System A vs System B) 비교
  2. per-query difference 의 1000-iter paired bootstrap → 95% CI + p-value
"""
from __future__ import annotations

import random
import statistics
from collections.abc import Sequence


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    iterations: int = 1000,
    seed: int = 42,
) -> tuple[float, tuple[float, float], float]:
    """Paired bootstrap for two correlated metric lists.

    Args:
        a, b:       per-query metric values (length 일치 필수).
        iterations: bootstrap resample 횟수.
        seed:       재현성용.

    Returns:
        (mean_diff, (CI_lower, CI_upper), two_sided_p_value).

    Algorithm:
        - obs_diff = mean(a) - mean(b)
        - 1000회 resample (with replacement) — 같은 index 페어를 재추출.
        - 각 resample 의 mean_diff distribution → 95% CI (2.5 / 97.5 percentile).
        - p-value: 부호 반전 비율 (two-sided).
    """
    if len(a) != len(b):
        raise ValueError(f"a, b length mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0, (0.0, 0.0), 1.0

    rng = random.Random(seed)
    n = len(a)
    diffs = [ai - bi for ai, bi in zip(a, b, strict=True)]
    obs_diff = statistics.fmean(diffs)

    boot_diffs: list[float] = []
    for _ in range(iterations):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot_diffs.append(statistics.fmean(sample))

    boot_diffs.sort()
    lower = boot_diffs[max(0, int(0.025 * iterations) - 1)]
    upper = boot_diffs[min(iterations - 1, int(0.975 * iterations))]

    # Two-sided p-value: |bootstrap diff - obs_diff| 가 |obs_diff| 보다 큰 비율 (대략적).
    # 더 정확히는 H0 (mean_diff=0) 가정 하의 분포 추정 — 본 구현은 percentile-based CI 기반
    # 의 간이 p-value.
    if obs_diff >= 0:
        p_one = sum(1 for d in boot_diffs if d <= 0) / iterations
    else:
        p_one = sum(1 for d in boot_diffs if d >= 0) / iterations
    p_two = min(1.0, 2.0 * p_one)

    return obs_diff, (lower, upper), p_two


def pairwise_compare(
    metric_per_query_by_mode: dict[str, dict[str, float]],
    iterations: int = 1000,
    seed: int = 42,
) -> list[dict[str, float | str]]:
    """4 mode 의 4C2 = 6 pairwise comparison.

    Args:
        metric_per_query_by_mode: {mode_name: {qid: metric_value}}.
                                  qid set 은 모든 mode 에서 동일해야 함.

    Returns:
        list of {mode_a, mode_b, mean_diff, ci_lower, ci_upper, p_value}.
    """
    modes = sorted(metric_per_query_by_mode.keys())
    qids = sorted(next(iter(metric_per_query_by_mode.values())).keys())

    rows: list[dict[str, float | str]] = []
    for i, ma in enumerate(modes):
        for mb in modes[i + 1:]:
            a_vals = [metric_per_query_by_mode[ma][q] for q in qids]
            b_vals = [metric_per_query_by_mode[mb][q] for q in qids]
            mean_diff, (lo, hi), p = paired_bootstrap(a_vals, b_vals, iterations, seed)
            rows.append({
                "mode_a": ma,
                "mode_b": mb,
                "mean_diff": mean_diff,
                "ci_lower": lo,
                "ci_upper": hi,
                "p_value": p,
            })
    return rows
