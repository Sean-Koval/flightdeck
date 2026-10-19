# 0003: The v0 line budget is 2,500 lines

Status: Accepted (owner-ratified 2026-10-18), raised by [0004](0004-local-runner-budget.md) · Oct 17, 2026

## Context

The v0 budget of 1,500 counted lines under `src/flightdeck/` was set at bootstrap, before any of v0 existed, to keep
flightdeck a small analysis tool rather than a platform. The v0 scope agreed in the plan is now written and reviewed:
the data plane and stats core, ingest from hangar, `stats compare` and the report (#7, #8, #9), the behavior spec
language and nightly runner (#14, #15), the Harbor task format (#10) and the experiment submission client (#11).
Each fits on its own; together they count about 2,100 lines. No piece is optional for flightdeck v0's one goal,
changing one real team decision (#20).

## Options

| Option | For | Against |
| --- | --- | --- |
| A. Keep 1,500 and cut a v0 piece | The original number | Drops something #20 needs (the report, the specs or submission) |
| B. Keep 1,500 and compress the code | No scope cut | Denser code that is harder to review, for a number chosen before the code existed |
| C. Raise the budget to 2,500 | Matches the measured v0 scope with room for the compactor (#5) and weekly metrics (#6) | The ceiling moves once |

## Decision

C. The v0 budget is **2,500** counted lines. The rules around it are unchanged: `scripts/loc_budget.py` enforces it in
CI, ported code goes in `src/flightdeck/ported/` and is reported but not counted, and any further increase needs its
own ADR. A UI, a server or a database stays out of v0 regardless of room.

## Consequences

- The budget check passes with the v0 PRs merged, with about 300 lines left for #5 and #6.
- If #5 and #6 don't fit in what remains, that is the signal to cut, not to raise the budget again.
