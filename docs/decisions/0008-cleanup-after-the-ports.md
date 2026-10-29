# 0008: The cleanup after the ports drops the local real-client path and keeps the limit at 3,785

Status: Proposed · Oct 28, 2026 · KAN-93 (#23)

## Context

[ADR 0005](0005-post-v0-budget.md) closed the post-v0 batch at 3,785 counted lines with none to spare. Its
ratification says a line added before #20's ADR is paid for by a line cut, starting with #23's cleanup.

ADR 0005 also left one cut to #23: the local runner's real-client path (`claude-code@<version>`). ADR 0004 said to drop
it if it never qualified. It has not been run against a live model since the port, and CI never runs it.

Both removals have merged: ai-dlc's evaluation code (ai-dlc#195) and hangar's `evals/` (hangar#405, KAN-86). So
`ported/` now holds the only copies, and anything in it that nothing calls is dead code.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Keep the real-client path | Leave `claude-code@<version>` in the local backend | A local model trial stays possible | About 55 unqualified counted lines, a credential and an egress proxy in a fixtures-only backend |
| B. Drop it, keep the limit | The local backend runs `deterministic` only; `LIMIT` stays 3,785 | Frees counted lines for #20's follow-ups; model trials have one home, hangar | A local model trial needs hangar |
| C. Drop it, lower the limit | As B, with `LIMIT` at the new total | No headroom at all | The ratification banks cuts to pay for later lines |

## Decision

B.

1. The local backend runs only the `deterministic` driver. Any other harness is refused before anything runs; model
   trials run on hangar.
2. Removed with it, in `runners/local.py`: the Claude Code stream parser, the credential check and redaction, the run
   budget and the egress set-up. Measured: 3,785 to 3,719 counted lines (-66).
3. Removed from `ported/`, uncounted (1,795 to 1,237 lines): `budgets.py`, `test_proxy.py`, the Claude Code driver,
   the attempt's egress proxy, credential redaction and `evaluate_git_assertion`. `task import-aidlc` maps those
   assertions onto specs instead.
4. ai-dlc contract models no flightdeck path reads are removed, with their schemas. They are `Profile`, `Event`,
   `Report` and `BaseImage`, and their parts. `Scenario` and `Suite` stay for the importer.
5. Every remaining file under `ported/` is listed as kept, with its caller, in `ported/__init__.py`.
6. `LIMIT` stays 3,785, so 66 lines are banked. Lines added before #20's ADR merges are paid from them.

## Consequences

- `--backend local` needs no secret and no network, which matches what it is for: fixtures and CI.
- `ANTHROPIC_API_KEY` is gone from the CLI reference; `runs` rows from a local run set always have `harness =
  deterministic`.
- A local model trial would need a new ADR, a qualification run against a live model and its own lines.
- Revisit if hangar can't run a trial that a team decision needs, and only a local run could.
