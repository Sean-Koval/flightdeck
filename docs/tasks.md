# Tasks

A task is graded work: an instruction for the agent, the environment it works in, and hidden tests that decide the
reward.

flightdeck's format is [Harbor](https://github.com/harbor-framework/harbor)'s task directory. So public Harbor
datasets (Terminal-Bench and others in Harbor's registry) load without a converter, and flightdeck's tasks run on
Harbor. hangar's spec 0008 chose this format for graded work; flightdeck owns it. Code: `src/flightdeck/tasks/`.

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

`to_hangar(tasks)` builds the `tasks` and `grader` of a `hangar.experiment/v1` spec (hangar
`src/hangar/experiments.py`, `Task` and `Grader`). hangar runs one grader per experiment. So every task's tests go
into its `Grader.files` as `<id>/tests/...`, and the command is
`cd "$HANGAR_HIDDEN_TESTS/$HANGAR_TASK" && <command>`. Each trial runs its own task's command from that task's
pristine copy.

hangar's limits are checked before submitting. Task ids match `^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$` (a longer Harbor
id gets a stable short form). Instructions run up to 64,000 characters. Grader files are at most 64 and 1 MB in all
(`MAX_GRADER_FILES`), text only; a reference patch is up to 1 MB. Tasks whose grader commands differ go in separate
experiments.

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

It was converted by hand; `flightdeck task import-aidlc` (below) now does the same for any ai-dlc suite.

## Importing ai-dlc scenarios

ai-dlc's scenario contract moved here (#17): `src/flightdeck/ported/aidlc/contracts.py` (`Suite`, `Scenario`,
`Assertion`) and its JSON Schema, `schemas/aidlc/scenario.schema.json`, from ai-dlc's handoff commit `f5be4f4`.

```sh
flightdeck task import-aidlc evaluations/suites/smoke.json --out tasks/imported/smoke
```

It validates the suite with ai-dlc's models. A credential-shaped key or value is refused, naming the field and never
the value. Ids must be unique, both arms must run, and each fixture must match its digest. It writes nothing unless
every scenario converts.

### What it writes

`<scenario>/`, a task. `goal` is `instruction.md`. The fixture is `environment/workspace/`, copied into ai-dlc's
digest-pinned Python image. The hidden fixture's `test_*.py` are `tests/`, run by a generic `test.sh` with unittest,
as ai-dlc's controller ran them. It runs on an isolated copy of the whole tree; narrow it to the code under test when
you can.

`answers` become `[flightdeck.agent] answers`: bounded replies, where an unmatched question is needs-input, which
hangar models as a cancelled trial. `limits` become `[agent] timeout_sec` and `[flightdeck] max_turns`. `answers` sit
under `[flightdeck]`, not Harbor's `[agent]`, so the task stays valid for Harbor.

`specs/<scenario>.yaml`: one [behavior spec](behavior-specs.md) per assertion that isn't the grader, scoped with
`applies_when: {task_id: <scenario>}`. Workflow assertions also take `variant: treatment`, since ai-dlc judged
workflow only in the treatment arm.

`suite.yaml`: the scenarios as tasks and the arms as variants `treatment` and `baseline`. The variants are left empty
for you to fill with the hangar overlay that makes each arm what ai-dlc meant (with or without ai-dlc).

### Assertions

The command prints the mapping as a table. Assertions map like this, and any other kind fails the import:

| ai-dlc assertion | Becomes |
| --- | --- |
| `hidden-tests` | the task's grader (`tests/`) |
| `commit-present` | `eventually: {event: git.commit}`; with a `path`, `any` delivered file (`diff.files`) matches it |
| `path-committed` | `any` delivered file (`diff.files`) matches the path |
| `ordering` | `before`: the first edit of `before`'s path precedes `after`'s. Approximate: hangar's `git.commit` events carry no paths, so this is edit order, not commit order |
| `artifact-present` | `any` changed or delivered file matches `expect` (refused without `expect`) |
| quality dimension (`human-review`) | a spec with no `assert` and a `pending` note: always `unknown` until a person records it, or a judge calibrated under #27 |
| `checkpoints` | dropped, and listed: ai-dlc never observed them |

`diff.files` is the delivered diff on hangar, and the committed plus uncommitted paths on the local runner. So
`path-committed` means "would be delivered".

### Outcomes

ai-dlc's `ArmReport.outcome` keeps failures apart, and flightdeck keeps them apart the same way. `infrastructure` is
`outcome_class = infra_error`, excluded from comparisons. `product` is an unresolved grade. `workflow-violation` is a
failing workflow spec. `unavailable` is `unknown`: a missing grade or a spec without evidence, which never passes.

Transcripts are never evidence. Test runs count only when the controller or hangar ran them (`trusted`).

### Not ported

ai-dlc's `evaluate.py`: its grading is the grader plus the specs above. `planning.py`'s profile and attempt matrix:
suite files and variants replace them. Its credential tripwire, field-naming validation and the fixture `tree_digest`
are kept in `ported/aidlc/planning.py`.

## See also

- [Running experiments](runners.md): the suite file that names tasks, and the local backend that runs them.
- [Holdouts](holdouts.md): tasks written blind and sealed, with `sealed = true`.
- [Behavior specs](behavior-specs.md): the specs an import writes beside the tasks.
- [Concepts](concepts.md): check against grader, task against trial.
