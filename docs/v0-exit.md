# Has flightdeck v0 met its exit criteria?

Not yet. Two of the four criteria hold today, and one waits for a paid run. This page checks each criterion of
epic [#1](https://github.com/Sean-Koval/flightdeck/issues/1) against `main`, as of Nov 18, 2026 (KAN-87).

| Criterion | Status | Evidence |
| --- | --- | --- |
| The line budget's CI job is green | Holds, with no room left | 3,875 of 3,875 counted lines (below) |
| No sandbox, credential or provider code, apart from the local runner | Holds | `tests/test_boundary.py`, ADR 0001 |
| #20 records one real decision as an ADR | Waits for the paid run | [ADR 0011](decisions/0011-first-decision-plugin-ab.md), Proposed |
| Every child is closed or moved with a reason | Not yet: four open v0 children have shipped their code | The children table below |

## The line budget

`python scripts/loc_budget.py` counts non-blank, non-comment lines under `src/flightdeck/`, leaving out
`ported/`. CI's `loc-budget` job runs it on every pull request.

| Area | Counted lines |
| --- | --- |
| `specs/` | 832 |
| `dataplane/` | 721 |
| `runners/` | 696 |
| `tasks/` | 684 |
| `stats/` | 385 |
| `report/` | 206 |
| `metrics/` | 148 |
| `judges/` | 142 |
| top level | 61 |
| **Total** | **3,875 of 3,875** |
| `ported/` (not counted) | 1,237 |

The limit has moved by ADR each time. It was 2,500 in [0003](decisions/0003-line-budget.md) and 2,800 in
[0004](decisions/0004-local-runner-budget.md). Then 3,785 in [0005](decisions/0005-post-v0-budget.md), 3,850 in
[0009](decisions/0009-label-and-integrity-budget.md) and 3,875 in [0010](decisions/0010-default-specs-budget.md).
The epic's original "1,500 non-test lines" is out of date. The criterion now reads "CI's `loc_budget` job is green".

There are no lines banked. ADR 0010 says the next growth pays with a cut. The planned cut is the SQL step
labeller, once the trace compiler is the labeller of record (KAN-269, KAN-208).

The flightdeck#20 run needs no counted lines. Its runner is `scripts/decision_run.py`, which only calls the CLI.

## The children

Every v0 child has merged code except #12 and #20. The ones still open:

| Child | State | What is left | Proposed action |
| --- | --- | --- | --- |
| #12 Regression v1 | Open, no code | 20 labelled failures (KAN-25), then mining (KAN-88) | Move to P4 with that reason; regression-v0 stands in |
| #13 Holdout custody | Code merged (#52) | Seal the first set (KAN-89) | Close; live work is KAN-89 |
| #15 Spec runner | Code merged (#41) | A team ADR with `checks:` and the nightly job (KAN-91) | Close; live work is KAN-91 |
| #16 Mutation scoring | Code merged (#53) | A live run (KAN-92) | Close; live work is KAN-92 |
| #20 One real decision | Ready to run | The paid run (KAN-223), then ADR 0011's verdict | Close with the verdict |
| #21 Knowledge gold set | Code merged (#54) | Write and seal 40 questions (KAN-90) | Close; live work is KAN-90 |
| #23 Cleanup | Code merged (#91, KAN-93) | Nothing in this repository | Close |

The P4 and backlog children (#25 to #36) are already in later milestones. They wait for #20 by design, so they need
no action.

## What closes v0

1. A person runs the flightdeck#20 run: `python scripts/decision_run.py preflight`, then `start` and `finish`
   (ADR 0011). That needs a funded API key and a Docker hangar (KAN-223).
2. ADR 0011 moves to Accepted with the verdict and the report link.
3. Sean closes or moves the children above, and updates the epic's line-budget criterion.

## See also

- [ADR 0011](decisions/0011-first-decision-plugin-ab.md): the decision, the suite and how to run it.
- [Contributing: the line budget](https://github.com/Sean-Koval/flightdeck/blob/main/CONTRIBUTING.md#the-line-budget).
