"""Prediction-powered inference: a mean from a few human labels and many judge labels (docs/statistics.md#ppi).

PPI++ (Angelopoulos et al. 2023): theta = lam * mean(f over unlabelled) + mean(y - lam * f over labelled), with lam
tuned to minimise the variance (lam = 0 is the human-only mean, so the estimate never does worse than it in
expectation). The judge's bias is corrected by the labelled residuals; the judge only narrows the interval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import NormalDist

import numpy as np

from flightdeck.stats.core import Interval


def ppi_mean(y: Sequence[float], f_lab: Sequence[float], f_unl: Sequence[float], level: float = 0.95,
             lam: float | None = None) -> Interval:
    """The PPI++ mean and its normal interval. `y` and `f_lab`: human and judge labels on the same items; `f_unl`:
    judge labels on the rest."""
    y_, fl, fu = (np.asarray(x, float) for x in (y, f_lab, f_unl))
    n, big = len(y_), len(fu)
    if n < 2 or len(fl) != n:
        raise ValueError("need at least two items with both a human and a judge label")
    if lam is None:
        var_f = np.var(np.concatenate([fl, fu]), ddof=1)
        lam = 0.0 if var_f == 0 or big == 0 else float(np.clip(np.cov(y_, fl)[0, 1] / ((1 + n / big) * var_f), 0, 1))
    est = (lam * fu.mean() if big else 0.0) + (y_ - lam * fl).mean()
    var = (lam**2 * fu.var(ddof=1) / big if big > 1 else 0.0) + (y_ - lam * fl).var(ddof=1) / n
    half = NormalDist().inv_cdf(0.5 + level / 2) * float(np.sqrt(var))
    return Interval(float(est), float(est - half), float(est + half), level, n_trials=n + big,
                    note=f"PPI++, lambda {lam:.2f}, {n} human-labelled")


def ppi_stratified(strata: Mapping[str, tuple[Sequence[float], Sequence[float], Sequence[float]]],
                   level: float = 0.95) -> Interval:
    """Stratified PPI: each stratum's PPI++ mean weighted by its share of all items; variances add."""
    parts = {k: ppi_mean(*v, level=level) for k, v in strata.items()}
    sizes = {k: len(v[0]) + len(v[2]) for k, v in strata.items()}
    w = {k: s / sum(sizes.values()) for k, s in sizes.items()}
    est = sum(w[k] * p.estimate for k, p in parts.items())
    half = float(np.sqrt(sum((w[k] * (p.high - p.low) / 2) ** 2 for k, p in parts.items())))
    return Interval(est, est - half, est + half, level, n_trials=sum(sizes.values()),
                    note=f"stratified PPI++ over {len(parts)} strata")
