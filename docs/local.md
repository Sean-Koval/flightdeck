# Local runs

`flightdeck experiment run <suite> --backend local --data <dir>` runs every trial of the suite now, one after another,
in Docker on this machine. It writes them into the data plane at `<dir>` with `source = local`.

It is for fixtures and CI; this repository's own CI runs `tasks/fixtures/local.yaml` on every PR. It is never for
team tasks: a task with `sealed = true` or `mined_from` set is refused. Team tasks and every model trial run on
hangar, where credentials and egress policy live.

There is no cost gate: the only driver makes no model calls and spends nothing. `status` and `collect` recognize a local run set by its `local-` prefix and read its evidence from
`<dir>/raw/<run-set>/`.

The isolation is ai-dlc's evaluation runner, ported at its handoff commit `f5be4f4` (`src/flightdeck/ported/aidlc/`,
each file listing what changed). The flightdeck side is `src/flightdeck/runners/local.py`.

## Environment

The task's `environment/Dockerfile` is built to an image id. Or `[environment] docker_image`, which must be pinned by
digest, is used as is and never pulled. The project is the image's working directory (`[environment] workdir`, else the
image's `WORKDIR`). The image needs `git`.

## Attempt

A controller-owned stager copies the working directory into a per-attempt volume, dropping any `.git`. The controller
commits it as a fixed anchor (`refs/flightdeck/anchor`, neutral author, fixed date).

The agent's container runs as uid 1000 with `--read-only --cap-drop=ALL --security-opt=no-new-privileges`, memory
and process limits, tmpfs `/tmp` and home, and `--network=none`. Nothing from the host is mounted.

After the agent stops, a separate read-only collector copies the volume out. Then every container and volume is
removed; `cleanup-ledger.jsonl` names any that weren't.

## Grading

The task's `tests/` stay on the controller. The grader command (`[flightdeck.grader] command`) runs on the collected
tree in a fresh container with no network and the same isolation. It gets `FLIGHTDECK_WORKDIR` and
`FLIGHTDECK_REWARD_DIR` ([Tasks](tasks.md#writing-a-safe-testsh)). Its `reward.json` is kept beside the trial's
evidence and in `grades.data`; its exit code is `grades.exit_code`.

## Driver

A variant's `harness` must be `deterministic`; any other harness is refused before anything runs.

`deterministic` makes no model calls. It runs the task's `solution/deterministic.json` (ai-dlc's script format:
`{"steps": [argv, or {"write": path, "from": file}]}`, one command per step), else Harbor's oracle (copy `solution/`
in, run `solve.sh`).

The port's `claude-code@<version>` driver was removed in KAN-93. It was never qualified against a live model, and
model trials belong on hangar ([ADR 0008](decisions/0008-cleanup-after-the-ports.md)).

## Rows

A local run set reads like a hangar experiment to `stats compare`, reports and specs (`experiment_id` = the run set
id):

| Table | From |
| --- | --- |
| `runs` | one per trial: `outcome` `succeeded` (the attempt completed), `failed` (`outcome_class = infra_error` when provisioning, staging or a resource limit failed; else timeout, cancellation or damaged evidence, in `reason`); `diff_files` from the Git observer; `truncated` when the attempt or the observation is incomplete, so specs answer `unknown` rather than pass |
| `grades` | the grader's exit code, seconds, `reward.json` and the tests' `files_digest` |
| `spans` | one `tool.call` per deterministic step (`tool_kind` `shell`, or `edit` for a file write). Each has hangar's `tool_kind` and `shell_ops` (ported from hangar's `traces.py`) and `seq` in order |
| `events` | one `git.commit` per post-anchor commit the Git observer confirms, placed after the step that made it |
| `test_cases` | one trusted `test.run` per deterministic step whose command is a test (`total` from unittest's or pytest's summary) |

Trust follows hangar's rule. A `test.run` is trusted because the controller ran the command and read its result,
which the agent can't fake.

So `tests-before-commit` evaluates on local runs. On `tasks/fixtures/local.yaml`, the csv-validator script tests
before committing (`pass`) and semver's `solve.sh` commits without testing (`fail`). A step that both tests and
commits counts the test first, unless its command commits first.
