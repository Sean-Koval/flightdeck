# Hangar interface fixtures

Synthetic. No team data (docs/decisions/0002-public-code-private-data.md).

| File | Produced by |
| --- | --- |
| `trace_session_good.json`, `trace_session_bad.json` | hangar's own exporter (`hangar.traces.session_export`), from the same event logs as hangar `tests/test_interfaces.py::test_behavior_specs_can_be_written_from_the_export_alone` (hangar main `f66679a`) |
| `trace_job.json` | hangar's `hangar.traces.job_export` on a synthetic job: one turn, an untrusted in-turn `pytest --collect-only` (`test.run`, trusted false, total 0), hangar's trusted verify run, delivery, PR and merge |
| `manifest_turn.json`, `experiment_index.json` | written by hand to hangar's `docs/api/manifest.schema.json` and `docs/api/experiment.schema.json`, and validated against the copies in `schemas/` by the tests |
| `experiment-spec.schema.json` | `ExperimentSpec.model_json_schema()` from hangar `src/hangar/experiments.py` at main `359675a`: the body `POST /api/experiments` accepts (its `$comment` lists the validators the schema can't express) |

Regenerate the traces from a hangar checkout when `hangar.trace/v1` gains fields; keep names and URLs synthetic
(`example`, `dev-a`).
