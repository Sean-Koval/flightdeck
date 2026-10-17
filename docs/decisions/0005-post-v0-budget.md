# 0005: The post-v0 batch is counted, and the budget rises by each piece's measured size

Status: Accepted · Oct 17, 2026 · amended by each PR of the batch below (last: #24) (agent-proposed; owner review requested)

## Context

ADR 0004 left the v0 budget at 2,800 counted lines with 17 to spare (2,783). The next unblocked issues all add new
flightdeck code, not ported code:

- #17: `flightdeck task import-aidlc`, which turns ai-dlc scenarios into task directories and specs. ai-dlc's
  contracts and suite checks go to `ported/aidlc/` uncounted (ADR 0004 rule 1), but nothing in ai-dlc wrote Harbor
  tasks or flightdeck specs, so the converter is new code.
- #13 (holdout custody), #16 (mutation scoring), #21 (knowledge gold-set scoring): v0-plan pieces, scheduled after v0.
- #24 (trial-result cache and drift sentinel) and #27 (rubric judges, PPI): P4 frontier pieces, each gated.

ADR 0004 says the next piece that doesn't fit is a signal to cut. Each PR of this batch looks for cuts first and
records them here. The cuts so far:

- `stats/__init__.py` re-exported `stats.core` (14 lines of duplication); callers import `stats.core` (#17).
- `applies_when` matched `source` and `repo` with two special cases; one glob rule over the `runs` columns replaces
  both and covers `task_id` and `variant` too, for a few lines less (#17).
- #13 found no cut in what it touches; it moved `task digest --write`'s logic into `tasks/format.py` so sealing
  reuses it instead of adding a third copy.
- #16 reuses `stats compare`, `pass_hat_k_suite`, `wilson`, the spec SQL compiler and `experiment run`'s cost gate
  rather than adding its own; no cut found in `specs/`.
- #21 reuses the custody manifest, canaries and `canary-scan` for the gold set instead of a second sealing scheme;
  no cut found.
- #24 lets `load_trials` take a run set, so `holdout score` and `mutate score` drop their own loops over experiment
  ids (two lines); no larger cut found.

Cuts considered and not taken:

- The local runner's real-client path (`claude-code@<version>`: stream parsing, credentials, run budget; about 55
  lines in `runners/local.py`). It is unqualified, but ADR 0004 hands that call to #23 once ai-dlc#223 merges; cutting
  it here would reverse #50 hours after it merged.
- Code in `ported/`: shrinking it changes nothing counted, and moving flightdeck code there is the dodge CONTRIBUTING
  forbids.
- Compressing reviewed code to fit: ADR 0003's option B, already rejected.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. One ADR per PR | Each issue argues its own raise | Smallest steps | Six ADRs saying the same thing; reviewers lose the total |
| B. One ADR for the batch, amended per PR | Each PR adds its measured size to the table below and moves the limit by exactly that | One place shows the total and every cut; no headroom is granted in advance | The ceiling moves several times in a day |
| C. A separate budget for frontier (P4) code | v0 stays at 2,800; #24 and #27 count elsewhere | Keeps the v0 number | A second number is still a raise; the boundary between v0 and frontier code is soft |

## Decision

B.

1. Every PR of the batch (#17, #13, #16, #21, #24, #27) first looks for cuts and records them above, then measures its
   net counted lines with `scripts/loc_budget.py` and adds a row to the table. `LIMIT` in `scripts/loc_budget.py`
   moves to the new total, with no headroom.
2. Frontier code counts like v0 code. A UI, a server or a database stays out regardless of room (ADR 0003).
3. If the batch's total passes 3,800 counted lines, stop and revisit: either cut a piece or split the package.
4. Any piece outside this batch needs its own ADR.

| PR | Issue | What it adds | Net counted lines | Limit after |
| --- | --- | --- | --- | --- |
| (ADR 0004) | #18 | the local runner's adapter | | 2,800 |
| #51 | #17 | `tasks/aidlc.py` and `task import-aidlc` (+131); the `any` path operator and `task_id`/`variant` scope in specs, after the `applies_when` cut (-4); the stats re-export cut (-14) | +113 | 2,896 |
| #52 | #13 | `tasks/custody.py`: manifest, seal, canary scan, score once, briefs, and the `holdout` CLI (+204); `write_digest` moved to `tasks/format.py` so the CLI, the importer and sealing share it (+1); registration (+2) | +207 | 3,103 |
| #53 | #16 | `specs/mutate.py`: operators, plan, run through the cost gate, kill scoring and the survivors' report (+167); `stats compare` no longer fails when no trial has a known cost (+1); registration (+2) | +170 | 3,273 |
| #54 | #21 | `tasks/knowledge.py`: seal, citation classes, correctness by raters, the paired report and the 15-point rule (+130); `cohen_kappa` in `stats/core.py`, which #27's calibration reuses (+10); `custody.save` creates its directory (+1); registration (+2) | +143 | 3,416 |
| #55 | #24 | `runners/cache.py`: key, lookup, plan reduction, reuse rows, `cache drop` and the drift sentinel (+148); `--cache` in `experiment run` and digest stamping in both backends (+21); `load_trials` reads run sets and reused trials once each, and `stats compare` reports them (+12); schema and registration (+3) | +184 | 3,600 |

## Consequences

- The total and its history live in one table, so the cost of each post-v0 piece stays visible next to its cuts.
- `ported/` keeps growing uncounted (#17 adds ai-dlc's contracts and suite checks); `loc_budget` prints it beside the
  total.
- #23 should re-check the real-client path and the importer once ai-dlc#195 removes ai-dlc's copy.
