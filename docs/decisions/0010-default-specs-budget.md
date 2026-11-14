# 0010: Raise the line limit to 3,875 so the team-default spec fixes fit

Status: Accepted (owner-chosen 2026-11-11) · Nov 11, 2026 · KAN-386 (#104)

## Context

[ADR 0009](0009-label-and-integrity-budget.md) set `LIMIT` to 3,850 and banked 18 lines.

KAN-309 (#100) then filled the new trace columns and took main to 3,833. KAN-311 (#104) stops the team-default specs
failing a good job. It adds `paths.ignore` and the `applies_when.approvals` unit key, written once in the Python
evaluator and once in SQL.

Merged together they count 3,867 lines, 17 over the limit, so CI's budget check fails on #104.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Split #104 | Land the two spec keys in separate PRs | Each PR is smaller | Both halves are one feature in two evaluators, so the total is the same |
| B. Cut 17 lines | Find savings across `specs/`, `metrics/` and `dataplane/` | The limit holds | A refactor of shipped code to pay for a merge, with no behavior gained |
| C. Raise the limit a little | `LIMIT` to 3,875: the merged total plus 8 lines | The default specs stop failing good jobs now | The second raise in a week |

## Decision

C, the owner's choice.

1. `LIMIT` in `scripts/loc_budget.py` is 3,875.
2. Measured with #104 merged: 3,867 counted lines, so 8 lines are banked.
3. The next growth past 3,875 pays with a cut, not another raise.

## Consequences

- #104 can merge as reviewed, and the team-default specs pass a good job.
- The bank is 8 lines, so the next change of any size needs a cut first.
- The planned cut: once trace compiler is the labeller of record and connected (KAN-269, KAN-208), the SQL
  labeller's lines go. That pays this raise back.
