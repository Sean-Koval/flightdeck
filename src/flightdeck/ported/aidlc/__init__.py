"""ai-dlc's local Docker evaluation runner, ported for flightdeck's local backend (#18; docs/local.md).

From ai-dlc's handoff commit f5be4f4206a8469f17d4b54296e41e06a2d1a41e (tag eval-handoff-2026-10). Kept, each with a
caller in flightdeck (KAN-93 checked; ai-dlc deleted its copy in ai-dlc#195, so these are the only copies):

- `attempt.py`, `drivers.py` (the deterministic driver), `git_observer.py` and `evidence.py` (the evidence
  manifest): the attempt lifecycle behind `flightdeck.runners.local`;
- `contracts.py` (`Scenario` and `Suite`) and `planning.py` (the suite checks): `flightdeck task import-aidlc` (#17).

Removed in KAN-93 with the unqualified real-client path: `budgets.py`, `test_proxy.py`, the Claude Code driver, the
egress proxy, credential redaction, the Git assertion evaluator and the contract models nothing read.
Each file keeps ai-dlc's MIT notice and lists its changes. The flightdeck side, tasks in and data-plane rows out, is
`flightdeck.runners.local`, which counts against the line budget.
"""
