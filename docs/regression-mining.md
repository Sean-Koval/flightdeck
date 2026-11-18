# How are regression tasks mined from labelled failures?

regression-v1 ([#12](https://github.com/Sean-Koval/flightdeck/issues/12), KAN-88) turns the Friday review's
labelled failures into tasks. Each task is the failed job's starting commit, its instruction, and the tests of the
human fix that followed. `scripts/mine_regression.py` does the mining. It runs in the private data repository
([ADR 0002](decisions/0002-public-code-private-data.md)), never in this one.

## The labels

`labels/first-failures.yaml` holds one row per failed job. `job_id`, `first_failure_seq` and `category` are required.
The category comes from hangar's taxonomy: `stuck-loop`, `oracle-fixation`, `scope-creep`, `test-gaming`,
`premature-done`, `unsafe-action`, `dependency-fight`, `env-fix` or `other`.

```yaml
- job_id: j-123
  first_failure_seq: 14            # hangar.seq of the first failing step
  category: scope-creep
  labelled_by: reviewer
  labelled_at: 2026-11-21
  fixed_by_pr: OWNER/NAME#45       # the human fix
  fix_sha: <40 hex>                # optional: else the PR's merge commit, read from GitHub
  instruction: "..."               # the job's task text, as hangar fenced it
```

The repository and base commit come from the data plane's `runs`. A row may set `repo` or `base_sha` to override
them.

## Commands

```sh
python scripts/mine_regression.py validate labels/first-failures.yaml --data ~/plane
python scripts/mine_regression.py mine labels/first-failures.yaml --data ~/plane --out . --image <grader image>
```

`validate` checks every row and that each job is in `runs`. It also counts the rows against the 20 the issue needs.

`mine` writes a task per row under `tasks/regression-v1/`. The hidden tests are the `tests/**/test_*.py` and
`conftest.py` files the fix added or changed. `solution/reference.patch` is the rest of the fix.

## Fail-to-pass

A task is kept only if its hidden tests fail on the base and pass on the fix, three times each. A varying outcome
is recorded as flaky and dropped.

With `--image`, the checks run in that image with no network. The image needs the repository's dependencies and
pytest. Without `--image`, they run on this machine, which is for fixtures and CI only. Never run them on a laptop
that holds team credentials.

## What can't be mined

Every row that isn't mined is recorded with its reason:

- `needs-instruction`: the row has no task text.
- `needs-tests`: there's no fix pull request. A reviewer-written test can stand in.
- The base commit is gone, for example force-pushed away.
- The fix changes no test file, or two hidden files share a name.
- The tests already pass on the base, fail on the fix, or are flaky.

## The lock

`suites/regression-v1.lock.json` records each task's digest and `files_digest`, its job, category and seq. It also
lists every unmined job with its reason. The issue's bar is 20 labelled and at least 12 mined, and `mine` exits 1
below 12.

## Why a script

The counted-line budget is full: 3,875 of 3,875 ([ADR 0010](decisions/0010-default-specs-budget.md)). Mining runs a
few times a year by hand, so it lives in `scripts/` and calls flightdeck's task code. A `flightdeck task mine`
command would need a cut or an ADR.

## See also

- [Tasks](tasks.md): the task format the miner writes.
- [Holdouts](holdouts.md): regression tasks may shape harness changes, and holdouts may not.
