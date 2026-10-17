import math

import pytest

from flightdeck.stats.core import (
    clean_run_bound,
    dollars_per_resolved,
    mcnemar_discordant,
    paired_bootstrap,
    pass_at_k,
    pass_hat_k,
    pass_hat_k_suite,
    simulate_power,
    trial_bootstrap,
    wilson,
)


def test_wilson_known_values() -> None:
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-3), pytest.approx(0.7634, abs=1e-3))
    assert wilson(10, 10)[1] == 1.0 and wilson(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_pass_k() -> None:
    assert pass_hat_k(3, 5, 2) == pytest.approx(0.3)
    assert pass_at_k(3, 5, 2) == pytest.approx(0.9)
    assert pass_hat_k(5, 5, 3) == 1.0 and pass_at_k(0, 5, 3) == 0.0
    assert pass_hat_k_suite([(3, 5), (5, 5)], 2) == pytest.approx(0.65)
    with pytest.raises(ValueError):
        pass_hat_k(1, 3, 4)


def test_clean_run_bound() -> None:
    assert clean_run_bound(59) == pytest.approx(0.0495, abs=1e-3)
    assert clean_run_bound(58) > 0.05 > clean_run_bound(59)
    assert clean_run_bound(0) == 1.0


def test_paired_bootstrap_is_deterministic_and_labels_small_n() -> None:
    per_task = {f"t{i}": ([0, 0, 1], [1, 1, 1]) for i in range(5)}
    a, b = paired_bootstrap(per_task, seed=7), paired_bootstrap(per_task, seed=7)
    assert a == b and a.estimate == pytest.approx(2 / 3) and a.n_tasks == 5 and a.n_trials == 30
    assert "underpowered" in a.note and a.seed == 7 and "n=5 tasks" in str(a)
    big = paired_bootstrap({f"t{i}": ([0, 1], [1, 1]) for i in range(12)})
    assert big.note == "" and big.low == big.high == pytest.approx(0.5)


def test_paired_bootstrap_resamples_tasks_not_trials() -> None:
    """One task with a huge effect and the rest with none: task-level resampling sees that the lift rests on one task
    and gives a wider interval than resampling trials."""
    per_task = {f"t{i}": ([0.0] * 5, [0.0] * 5) for i in range(11)}
    per_task["big"] = ([0.0] * 5, [100.0] * 5)
    paired = paired_bootstrap(per_task, b=4000, seed=1)
    naive = trial_bootstrap(per_task, b=4000, seed=1)
    assert paired.estimate == pytest.approx(naive.estimate)
    assert (paired.high - paired.low) > (naive.high - naive.low)
    assert paired.low == 0.0  # resamples without the big task exist


def test_paired_bootstrap_drops_tasks_missing_an_arm() -> None:
    r = paired_bootstrap({"a": ([1], [1]), "b": ([], [1]), **{f"t{i}": ([0], [1]) for i in range(10)}})
    assert r.n_tasks == 11
    with pytest.raises(ValueError):
        paired_bootstrap({"a": ([], [1])})


def test_dollars_per_resolved() -> None:
    per_task = {"a": [(1.0, True), (1.0, False)], "b": [(2.0, True), (None, True)], "c": [(4.0, False)]}
    r = dollars_per_resolved(per_task, seed=0)
    assert r.estimate == pytest.approx(8.0 / 2) and r.n_trials == 4 and "1 trials without" in r.note
    assert r.low <= r.estimate <= r.high
    assert math.isinf(dollars_per_resolved({"x": [(1.0, False)]}).estimate)


def test_mcnemar() -> None:
    pairs = [(True, True)] * 3 + [(False, True)] * 6 + [(True, False)]
    m = mcnemar_discordant(pairs)
    assert (m["concordant"], m["b"], m["c"], m["n_discordant"]) == (3, 1, 6, 7)
    assert m["p_exact"] == pytest.approx(0.125)  # 2 * (1 + 7) / 128
    assert mcnemar_discordant([(True, True)])["p_exact"] == 1.0


@pytest.mark.parametrize(("delta", "paired", "expected"), [(0.10, True, 0.54), (0.15, True, 0.83),
                                                          (0.10, False, 0.17)])
def test_power_reproduces_the_r1_table(delta: float, paired: bool, expected: float) -> None:
    """r1 power table, 50 tasks x 3 trials: paired 0.54 at 10 pp and 0.83 at 15 pp; unpaired 0.17 at 10 pp."""
    assert simulate_power(50, 3, delta, sims=1500, seed=0, paired=paired) == pytest.approx(expected, abs=0.05)
