# Tasks

A task is graded work: an instruction for the agent, the environment it works in, and hidden tests that decide the
reward.

flightdeck's format is [Harbor](https://github.com/harbor-framework/harbor)'s task directory. So public Harbor
datasets (Terminal-Bench and others in Harbor's registry) load without a converter, and flightdeck's tasks run on
Harbor. hangar's spec 0008 chose this format for graded work; flightdeck owns it. Code: `src/flightdeck/tasks/`.

<figure class="af-figure" markdown>
--8<-- "docs/assets/task-anatomy.svg"
<figcaption>One directory: the agent gets the instruction and the environment, and the hidden tests grade its patch</figcaption>
</figure>

## Layout

```
<task-id>/
  task.toml          Harbor's config (schema 1.4) plus flightdeck's keys under [flightdeck]
  instruction.md     what the agent gets, verbatim
  environment/       a Dockerfile for the local runner and Harbor (hangar trials use [flightdeck] environment)
  tests/             hidden: never given to the agent; tests/test.sh writes the reward
  solution/          optional oracle (solve.sh; reference.patch for hangar's base check), never mounted for agents
```

`task.toml`, as flightdeck reads it. Harbor's own keys stay where Harbor puts them (its docs:
[task configuration](https://docs.harborframework.com/tasks/configuration)); Harbor ignores the `[flightdeck]` table.

```toml
schema_version = "1.4"

[task]                     # Harbor: optional; `name` (org/name) is required when present. The id is name's last part,
name = "flightdeck/semver" # else the directory's name (older Harbor tasks have no [task] and a top-level `version`)
version = "1.0.0"
description = "..."        # hangar's task title

[agent]
timeout_sec = 1800.0

[verifier]
timeout_sec = 600.0        # the grader's timeout on hangar (30..3600 s)

[flightdeck]
tags = ["smoke"]
sealed = false             # sealed tasks never live in this repository (docs/holdouts.md); the local runner refuses them
environment = "bare"       # the hangar environment trials run in
# mined_after = "YYYY-MM-DD"  # holdout tasks: when the mined work merged (docs/holdouts.md); mined_from: mining work

[flightdeck.source]        # what hangar checks out: repo, base_sha (40 hex), base_branch, issue, verify
repo = "https://github.com/OWNER/REPO.git"
base_sha = "..."

[flightdeck.grader]
command = "bash tests/test.sh"   # run from the task's directory
files_digest = "sha256:..."      # of tests/*, written by `flightdeck task digest --write`
```

The issue's `[source]`, `[grader]` and `[task] id` moved under `[flightdeck]` for Harbor's sake. Harbor's `source` is
a top-level string and its `[task]` requires `name`, so those tables would make a flightdeck task invalid for Harbor.
Harbor's `[agent]` and `[verifier]` timeouts replace `timeout_min` and `timeout_s`.

Not supported yet: Harbor's multi-step tasks (`[[steps]]`) and Windows `test.bat`, refused with a message.

## Commands

```sh
flightdeck task new tasks/regression/fix-retry   # from the template: safe test.sh, placeholder hidden test
flightdeck task check tasks/smoke/semver ...      # layout, symlinks, files_digest, hangar's limits
flightdeck task digest [--write] tasks/smoke/semver
```

## Digests

### task_digest

`task_digest = sha256(canonical task.toml, instruction.md, tests/*, environment/*)` is the trial-result cache key
(#24). Each part is hashed as `name \0 length \0 bytes`, files sorted by relative path. `task.toml` is canonical JSON:
sorted keys, no comments or formatting, `files_digest` left out.

Text files get LF newlines before hashing, so a Windows checkout hashes the same. `__pycache__` and `*.pyc` are
skipped; symlinks are refused.

### files_digest

The same hash over `tests/*` alone, recorded in `task.toml`. `load_task` refuses a task whose tests no longer match
it, so a changed hidden test is always a deliberate, reviewed edit.

## On hangar

`to_hangar(tasks)` builds a `hangar.experiment/v1` spec's `tasks` and its one `grader` (hangar `experiments.py`).
Each task's tests go into `Grader.files` as `<id>/tests/...`. The command starts
`cd "$HANGAR_HIDDEN_TESTS/$HANGAR_TASK"`, its task's pristine copy.

Grader commands may differ: one shared command `eval`s each task's own, by a `case` on `$HANGAR_TASK`.

Ids match `^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$` (longer ones get a stable short form). Instructions take 64,000
characters, a reference patch 1 MB. A grader takes 64 text files, 1 MB, a 4,000-character command. A larger
suite is split ([Runners](runners.md)); one task over a cap is refused.

A task with `environment/workspace/` and no `[flightdeck.source] repo` is refused: hangar would run the
environment's repo.

hangar runs the grader in a sealed sandbox (no credential, egress `none`), writes the files outside the repo and adds
a canary comment to each. A `test.sh` command is recorded as `trust: low`, since hangar can only vouch for its own
`hangar-grade pytest` runner. The safe pattern below is what keeps such a grade honest.

## Writing a safe test.sh

A trial's patch can try to forge its grade. It can write the reward file. Or it adds a `conftest.py`, pytest settings,
`sitecustomize.py` or a `.pth` file, run before the hidden tests (hangar spec 0014 §6). The template does this:

1. Find things by environment. The agent's tree is `$FLIGHTDECK_WORKDIR`, else `$HANGAR_REPO`, else the current
   directory (Harbor). The hidden tests are the script's own directory. The reward goes to
   `$FLIGHTDECK_REWARD_DIR/reward.json`, else `/logs/verifier/reward.json` (Harbor), and to `$HANGAR_GRADE_OUT` when
   set.
2. Copy the tests and only the code under test to a fresh directory outside the agent's tree, before any of the
   agent's code runs.
3. Run Python isolated: `python3 -I -m pytest --noconftest -p no:cacheprovider -c /dev/null -o addopts=` with
   `PYTHONNOUSERSITE=1` and `PYTHONPATH`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` unset.
4. Compare against expected output, not against anything the agent produced.
5. Write the reward last. Harbor's `reward.json` takes numbers only (`{"reward": 1, "passed": 116, "total": 116}`);
   richer detail goes to stdout and `$HANGAR_GRADE_OUT`. Exit non-zero when the reward is 0, since hangar reads the
   exit code.

Code under test still runs inside the test process and can lie through it. hangar's base-must-fail check (a
`solution/reference.patch` must pass, the base must fail), canaries and `touched_tests` are the detectors for that.

## Shipped tasks and imports

- <span id="the-semver-smoke-task"></span><span id="the-csv-validator-fixture"></span>[The two public tasks](task-fixtures.md):
  the semver smoke task and the csv-validator fixture.
- <span id="importing-ai-dlc-scenarios"></span>[Importing ai-dlc scenarios](task-import.md): `flightdeck task import-aidlc`
  turns an ai-dlc suite into tasks, specs and a suite file.

## Next

- [Running experiments](runners.md): the suite file that names tasks, and the local backend that runs them.
- [Holdouts](holdouts.md): tasks written blind and sealed, with `sealed = true`.
- [Behavior specs](behavior-specs.md): the specs an import writes beside the tasks.
- [Concepts](concepts.md): check against grader, task against trial.
