# 0004: The local runner's adapter counts, and the budget becomes 2,800 lines

Status: Accepted, raised by [0005](0005-post-v0-budget.md) · Oct 17, 2026

## Context

#18 moves ai-dlc's Docker attempt runner into flightdeck as `--backend local`, for fixtures and CI. ADR 0003 set the v0
budget at 2,500 counted lines with about 300 left for #5 and #6; after they merged, 10 lines were left. The port has
two parts that are different in kind:

- **ai-dlc's runner**, kept close to its source: the attempt lifecycle, drivers, the Git observer, run budgets,
  evidence sealing and the egress proxy (about 1,390 lines under `src/flightdeck/ported/aidlc/`), plus hangar's tool
  kind and shell-op classifier (about 90 lines, `ported/hangar_traces.py`). Each file names its source commit and
  lists what changed. ADR 0003 already rules that ported code is reported and not counted.
- **The adapter**, new code written for flightdeck: a task directory in (build the environment, pick the driver,
  grade with the task's own `tests/` on the collected tree), `flightdeck.parquet/v1` rows out (runs, grades, spans,
  events, test cases), and the `--backend local` switch in the CLI. It is about 290 counted lines
  (`src/flightdeck/runners/local.py` and the CLI change). The plan scheduled this port for v0 (P3: "ai-dlc eval runner
  moved in"), but ADR 0003's measurement listed only the analysis pieces and assumed the runner would be all ported
  code. It isn't: nothing in ai-dlc wrote flightdeck's tables or read Harbor tasks.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Put the adapter in `ported/` | No ADR, under budget | Free | Not ported code; CONTRIBUTING forbids moving code there to dodge the count |
| B. Cut ~290 lines elsewhere | Keep 2,500 | The number holds | Nothing in v0 is that large and optional; compressing reviewed code to fit is ADR 0003's option B, already rejected |
| C. Count the adapter, raise the budget to 2,800 | The adapter is measured like every other new line | Honest count, the ported part stays visibly separate | The ceiling moves a second time |

## Decision

C. The adapter counts, and the v0 budget is **2,800** counted lines.

1. Code moved in from ai-dlc or hangar and kept close to its source goes in `src/flightdeck/ported/`, names its
   source commit, lists its changes, and stays uncounted. Code that adapts it to flightdeck's model is new code and
   counts.
2. 2,800 is the adapter's measured size on top of the 2,490 lines before it, with no further headroom. The next piece
   that doesn't fit is a signal to cut, as ADR 0003 said for #5 and #6.
3. Any further increase needs its own ADR. A UI, a server or a database stays out of v0 regardless of room.

## Consequences

- `scripts/loc_budget.py` enforces 2,800; the excluded `ported/` total (about 1,550 lines) is printed beside it, so the
  size of what was moved in stays visible in every CI run.
- When ai-dlc removes its copy (ai-dlc#195) there is one runner, and the cleanup issue (#23) should check whether the
  adapter or `ported/aidlc` can shrink, for example by dropping the real-client path if it never qualifies.
