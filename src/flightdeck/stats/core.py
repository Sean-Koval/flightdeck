"""Intervals and paired comparisons for agent trials, at the team's scale (hundreds of trials a month).

Comparisons are paired by task and resample tasks, not trials: tasks differ far more from each other than trials of
one task do, so trial-level resampling understates the uncertainty. Every resampling takes a seed, and results carry
their n. numpy and `statistics.NormalDist` only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import comb, sqrt
from statistics import NormalDist

import numpy as np

UNDERPOWERED_TASKS = 10


@dataclass(frozen=True)
class Interval:
    """A point estimate with a two-sided confidence interval and what it was computed from."""

    estimate: float
    low: float
    high: float
    level: float = 0.95
    n_tasks: int = 0
    n_trials: int = 0
    seed: int | None = None
    note: str = ""

    def __str__(self) -> str:
        s = f"{self.estimate:+.3f} [{self.low:+.3f}, {self.high:+.3f}] ({self.level:.0%}, n={self.n_tasks} tasks"
        s += f", {self.n_trials} trials" if self.n_trials else ""
        return s + (f"; {self.note}" if self.note else "") + ")"


def _z(level: float) -> float:
    return NormalDist().inv_cdf(0.5 + level / 2)


def wilson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. (0.0, 1.0) when n is 0."""
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return 0.0, 1.0
    z = _z(level)
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return (0.0 if k == 0 else max(0.0, centre - half)), (1.0 if k == n else min(1.0, centre + half))


def pass_at_k(c: int, n: int, k: int) -> float:
    """Unbiased pass@k from c successes in n trials of one task: P(at least one of k drawn trials passes)."""
    _check(c, n, k)
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(c: int, n: int, k: int) -> float:
    """pass^k (tau-bench) for one task: P(all k drawn trials pass) = C(c, k) / C(n, k). A reliability measure."""
    _check(c, n, k)
    return comb(c, k) / comb(n, k)


def pass_hat_k_suite(counts: Sequence[tuple[int, int]], k: int) -> float:
    """pass^k over a suite: the mean over tasks of C(c, k) / C(n, k), from (c, n) per task."""
    if not counts:
        raise ValueError("no tasks")
    return float(np.mean([pass_hat_k(c, n, k) for c, n in counts]))


def _check(c: int, n: int, k: int) -> None:
    if not (0 <= c <= n and 1 <= k <= n):
        raise ValueError(f"need 0 <= c <= n and 1 <= k <= n, got c={c}, n={n}, k={k}")


def clean_run_bound(n_clean: int, alpha: float = 0.05) -> float:
    """Upper (1 - alpha) bound on a failure rate after n_clean trials without a failure: 1 - alpha^(1/n).

    "It never does X" at <5% with 95% confidence needs 59 clean trials (the rule of three, exactly).
    """
    if n_clean < 1:
        return 1.0
    return 1.0 - alpha ** (1.0 / n_clean)


PerTask = Mapping[str, tuple[Sequence[float], Sequence[float]]]


def paired_bootstrap(per_task: PerTask, b: int = 10_000, seed: int = 0, level: float = 0.95) -> Interval:
    """Mean difference B - A across tasks, with a percentile interval from resampling TASKS with replacement.

    `per_task` maps a task id to (A's trial values, B's trial values): 0/1 for outcomes, or a process metric. Within a
    task each arm is reduced to its mean, so tasks weigh equally whatever their trial counts. Tasks missing an arm are
    dropped.
    """
    tasks = [(np.mean(a), np.mean(b_)) for a, b_ in per_task.values() if len(a) and len(b_)]
    if not tasks:
        raise ValueError("no task has trials in both arms")
    diffs = np.array([y - x for x, y in tasks])
    n_trials = sum(len(a) + len(b_) for a, b_ in per_task.values() if len(a) and len(b_))
    rng = np.random.default_rng(seed)
    boot = diffs[rng.integers(0, len(diffs), size=(b, len(diffs)))].mean(axis=1)
    lo, hi = np.quantile(boot, [(1 - level) / 2, (1 + level) / 2])
    note = f"underpowered: fewer than {UNDERPOWERED_TASKS} paired tasks, do not decide on this" if len(
        diffs) < UNDERPOWERED_TASKS else ""
    return Interval(float(diffs.mean()), float(lo), float(hi), level, len(diffs), n_trials, seed, note)


