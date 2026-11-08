# 0009: Raise the line limit to 3,850 for the step-label and process-integrity work

Status: Accepted (owner-chosen 2026-11-08) · Nov 8, 2026 · KAN-175 (#93)

## Context

[ADR 0008](0008-cleanup-after-the-ports.md) kept `LIMIT` at 3,785 and banked 66 lines, which left main at 3,719.

Two pieces of work then spent the bank separately. KAN-272 and KAN-273 (#94, #95) made step labels count every
part of a call and score them against a gold set. They took main to 3,766. KAN-175 (#93) hardened process evidence:
duplicate rows count once, unknown results finish no fix loop, and `conservative-v1` partial observations. It
measured 3,785 on its own.

Merged together they count 3,832 lines, 47 over the limit, so CI's budget check fails on #93.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Cut 47 lines | Find savings across `specs/`, `metrics/` and `dataplane/` | The limit holds | A refactor of shipped code to pay for a merge, with no behavior gained |
| B. Raise the limit a little | `LIMIT` to 3,850: the merged total plus 18 lines | Both changes land as reviewed; the next small fix fits | The budget grows for the first time since ADR 0005 |

## Decision

B, the owner's choice.

1. `LIMIT` in `scripts/loc_budget.py` is 3,850.
2. Measured with #93 merged: 3,832 counted lines, so 18 lines are banked.
3. Growth past 3,850 needs a new ADR, as before.

## Consequences

- #93 can merge without a refactor, and the labeller and integrity rules stay as reviewed.
- The bank is small. Work that needs more than 18 lines pays with a cut or its own ADR.
- Revisit when trace compiler becomes the labeller of record (KAN-269): the SQL labeller's lines may then go.
