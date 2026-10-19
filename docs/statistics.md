# Statistics

How flightdeck turns trials into numbers a team can decide on: paired by task, every interval with its n and seed.
Code: `src/flightdeck/stats/core.py`.

## What flightdeck can tell you

At the team's scale, about 500 trials a month, an A/B of a harness change can show:

### An outcome change of about 15 points or more

For example, a change that moves the share of tasks resolved from 40% to 55%. With 50 tasks run 3 times in each arm
(300 trials), a 15-point change is detected about 4 times in 5. A 10-point change is detected about half the time, a
5-point change about 1 time in 5.

With 30 tasks the smallest change seen 4 times in 5 is about 20 points; with 20 tasks, about 25.

### "Not worse" only with many tasks

The 95% interval on resolved is about 19 points wide at 50 tasks × 3 trials, 24 at 30 tasks and 29 at 20. For a
non-inferiority verdict at a 5-point margin, the whole interval has to sit above −5 points.

When nothing really changed, that happens about 1 time in 5 at 50 tasks: 19% of 20,000 simulated experiments, 16%
*non-inferior* and 3% *better*. The other 4 times the report says *No decision*. At that size it is the honest answer,
not a failure.

Seeing 5-point changes, or a 5-point margin, takes about 400 tasks × 3 trials per arm. That is 2,400 trials, about
five months at this scale, for an interval about 7 points wide.

### Smaller changes in process metrics

Tool calls, cost and wall time are numbers on every trial rather than a pass or a fail. Each comes with its own paired
interval, which is often far narrower than the outcome's.

### Behavior

Whether each behavior spec holds, as a pass rate per variant, and a jump in a spec's nightly violation rate
([behavior specs](behavior-specs.md)).

### What it can't show