def trial_bootstrap(per_task: PerTask, b: int = 10_000, seed: int = 0, level: float = 0.95) -> Interval:
    """The naive comparison, resampling trials within each arm and ignoring tasks. For contrast only: it understates
    the uncertainty when tasks differ, which is why reports use paired_bootstrap."""
    a = np.concatenate([np.asarray(x, float) for x, y in per_task.values() if len(x) and len(y)])
    c = np.concatenate([np.asarray(y, float) for x, y in per_task.values() if len(x) and len(y)])
    rng = np.random.default_rng(seed)
    boot = (c[rng.integers(0, len(c), (b, len(c)))].mean(axis=1) - a[rng.integers(0, len(a), (b, len(a)))].mean(axis=1))
    lo, hi = np.quantile(boot, [(1 - level) / 2, (1 + level) / 2])
    return Interval(float(c.mean() - a.mean()), float(lo), float(hi), level, len(per_task), len(a) + len(c), seed)


def dollars_per_resolved(per_task: Mapping[str, Sequence[tuple[float | None, bool]]], b: int = 10_000, seed: int = 0,
                         level: float = 0.95) -> Interval:
    """Dollars per resolved task: total cost over resolved count (a ratio of sums), task-bootstrapped.

    `per_task` maps a task to its trials' (cost_usd, resolved). Trials with unknown cost are excluded and counted in
    the note. The estimate is inf when nothing resolved.
    """
    rows, missing = [], 0
    for trials in per_task.values():
        known = [(c, r) for c, r in trials if c is not None]
        missing += len(trials) - len(known)
        if known:
            rows.append((sum(c for c, _ in known), sum(1 for _, r in known if r), len(known)))
    if not rows:
        raise ValueError("no trial has a known cost")
    cost = np.array([r[0] for r in rows])
    won = np.array([r[1] for r in rows], float)
    est = float(cost.sum() / won.sum()) if won.sum() else float("inf")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rows), (b, len(rows)))
    num, den = cost[idx].sum(axis=1), won[idx].sum(axis=1)
    ratio = np.where(den > 0, num / np.where(den > 0, den, 1), np.inf)
    lo, hi = np.quantile(ratio, [(1 - level) / 2, (1 + level) / 2], method="inverted_cdf")  # inf-safe
    note = f"{missing} trials without a known cost excluded" if missing else ""
    return Interval(est, float(lo), float(hi), level, len(rows), sum(r[2] for r in rows), seed, note)


def mcnemar_discordant(pairs: Sequence[tuple[bool, bool]]) -> dict[str, float | int]:
    """McNemar counts for paired binary outcomes (A, B) per task: concordant, b (A only), c (B only), exact p."""
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    n = b + c
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n if n else 1.0
    return {"concordant": len(pairs) - n, "b": b, "c": c, "n_discordant": n, "p_exact": min(1.0, 2 * tail)}


def simulate_power(tasks: int, trials: int, delta: float, sims: int = 2000, seed: int = 0, paired: bool = True,
                   alpha: float = 0.05) -> float:
    """Power of a one-sided z test at `alpha` for a `delta` lift, with task base rates from Beta(1.2, 1.2).

    The panel's r1 simulation: paired uses every task in both arms; unpaired splits tasks between arms.
    """
    rng = np.random.default_rng(seed)
    z = NormalDist().inv_cdf(1 - alpha / 2)
    hits = 0
    for _ in range(sims):
        p0 = rng.beta(1.2, 1.2, tasks)
        p1 = np.clip(p0 + delta, 0, 1)
        a, b = rng.binomial(trials, p0) / trials, rng.binomial(trials, p1) / trials
        if paired:
            d = b - a
            sd = d.std(ddof=1)
            stat = d.mean() / (sd / sqrt(tasks)) if sd > 0 else 0.0
        else:
            h = tasks // 2
            se = sqrt(b[:h].var(ddof=1) / h + a[h:].var(ddof=1) / h)
            stat = (b[:h].mean() - a[h:].mean()) / se if se > 0 else 0.0
        hits += stat > z
    return hits / sims
