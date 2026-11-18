# Design: a cheap A/B (KAN-233)

This page is for whoever builds KAN-233: how one pre-registered A/B drops from about $240 to about $70, and what
each saving costs. It is a proposal; nothing here is built.

## The cost today

One A/B is 20 tasks × 3 trials × 2 arms at about $2 a trial on Opus, so about $240. Ten of them would pass the
$1,500 monthly eval cap. Four changes cut that price, and each needs a guard so the answer stays honest.

| Change | Saves | Guard |
| --- | --- | --- |
| Reuse the control arm | the control's ~$120 | a fresh 5-task sentinel and `drift()` |
| Select mid-band tasks | 44–70% of the tasks | select on trials the analysis doesn't use |
| One futility look | the third trial of a losing candidate | futility only, never early success |
| Symmetric cost cap | the long tail of expensive trials | the same cap on both arms, cached ones too |

## 1. Reuse the control arm

The control arm comes from hangar's trial cache (`trialcache.py`, `POST /api/trials` with `reuse: {min_trials: 3}`)
when its pin set is unchanged. Cached trials cost nothing against the eval budget. KAN-224 deletes flightdeck's
own `lookup()` in KAN-94's PR, so this design reads hangar's cache.

A silent provider change keeps every cache key the same. So five of the selected tasks also run a fresh control, at
about $10. `drift()` compares those fresh trials with the cached ones, and a drift stops the analysis before the
comparison is read.

## 2. Select mid-band tasks

A task the control always or never solves says almost nothing about a lift. The run keeps only
tasks whose control pass rate is 30–70%. The Mid-Range Difficulty Filter cuts 44–70% of tasks at a rank correlation
of about 0.95 ([arXiv 2603.23749](https://arxiv.org/pdf/2603.23749)).

```sh
flightdeck tasks select --band 0.3,0.7 --min-trials 3
```

It writes a task list from cached control history and records the band in the pre-registration.

The trap is selecting and measuring on the same trials. A task picked at a cached 30% regresses toward its true
rate, so a control measured on those trials looks worse than it is. Selection reads only cached trials older than
the ones the control arm reuses, and a task needs 3 of them.

## 3. One futility look

After 2 of 3 trials, `stats compare` takes one pre-registered look. If the candidate isn't ahead (the paired mean
difference is at most 0), the run stops and reports futility. Otherwise the third trial runs and the usual test
decides. This follows [Inspect's early stopping](https://inspect.aisi.org.uk/early-stopping.html) and
[arXiv 2607.17409](https://www.alphaxiv.org/abs/2607.17409).

The look can stop for futility, never for success. A futility-only stop can't raise the false-positive rate, so the
final boundary stays a one-sided test at 2.5%. It does cost power, which the simulation below has to measure.

## 4. A symmetric cost cap

With `cap: p90`, the runner sets `trial_budget_usd` to the control's p90 cost per trial. A capped trial counts as
unresolved, at a cost equal to the cap. It is never excluded, since dropping it would hide exactly the trials the
candidate made expensive.

Two places must agree:

- `compare.exclusion()` drops a truncated trace for process metrics only. A budget-stopped trial may still fall to
  `no grade or verify` or `unknown cost`; both must read it as unresolved at the cap.
- Cached control trials ran without a cap. Any that cost more than the cap count as capped too, or the cap only
  touches one arm.

## The pre-registration

The estimand changes. It is now "the effect on tasks the control solves 30–70% of the time", not the effect on the
suite. The pre-registration names the band, the futility look, the cap and the sentinel tasks before any trial runs.
`docs/statistics.md` gets the same sentence. KAN-31's first A/B is already pre-registered and keeps the old design.

## Before relying on the $70

The research agent's simulation put it near $71 at the power of 20 random tasks. Re-run it first:

- `simulate_power` draws task base rates from Beta(1.2, 1.2). A banded run needs them truncated to the band.
- It has no interim look. Add one, and run a 20,000-run A/A to show type I stays at or under 2.5%.
- Report the power lost to the look next to the money it saves.

## Line budget

`scripts/loc_budget.py` shows 3,832 of 3,850 lines today, so 18 left. The ticket allows +40 net once KAN-224's
deletion of the cache lookup lands, so this waits on KAN-94 and KAN-224. The ticket calls that change ADR 0009,
but 0009 now holds the label and integrity budget, so it needs the next number.
