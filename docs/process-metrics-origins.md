# Where the process metrics came from

The [process metrics](process-metrics.md) are ported from hangar's `evals/semver` kit, built for its 2026-10-12
harness comparison. That kit parsed pi and Antigravity logs; hangar's trace export now does that for every harness.
`tests/test_process_metrics.py` checks the views against the kit's `metrics.py` and `classify.rule()` on one trial.

## Differences from hangar's kit

- **No LLM call count.** Traces record a run's tokens and cost, not each model call.
- **Test runs need a runner at a command position.** The kit matched `pytest` or `unittest` anywhere. So
  `pip install pytest` was a test run, and so was an edit whose path named pytest.
- **Setup has a label, and a call has every label it earns.** The kit gave one label and called installs `other`.
- **Plan tools have a label.** The kit called them `other`.
- **No model labeller.** The kit could also ask a model (Microsoft Decision-1, through OpenRouter) for each label.
  flightdeck holds no model credentials ([ADR-0001](decisions/0001-boundary-with-hangar.md)). Model labels wait
  for a calibrated [judge](judges.md).
- **Wall time** is the run's start to its end, not its first span to its last.
- **SDLC labels are new.** The kit had no `pr`, `ci_wait`, `review` or `tracker` label.

## Next

- [Process metrics](process-metrics.md): the views and their columns.
- [Label gold sets](label-gold-sets.md): how often labels are right.
