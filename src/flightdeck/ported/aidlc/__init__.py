"""ai-dlc's local Docker evaluation runner, ported for flightdeck's local backend (#18; docs/local.md).

From ai-dlc's handoff commit f5be4f4206a8469f17d4b54296e41e06a2d1a41e (tag eval-handoff-2026-10): the attempt
lifecycle (`attempt.py`), drivers (`drivers.py`), the controller's Git observer (`git_observer.py`), run budgets
(`budgets.py`), evidence sealing (`evidence.py`) and the egress proxy (`test_proxy.py`, copied: ai-dlc keeps its own);
and for `flightdeck task import-aidlc` (#17) the evaluation contracts (`contracts.py`) and the suite checks from
planning (`planning.py`).
Each file keeps ai-dlc's MIT notice and lists its changes. The flightdeck side, tasks in and data-plane rows out, is
`flightdeck.runners.local`, which counts against the line budget.
"""
