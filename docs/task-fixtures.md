# The two public tasks

Which tasks ship with flightdeck? Two: a smoke task that runs on hangar, and a fixture for the local runner. Both are
synthetic, and both come with a reference solution that scores full marks.

| Task | Where | Hidden tests | Runs on |
| --- | --- | --- | --- |
| semver | `tasks/smoke/semver/` | 116 cases in 13 categories | hangar, and the local backend |
| csv-validator | `tasks/fixtures/csv-validator/` | 10 acceptance tests | the local backend |

## The semver smoke task

`tasks/smoke/semver/`, ported from hangar `evals/semver`: build a Python semver library with node-semver range
matching. It has 116 hidden unittest cases in 13 categories, generated from node-semver 7.8.5's answers
(`generator/`: `node oracle.js > oracle.json`, `python3 gen_hidden.py`).

`test.sh` copies only `semver.py`, runs the hidden tests with pytest when the environment has it (else unittest),
writes `reward.json` and prints `RESULT {passed, total, by_category, failed}`. `solution/semver.py` is a reference
that scores 116 of 116. Every hangar trial so far scored 116 of 116, so it tests the plumbing, not the agents.

To run it on hangar, set `[flightdeck.source] repo` and `base_sha` to an empty repository's first commit. hangar
applies and grades a trial's patch only on a repo.

## The csv-validator fixture

`tasks/fixtures/csv-validator/` is ai-dlc's evaluation fixture, the one its runner was qualified on: add duplicate-row
detection to a small CSV validator. It comes from `evaluations/suites/smoke.json`, scenario `csv-duplicate-rows`, at
ai-dlc's handoff commit `f5be4f4`.

The scenario's fixture is `environment/workspace/`, copied into the image's working directory. Its 10 hidden
acceptance tests are `tests/test_acceptance.py`, run by `test.sh` on a copy of the agent's `csvcheck/` package only.
Its reference is `solution/validate.py`.

`solution/deterministic.json` is the local runner's deterministic script: write the reference, run the fixture's own
tests, commit. `solve.sh` does the same for Harbor's oracle.

It lives under `tasks/fixtures/`, not `tasks/smoke/`, so the hangar smoke suite doesn't grow. It needs
`[flightdeck.source] repo` and `base_sha` before it can run on hangar. `tasks/fixtures/local.yaml` runs it and the
semver task on the [local backend](local.md).

It was converted by hand; [`flightdeck task import-aidlc`](task-import.md) now does the same for any ai-dlc suite.

## Next

- [Tasks](tasks.md): the layout and digests both tasks follow.
- [Local runs](local.md): the backend that runs `tasks/fixtures/local.yaml`.
- [Importing ai-dlc scenarios](task-import.md): the same conversion, by command.
