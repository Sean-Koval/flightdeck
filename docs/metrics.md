# Weekly team metrics

The team's weekly scorecard, defined once here and computed by one SQL file over the data plane. hangar's standup
line and Slack digest read the rendered numbers, never their own.

This page is the definition; hangar's standup line and Slack digest (hangar#168) cite it and read `latest.json`. The
only implementation is
[`src/flightdeck/metrics/weekly.sql`](https://github.com/Sean-Koval/flightdeck/blob/main/src/flightdeck/metrics/weekly.sql):
one DuckDB view per metric over the [data plane](data-plane.md), with each numerator and denominator repeated in a
header comment. A change to a definition changes this page and that file in the same PR.

```sh
flightdeck metrics weekly [--week 2026-W45] [--format md|json|slack] [--person P] [--repo owner/repo]
```

It reads Parquet only (`FLIGHTDECK_DATA_URI`), so it runs with hangar powered off. With `FLIGHTDECK_REPORTS_URI` set
and no `--person` or `--repo`, it also writes `<reports>/weekly/<week>.json`, `<week>.md` and `latest.json`
([`flightdeck.weekly/v1`](data-plane.md#flightdeckweeklyv1)). The nightly compactor job refreshes them for the last
complete week.

## Conventions

### Week

ISO week, Monday 00:00 to the next Monday 00:00 UTC. An event belongs to the week its timestamp falls in.

### Agent job

A hangar job with `source = job`: delegated work, from the API, GitHub, Slack or Jira. Experiment trials and shadow
runs are not delegation and are left out. An *agent PR* is a PR a hangar job opened (`pr.open` job event).

### Terminal

A job is terminal at the first of: its PR merged (`pr.merge`), its PR closed unmerged (`pr.close`), or it was
abandoned (`abandon`, that is, cancelled). A job with no PR is terminal when its last run's `job_state` is
`succeeded`, `failed` or `cancelled`.

### Counted

A terminal job counts when it ran at least one turn and its last run's `outcome_class` is not `infra_error`
(hangar#166). A job cancelled before it started does not count. Infra-error runs are reported as a count next to the
metrics, never silently dropped.

### Intervals

Rates come with a Wilson 95% interval (`flightdeck.stats.core.wilson`), always printed with `k` of `n`, because six
people give small numbers. The markdown shows the week next to the three weeks before it.

### Scope

`--person` and `--repo` narrow every job-based metric. Per-person numbers are for that person and admins only
(hangar's owner scoping): printed, never written to the shared report files. The Slack team view is team-wide. Agent
share is team or repo scope only.

## The metrics

| Metric | Target | View |
| --- | --- | --- |
| [Agent PR yield](#yield) | ≥ 60% | `weekly_yield` |
| [Agent share of merged PRs](#agent-share) | | `weekly_agent_share` |
| [Review wait](#review-wait) | p50 < 4 h, p90 < 24 h | `weekly_review_wait` |
| [Green to merge](#green-to-merge) | | `weekly_green_to_merge` |
| [Human steers per merged PR](#steer-rate) | | `weekly_steer_rate` |
| [Abandon rate](#abandon) | < 25%, with a reason | `weekly_abandon`, `weekly_abandon_reasons` |
| [14-day revert rate](#revert) | | `weekly_revert` |
| [Cost per merged PR](#cost-per-merged-pr) | | `weekly_cost_per_merged_pr` |
| [Active delegators](#active-delegators) | 6 of 6 | `weekly_active_delegators` |

### Yield

Agent jobs whose PR merged ÷ counted agent jobs that became terminal in the week. A rate, with its interval.

### Agent share

PRs merged in the week that a hangar job opened ÷ all PRs merged in the week on the team's repositories. The
denominator is the `prs` table, from GitHub, humans' and bots' PRs included. An agent PR is matched by its URL.

### Review wait

Hours from the agent PR opening (`pr.open`) to its first counting review (`review.first`: the first approval hangar's
landing counts, bots excluded), for agent PRs first reviewed in the week; p50 and p90. Until hangar records the time
a draft is marked ready (hangar#168 `ready_at`), a PR opened as a draft includes its draft time.

### Green to merge

Hours from the PR's checks going green to its merge (hangar's `green_to_merge_seconds` on `pr.merge`), for agent PRs
merged in the week; p50 and p90.

### Steer rate

Human touches on the agent jobs merged in the week ÷ those jobs. A touch is a steer or interrupt during a turn
(`run.json` `steers.n`), or a question the agent asked that a person answered (`questions`). A follow-up turn, every
job turn after the first, is a touch too. Corrections-only counts follow once hangar classifies steers (hangar#162).

### Abandon

Counted agent jobs terminal in the week that were abandoned or whose PR closed unmerged ÷ the same denominator as
yield. Broken down by hangar's abandon reason: `wrong_approach`, `bad_ticket`, `flaky_env`, `too_big`, `superseded`,
`other`. A closed PR or cancelled job without one is `unlabelled`.

### Revert

Take the agent PRs merged two weeks earlier. The rate is those a PR merged within 14 days of them reverts ÷ all of
them. The lag makes every PR in the cohort old enough for its 14 days.

A revert is a PR whose body is GitHub's revert-button text (`Reverts owner/repo#N`), says
`This reverts commit <sha>` for the PR's merge commit, or is titled `Revert "<title>"`. Reverts pushed straight to the
branch are not seen until hangar emits `revert` job events.

### Cost per merged PR

The summed `cost_usd` of every run of the agent jobs merged in the week ÷ those jobs. Review jobs (hangar#161) are
separate jobs, and not included until they link to the job they review.

### Active delegators

People with at least 3 agent PRs merged in the week, out of the people with an agent job run that week.

### Infra errors

Runs in the week whose `outcome_class` is `infra_error`: left out of yield and abandon, and reported as a count so
the exclusion is visible.

## Where the data comes from

The decision recorded for #6: facts hangar knows come from hangar, facts only GitHub knows come from GitHub.

| Data | Source | Table |
| --- | --- | --- |
| Jobs, runs, cost, steers, outcome class | hangar's outbox `run.json` | `runs` |
| PR opened, first review, merged (with green-to-merge), closed, abandoned (with reason) | hangar's outbox job events | `job_events` |
| All merged PRs on the team's repos, reverts | GitHub REST, nightly (`flightdeck ingest github`) | `prs` |

The issue's alternative, hangar emitting review and revert job events, is half taken. hangar already emits
`review.first` and has reserved a `revert` event. When hangar emits `revert`, the revert view switches to it, and the
`prs` table remains only for agent share.

## See also

- [Data plane](data-plane.md#flightdeckweeklyv1): the `flightdeck.weekly/v1` files this command writes.
- [Statistics](statistics.md#functions): the Wilson interval on every rate.
- [Contracts](contracts.md): the `runs`, `job_events` and `prs` columns.