An outcome change of a few points, at this budget. Those are judged by process metrics, behavior specs and, later,
trace-mined skill micro-evals ([#33](https://github.com/Sean-Koval/flightdeck/issues/33)).

### Where the numbers come from

Flightdeck's own code, on one model of tasks. Each task's base rate is drawn from Beta(1.2, 1.2), with 3 trials per
task and arm, and no real change for the interval widths.

`simulate_power` gives detection: a one-sided z test at α = 0.025, the same bar as a 95% interval whose lower bound
is above zero, at 80% power. `paired_bootstrap` with the report's verdict rule gives the intervals.

Every `stats compare` prints the smallest change its own experiment can detect.

## Pair by task

At about 500 trials a month, an outcome A/B is only worth running **paired by task**. Every task runs in both arms,
and the comparison resamples tasks. Tasks differ far more from each other than trials of one task do. So unpaired
comparisons, or trial-level resampling, mostly measure which tasks each arm happened to get.

<div class="af-figure" markdown>
--8<-- "docs/assets/paired-by-task.svg"
<figcaption>Every task runs in both arms; the discordant tasks carry the signal</figcaption>
</div>

A simulation (`stats.core.simulate_power`; task base rates from Beta(1.2, 1.2), one-sided z test at α = 0.025),
50 tasks × 3 trials per arm:

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
| `cohen_kappa(pairs)` | Cohen's κ for two raters' binary labels | Rater agreement on the knowledge gold set; judges' calibration ([#27](https://github.com/Sean-Koval/flightdeck/issues/27)) |

Every result is an `Interval` carrying its estimate, bounds, level, number of tasks and trials, the seed, and a note.
Fewer than 10 paired tasks is labelled *underpowered: do not decide on this*. No p-value is reported without its
interval and n.

## `flightdeck stats compare`

```sh
flightdeck stats compare <experiment> [--baseline control] [--candidate candidate] [--metric resolved|cost_usd|tool_calls|wall_s]
                         [--include-drift] [--seed 0] [--data DIR]
```

Code: `src/flightdeck/stats/compare.py`.

Per variant it prints the trials and the resolve rate with its Wilson interval (or the metric's mean), and dollars
per resolved task with its task-bootstrap interval. Then the paired difference, candidate minus baseline, with its 95%
task-bootstrap interval and the numbers of tasks and trials.

After that: concordant and discordant tasks (resolved), a power line, the resolved definition used, the exclusions
with counts, and the saturated tasks. The power line is the smallest lift `simulate_power` detects at 80% power with
this many tasks and trials, cached per n.

`tool_calls` counts the trial's `tool.call` spans; `wall_s` is the trial's finish minus start.

### Exclusions

First match wins:

- `not finished`: pending or running.
- `infra_error`: hangar's `outcome_class = infra_error`, or `excluded`. Hangar retries it as the next attempt under
  the same key. Flightdeck never infers it from a failure reason; a null class is unknown, not infrastructure.
- `cancelled`, or `outcome_class = cancelled`.
- `human`: a person stepped in.
- `task_invalid`: the task failed hangar's base check.
- `contaminated`: the grader's canary was seen.
- `drift`, unless `--include-drift`.
- `truncated trace`: process metrics only.
- `no grade or verify`.
- `unknown <metric>`: for cost, no usage recorded.

## Rules for reports

### Resolved

The grader passing (`grades.exit_code = 0` and `applied`), else hangar's after-turn verify. The report names which one
it used.

### Exclusions

Always listed with counts: `infra_error`, cancelled trials, drift (a trial whose configuration differs from its
variant's), truncated traces (process metrics only), tainted runs (promotion only), unknown cost ($ metrics only).

### Saturated tasks

Listed, since they carry no information: every trial of every arm had the same outcome.

### Seeds

Every resampling takes one, and reports print it.

### Reused trials

Trials from the [trial cache](runners.md#cache) count like new ones and are deduplicated by `run_id`, so a trial never
counts twice in one analysis. The comparison says how many were reused and how old they are.

## Mutation scores

`flightdeck mutate score` ([behavior specs](behavior-specs.md#mutation-scoring)) counts a mutant **killed** when
either:

- **the outcome moved**: the paired task bootstrap of resolved (mutant − base, tasks resampled, seed 0) has a 95%
  interval that excludes 0; or
- **a spec broke**: the spec held on the base, and on the mutant it is below the bound. Holding means its pass^k over
  tasks (k = the fewest judged trials of any task) is at least the bound (default 0.9). Only `pass` and `fail` count;
  `not_applicable` and `unknown` units are left out.

The **mutation score** is killed / (killed + survived) with a 95% Wilson interval. Equivalent mutants (no observable
difference expected) and mutants without trials are reported but not counted.

With n = 2 trials per task, a spec needs every judged trial to pass on the base to reach 0.9 on a small suite. So the
spec criterion is strict on the base and loose on the mutant: one failing task on the mutant is enough to kill it.

Read a survived mutant as "this suite didn't notice", not as "this component is useless".

## PPI

Prediction-powered inference (`stats/ppi.py`, used by [judges](judges.md)) estimates a mean from `n` human labels and
`N` judge labels.

PPI++: `θ = λ·mean(f over the N unlabelled) + mean(y − λ·f over the n labelled)`, with
`λ = cov(y, f) / ((1 + n/N)·var(f))` clipped to [0, 1]. The interval is normal, from
`λ²·var(f_unlabelled)/N + var(y − λ·f_labelled)/n`.

The residuals correct the judge's bias, so a biased judge only costs width; `λ = 0` is the human-only mean.
`ppi_stratified` combines per-stratum estimates weighted by each stratum's share of items.

The acceptance simulation uses 100 human labels and 2,000 judge labels from a judge that agrees 85% of the time. Its
95% interval covers the true mean at about the nominal rate, and is narrower than the human-only interval almost
every time (`tests/test_judges.py`). Reports print the PPI estimate, never a raw judge mean alone.

## Later

Sequential and adaptive designs (no peeking at fixed-n experiments), CUPED and confidence sequences for shadow
traffic. And mixed-effects models, a random effect per task, as the preferred model once the task bootstrap is in
routine use.

## See also

- [Reports](reports.md): the verdict rule these numbers feed.
- [Running experiments](runners.md): how many tasks and trials a plan has, and what that costs.
- [Judges](judges.md): where PPI is used.
- [Concepts](concepts.md): pp, CI, margin, saturated task, discordant pair.
