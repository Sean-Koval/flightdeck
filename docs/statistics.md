# Statistics

How flightdeck turns trials into numbers a team can decide on. Code: `src/flightdeck/stats/core.py`.

## Pair by task

At about 500 trials a month, an outcome A/B is only worth running **paired by task**: every task runs in both
arms, and the comparison resamples tasks. Tasks differ far more from each other than trials of one task do, so
unpaired comparisons (or trial-level resampling) mostly measure which tasks each arm happened to get.

The panel's r1 simulation (`stats.core.simulate_power`; task base rates from Beta(1.2, 1.2), one-sided z test at
α = 0.05), 50 tasks × 3 trials per arm:

| Lift | Paired power | Unpaired power |
| --- | --- | --- |
| 10 pp | 0.54 | 0.17 |
| 15 pp | 0.83 | |

So the minimum detectable effect at this scale is about **15 percentage points**. Smaller real effects exist; this
budget can't see them. `tests/test_stats.py::test_power_reproduces_the_r1_table` keeps these numbers honest.

## Functions

| Function | What | Use |
| --- | --- | --- |
| `wilson(k, n)` | Wilson score interval for a rate | Per-arm resolve rates. `wilson(0, 10)` upper ≈ 0.278 |
| `pass_at_k(c, n, k)` | Unbiased pass@k, 1 − C(n−c, k)/C(n, k) | "Can it ever do this?" |
| `pass_hat_k(c, n, k)`, `pass_hat_k_suite` | τ-bench pass^k, C(c, k)/C(n, k), averaged over tasks | "Does it do this every time?" `pass_hat_k(3, 5, 2) = 0.3` |
| `clean_run_bound(n)` | 1 − α^(1/n): upper bound on a failure rate after n clean trials | "Never" at < 5% with 95% confidence needs **59** clean trials |
| `paired_bootstrap(per_task)` | Mean B − A over tasks, percentile interval from resampling tasks | Every A/B, outcomes and process metrics (tool calls, cost, wall time) alike |
| `trial_bootstrap(per_task)` | The naive trial-level interval | Contrast only: it is too narrow when tasks differ |
| `dollars_per_resolved(per_task)` | Total cost / resolved count (ratio of sums), task bootstrap | Cost efficiency. Trials with unknown cost are excluded and counted |
| `mcnemar_discordant(pairs)` | Concordant and discordant task counts, exact McNemar p | Reported with every outcome comparison; feeds adaptive allocation later |

Every result is an `Interval` carrying its estimate, bounds, level, number of tasks and trials, the seed, and a
note. Fewer than 10 paired tasks is labelled *underpowered: do not decide on this*. No p-value is reported without
its interval and n.

## `flightdeck stats compare`

```sh
flightdeck stats compare <experiment> [--a control] [--b treat] [--metric resolved|cost_usd|tool_calls|wall_s]
                         [--include-drift] [--seed 0] [--data DIR]
```

Code: `src/flightdeck/stats/compare.py`. Per variant: trials and the resolve rate with its Wilson interval (or the
metric's mean), and dollars per resolved task with its task-bootstrap interval. Then the paired difference B − A with
its 95% task-bootstrap interval, the numbers of tasks and trials, concordant and discordant tasks (resolved), a power
line (the smallest lift the r1 simulation detects at 80% power with this many tasks and trials, cached per n), the
resolved definition used, the exclusions with counts, and the saturated tasks. `tool_calls` counts the trial's
`tool.call` spans; `wall_s` is the trial's finish minus start.

Exclusions, first match wins: `not finished` (pending or running), `infra_error` (hangar's `outcome_class =
infra_error` or `excluded`: hangar retries it as the next attempt under the same key; flightdeck never infers it from a
failure reason, and a null class is unknown, not infrastructure), `cancelled` (or `outcome_class = cancelled`), `human`
(a person stepped in), `task_invalid` (the task failed hangar's base check), `contaminated` (the grader's canary was
seen), `drift` (unless `--include-drift`), `truncated trace` (process metrics only), `no grade or verify`, and
`unknown <metric>` (for cost: no usage recorded).

## Rules for reports

- **Resolved** is the grader passing (`grades.exit_code = 0` and `applied`), else hangar's after-turn verify. The
  report names which one it used.
- **Exclusions** are always listed with counts: `infra_error`, cancelled trials, drift (a trial whose configuration
  differs from its variant's), truncated traces (process metrics only), tainted runs (promotion only), unknown cost
  ($ metrics only).
- **Saturated tasks** (every trial of every arm had the same outcome) are listed: they carry no information.
- **Seeds**: every resampling takes one and reports print it.

## Mutation scores

`flightdeck mutate score` ([behavior specs](behavior-specs.md#mutation-scoring)) counts a mutant **killed** when
either:

- **the outcome moved**: the paired task bootstrap of resolved (mutant − base, tasks resampled, seed 0) has a 95%
  interval that excludes 0; or
- **a spec broke**: the spec held on the base, meaning its pass^k over tasks (k = the fewest judged trials of any
  task) is at least the bound (default 0.9), and on the mutant it is below the bound. Only `pass` and `fail` count;
  `not_applicable` and `unknown` units are left out.

The **mutation score** is killed / (killed + survived) with a 95% Wilson interval. Equivalent mutants (no observable
difference expected) and mutants without trials are reported but not counted. With n = 2 trials per task, a spec
needs every judged trial to pass on the base to reach 0.9 on a small suite, so the spec criterion is strict on the
base and loose on the mutant: one failing task on the mutant is enough to kill it. Read a survived mutant as "this
suite didn't notice", not as "this component is useless".

## Later

Sequential and adaptive designs (no peeking at fixed-n experiments), prediction-powered inference for model judges,
CUPED and confidence sequences for shadow traffic, and mixed-effects models (a random effect per task) as the
preferred model once the task bootstrap is in routine use.
