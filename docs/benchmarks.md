# Create a benchmark and share it with your team

You have a set of tasks in mind and want your team to run them on two harnesses. This page walks that path with
today's commands. A benchmark is a git repository of task directories and a suite file, shared at a tag.

## 1. Write the tasks

Start each task from the template. It comes with a safe `test.sh` and a placeholder hidden test.

```sh
mkdir my-bench && cd my-bench && git init
uv run flightdeck task new tasks/fix-retry       # once per task
# edit tasks/fix-retry/instruction.md, tests/ and environment/
uv run flightdeck task digest --write tasks/fix-retry
uv run flightdeck task check tasks/*/
```

Keep the hidden tests hidden: the agent never sees `tests/`. Follow
[Writing a safe test.sh](tasks.md#writing-a-safe-testsh), so a trial can't forge its own grade. Rerun
`task digest --write` after every change to `tests/`.

To run on hangar, each task also needs `[flightdeck.source] repo` and `base_sha` in its `task.toml`. That is the
hosted repository hangar checks out ([Tasks](tasks.md#on-hangar)).

## 2. Add a suite file and tag it

A suite file names the tasks, the variants, the trial count and the budget. Copy `tasks/smoke/suite.yaml`:

```yaml
suite: my-bench
tasks: ["tasks"]
environment: bare
n: 3
budget_usd: 40
trial_budget_usd: 3
variants:
  claude-code: {harness: claude-code, model: claude-opus-5-5}
  codex: {harness: codex, model: gpt-6.1-sol}
```

Commit it, then tag the commit so everyone runs the same version:

```sh
git add . && git commit -m "my-bench v1"
git tag bench/my-bench/v1 && git push origin main bench/my-bench/v1
```

## 3. Your teammates run it

Each teammate clones the tag and checks the tasks. `task check` prints every task's `task_digest`. Two people ran the
same benchmark when their digests match.

```sh
git clone --branch bench/my-bench/v1 <repo-url> my-bench && cd my-bench
uv run flightdeck task check tasks/*/
uv run flightdeck experiment run suite.yaml --dry-run
uv run flightdeck experiment run suite.yaml --author dev-a
```

The dry run prints the hangar spec and the projected cost and submits nothing. The real run passes the cost gate
first ([Pins and the cost gate](pins.md)). It needs `HANGAR_URL` and `HANGAR_TOKEN`.

To try the path without hangar, run the fixtures on the [local backend](local.md) with Docker:
`uv run flightdeck experiment run tasks/fixtures/local.yaml --backend local --data /tmp/plane`.

## 4. Collect and compare

```sh
uv run flightdeck experiment status <run-set>
uv run flightdeck experiment collect <run-set> --data ./plane
uv run flightdeck stats compare <run-set> --a claude-code --b codex --data ./plane
uv run flightdeck report experiment <run-set> --a claude-code --b codex --data ./plane \
    --decision decision.yaml --out report.md
```

`stats compare` pairs the two variants by task. `report` gives the verdict, but only against a `decision.yaml`
committed before the run ([Reports](reports.md)). Every row carries its `task_digest`, so the data plane shows which
version each trial ran:

```sh
uv run flightdeck query "select distinct task_id, task_digest from runs" --data ./plane
```

## 5. Keep a set private

A private repository is enough for tasks your team may see. A set that judges a promotion must stay unseen by
whoever tunes the harness. Make that a [sealed holdout](holdouts.md) in the private data repository, not a shared
benchmark. Never share a sealed set by tag.

## What doesn't work yet

| Limit today | Tracked in |
| --- | --- |
| A benchmark has no name, version or digest of its own; the tag and the task digests stand in for them. | [KAN-191](https://seanmkoval.atlassian.net/browse/KAN-191) |
| Each task needs a hosted repository and a hangar environment. | [KAN-192](https://seanmkoval.atlassian.net/browse/KAN-192) |
| One grader per experiment: at most 64 files and 1 MB, and one grader command. | [KAN-192](https://seanmkoval.atlassian.net/browse/KAN-192) |
| No view of results across runs; `stats` compares two arms of one run set. | [KAN-193](https://seanmkoval.atlassian.net/browse/KAN-193) |
| hangar queues experiments for the nightly eval window, so a run can wait hours. | [KAN-194](https://seanmkoval.atlassian.net/browse/KAN-194) |

The `flightdeck bench` commands (KAN-191) wait on a scope and line-budget decision,
[KAN-190](https://seanmkoval.atlassian.net/browse/KAN-190). This page will document them when they land.

## See also

- [Tasks](tasks.md): the task format, digests and hangar's limits.
- [Running experiments](runners.md): suite files, backends and collecting.
- [Statistics](statistics.md): what a set of this size can and cannot show.
