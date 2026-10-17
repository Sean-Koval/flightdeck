# Tasks

A task is graded work: an instruction for the agent, the environment it works in, and hidden tests that decide the
reward. Flightdeck's format is [Harbor](https://github.com/harbor-framework/harbor)'s task directory, so public Harbor
datasets (Terminal-Bench and others in Harbor's registry) load without a converter and flightdeck's tasks run on
Harbor. Hangar's spec 0008 chose this format for graded work; flightdeck owns it. Code: `src/flightdeck/tasks/`.

## Layout

```
<task-id>/
  task.toml          Harbor's config (schema 1.4) plus flightdeck's keys under [flightdeck]
  instruction.md     what the agent gets, verbatim
  environment/       a Dockerfile for the local runner and Harbor (hangar trials use [flightdeck] environment)
  tests/             hidden: never given to the agent; tests/test.sh writes the reward
  solution/          optional oracle (solve.sh; reference.patch for hangar's base check), never mounted for agents
```

`task.toml`, as flightdeck reads it. Harbor's own keys (its docs: [task configuration](https://docs.harborframework.com/tasks/configuration))
stay where Harbor puts them; Harbor ignores the `[flightdeck]` table.

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
sealed = false             # sealed tasks never live in this repository (enforced by the holdout work, #13)
environment = "bare"       # the hangar environment trials run in
# canary, mined_from: set by the holdout and mining work

[flightdeck.source]        # what hangar checks out: repo, base_sha (40 hex), base_branch, issue, verify
repo = "https://github.com/OWNER/REPO.git"
base_sha = "..."

[flightdeck.grader]
command = "bash tests/test.sh"   # run from the task's directory
files_digest = "sha256:..."      # of tests/*, written by `flightdeck task digest --write`
```

Why the issue's `[source]`, `[grader]` and `[task] id` moved: Harbor's `source` is a top-level string and its `[task]`
requires `name`, so those tables would make a flightdeck task invalid for Harbor. Everything flightdeck adds is under
`[flightdeck]`; Harbor's `[agent]`/`[verifier]` timeouts replace `timeout_min`/`timeout_s`.

Not supported yet: Harbor's multi-step tasks (`[[steps]]`) and Windows `test.bat` (refused with a message).

## Commands

```sh
flightdeck task new tasks/regression/fix-retry   # from the template: safe test.sh, placeholder hidden test
flightdeck task check tasks/smoke/semver ...      # layout, symlinks, files_digest, hangar's limits
flightdeck task digest [--write] tasks/smoke/semver
```

## Digests

- `task_digest = sha256(canonical task.toml, instruction.md, tests/*, environment/*)`: the trial-result cache key
  (#24). Each part is hashed as `name \0 length \0 bytes`, files sorted by relative path. `task.toml` is canonical
  JSON (sorted keys, no comments or formatting, `files_digest` left out). Text files get LF newlines before
  hashing, so a Windows checkout hashes the same; `__pycache__` and `*.pyc` are skipped; symlinks are refused.
- `files_digest`: the same over `tests/*` alone, recorded in `task.toml`. `load_task` refuses a task whose tests no
  longer match it, so a changed hidden test is always a deliberate, reviewed edit.

## On hangar

`to_hangar(tasks)` builds the `tasks` and `grader` of a `hangar.experiment/v1` spec (hangar
`src/hangar/experiments.py`, `Task` and `Grader`). Hangar runs one grader per experiment, so every task's tests go
into its `Grader.files` as `<id>/tests/...` and the command is `cd "$HANGAR_HIDDEN_TESTS/$HANGAR_TASK" && <command>`:
each trial runs its own task's command from that task's pristine copy. Hangar's limits are checked before submitting:
task ids `^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$` (a longer Harbor id gets a stable short form), instructions up to 64,000
characters, grader files at most 64 and 1 MB in all (`MAX_GRADER_FILES`), text only, a reference patch up to 1 MB.
Tasks whose grader commands differ go in separate experiments.

Hangar runs the grader in a sealed sandbox (no credential, egress `none`), writes the files outside the repo and adds
a canary comment to each. A `test.sh` command is recorded as `trust: low` (hangar can only vouch for its own
`hangar-grade pytest` runner); the safe pattern below is what keeps such a grade honest.

## Writing a safe test.sh

A trial's patch can try to forge its grade: write the reward file, or add a `conftest.py`, pytest settings,
`sitecustomize.py` or a `.pth` file that runs before the hidden tests (hangar spec 0014 §6). The template does this:

1. Find things by environment: the agent's tree is `$FLIGHTDECK_WORKDIR`, else `$HANGAR_REPO`, else the current
   directory (Harbor); the hidden tests are the script's own directory; the reward goes to
   `$FLIGHTDECK_REWARD_DIR/reward.json`, else `/logs/verifier/reward.json` (Harbor), and to `$HANGAR_GRADE_OUT` when set.
2. Copy the tests and only the code under test to a fresh directory outside the agent's tree, before any of the
   agent's code runs.
3. Run Python isolated: `python3 -I -m pytest --noconftest -p no:cacheprovider -c /dev/null -o addopts=` with
   `PYTHONNOUSERSITE=1` and `PYTHONPATH`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` unset.
4. Compare against expected output, not against anything the agent produced.
5. Write the reward last. Harbor's `reward.json` takes numbers only (`{"reward": 1, "passed": 116, "total": 116}`);
   richer detail goes to stdout and `$HANGAR_GRADE_OUT`. Exit non-zero when the reward is 0, since hangar reads the
   exit code.

Code under test still runs inside the test process and can lie through it; hangar's base-must-fail check (a
`solution/reference.patch` must pass, the base must fail), canaries and `touched_tests` are the detectors for that.

## The semver smoke task

`tasks/smoke/semver/`, ported from hangar `evals/semver`: build a Python semver library with node-semver range
matching. 116 hidden unittest cases in 13 categories, generated from node-semver 7.8.5's answers
(`generator/`: `node oracle.js > oracle.json`, `python3 gen_hidden.py`). `test.sh` copies only `semver.py`, runs the
hidden tests with pytest when the environment has it (else unittest), writes `reward.json` and prints
`RESULT {passed, total, by_category, failed}`. `solution/semver.py` is a reference that scores 116/116. Every hangar
trial so far scored 116/116, so it tests the plumbing, not the agents.

To run it on hangar, set `[flightdeck.source] repo` and `base_sha` to an empty repository's first commit: hangar applies
and grades a trial's patch only on a repo.
