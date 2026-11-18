# 0011: Day-one users get the channel the flightdeck#20 run decides

Status: Proposed · Nov 18, 2026 · decision due when the run's report is posted · KAN-31 ([#20](https://github.com/Sean-Koval/flightdeck/issues/20))

## Context

flightdeck v0 must change one real decision ([#20](https://github.com/Sean-Koval/flightdeck/issues/20)). The
decision is route B: does team-default's `stable` channel move from r1 (ai-dlc workflow plugin off) to the
candidate (plugin on)?

The rule is pre-registered in team-harness `flightdeck/decision.yaml` (team-harness#1, amended by KAN-222 before
trial 1). Cost per trial is the primary, non-inferiority with a $0.40 margin. Resolved is a −20 pp guardrail. Each
task runs 3 trials per arm on `claude-opus-5-5` with `deny-risky`, and no `--cache`.

### The suite: regression-v0

The suite is regression-v0 (KAN-222): 20 tasks in team-harness `flightdeck/suites/regression-v0/`. Its
`SELECTION.md` was committed before any pull request was listed.

- Every pull request merged into main before 2026-10-29 in flightdeck, team-harness and ai-dlc, plus one-module
  hangar pull requests, that changes a test file.
- Its fix is 1 to N code files, and its test fails on the base commit and passes on the merge.
- 297 were screened. 18 passed at N = 5, and one recorded deviation (hangar's 64-file grader limit in place of a
  per-task cap) gave 20.

**Bias.** All 20 pull requests were written by coding agents, 17 of them by `claude-opus-5-5`, the model both
arms run. Absolute resolved rates will read high. The paired comparison is less affected, since both arms share the
bias. ai-dlc is missing: its pull requests could not be listed.

**Power.** 20 tasks × 3 trials detect about 24 pp on resolved at 80%. So resolved can only rule out a large
regression. "No decision on resolved, decided on cost" is an acceptable outcome.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Promote | `stable` moves to the candidate | The plugin reaches every user | Only if cost is non-inferior and every guardrail holds |
| B. Keep r1 | `stable` stays r1, the plugin stays opt-in (`@candidate`) | No unmeasured cost on every turn | The plugin's value stays unproven |

## Decision

Pending the run. Until the report is posted, day-one users get `stable` (r1, plugin off), and the plugin is opt-in
through `team-default@candidate`.

1. The outcome follows `decision.yaml`'s table, not judgement: promote only on "better" or "non-inferior" with every
   guardrail holding. Anything else keeps r1.
2. The run starts only after `python scripts/decision_run.py preflight` has no failures (below).
3. This ADR moves to Accepted with the verdict, the report link and the channel day-one users get.

## Running it

The run spends about $240-360 of model money. A person starts it:

```sh
python scripts/decision_run.py preflight --harness ~/team-harness              # free, offline
python scripts/decision_run.py start --harness ~/team-harness --data ~/plane --author sean --spend
python scripts/decision_run.py finish --harness ~/team-harness --data ~/plane --post Sean-Koval/team-harness#<PR>
```

`start` needs `HANGAR_URL` and `HANGAR_TOKEN` for a Docker hangar at main. That hangar's eval credential must be an
API key capped at $300 (KAN-223). Eval jobs start 20:00-00:15 ET, so expect 3-4 nights. `finish` refuses until hangar
reports the run set done.

### What preflight found on Nov 18, 2026

Against team-harness main `a188004`: 3 failures and 2 warnings, each a decision for Sean (KAN-223).

- **Fail, both arms:** `env.stable.yaml` and `env.candidate.yaml` set no `egress`. hangar's default is open, so a
  trial can fetch the public suite's hidden tests.
- **Fail, projection:** $360 at the default $3 a trial, over `budget_usd: 300`. Seed cost history, pass a measured
  `--assume`, or raise the budget in `suite.yaml` before trial 1.
- **Warn, revision:** the candidate renders r9, but `decision.yaml` pre-registered r4. Revisions r6 to r8 also
  changed the guard hook, so the arms differ by more than the plugin.
- **Warn, min_tasks:** `min_tasks: 20` equals the suite's size. One exclusion makes the verdict underpowered.

## Consequences

- flightdeck's v0 exit (KAN-87) closes on this ADR's verdict, whatever it is.
- If the result is "no decision", rerun once regression-v1 (KAN-88) brings the suite to 40 tasks or more.
- The suite belongs in a private data repository (ADR 0002). It is public today, so trials need restricted egress.
