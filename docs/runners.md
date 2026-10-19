# Running experiments

Flightdeck decides what to run; hangar runs it. A runner hands flightdeck's plan to hangar and brings the results back
into the data plane.

<div class="af-figure" markdown>
--8<-- "docs/assets/flow-experiment.svg"
<figcaption>An experiment's life: suite, plan, cost gate, hangar, collect, report; the cache skips what is already known</figcaption>
</div>

A plan names task sets, variants and how many trials. Code: `src/flightdeck/runners/`.

## Backends

```python
class Backend(Protocol):
    def submit(self, plan: TrialPlan) -> str          # a run-set id
    def status(self, run_set: str) -> RunSetStatus    # state, trial counts, pin problems, hangar's notes
    def collect(self, run_set: str) -> Path           # ingests runs, grades, traces and manifests
```

The CLI and suites call only this interface, and a test double proves it. So pin-set trials
([#25](https://github.com/Sean-Koval/flightdeck/issues/25), `POST /api/trials`) can replace today's backend without
touching them.

### HangarBatchBackend

Uses hangar's batch experiments (hangar spec 0014 §4). `POST /api/experiments` submits tasks × variants × a fixed trial
count; `GET /api/experiments/{id}` returns the `hangar.experiment/v1` index.

`HANGAR_URL` names hangar and `HANGAR_TOKEN` is the bearer token. Flightdeck checks nothing about credentials: hangar
refuses subscription logins for experiments and owns API keys and their spend caps.

Hangar caps one experiment at 100 tasks, 8 variants, 20 trials per task and variant, and 200 trials in all
(`HANGAR_EXPERIMENT_MAX_TRIALS`). A larger plan becomes several experiments named `<suite>-<suite_run>-<i>`. Their
ids joined by `+` are the run-set id, and the plan's `budget_usd` is split between them by task count.

Hangar does the interleaving, isolation and pinning. Experiments queue as eval-class work (after 20:00, within API
headroom), so `status` can say `queued` for hours. A trial whose agent asks a question is cancelled, since nobody is
there to answer; it counts as `cancelled`, not as a failure.

### LocalDockerBackend

`--backend local` runs trials in Docker on this machine, for fixtures and CI only. See [Local](#local).

## Commands

```sh
flightdeck experiment run tasks/smoke/suite.yaml --dry-run    # print the spec and the cost projection only
flightdeck experiment run tasks/smoke/suite.yaml --author dev-a
flightdeck experiment status <run-set> [--json]               # exit 1 when pins break pairing
flightdeck experiment collect <run-set> --data ./plane        # or FLIGHTDECK_DATA_URI
```

A suite file (YAML):

```yaml
suite: smoke
tasks: ["."]            # task directories (docs/tasks.md), or directories of them, relative to this file
environment: bare       # else the tasks' [flightdeck] environment, when they agree
n: 3                    # trials per task and variant
budget_usd: 40          # the experiment's cap: hangar starts no trial past it
trial_budget_usd: 3     # each trial's cap
parallel: 6
variants:               # hangar's Variant: harness[@version], model, approvals, skills, skills_remove,
  claude-code: {harness: claude-code, model: claude-opus-5-5}     # instructions, instructions_append
  codex: {harness: codex@0.162.1, model: gpt-6.1-sol}
```

The tasks become the experiment's tasks and its one grader ([Tasks](tasks.md#on-hangar)).

## Pins

### Models

Every variant names a concrete model id. A policy (`frontier`, `balanced`, `frontier@openai`), an alias (`*-latest`,
OpenRouter's `~…`) or a family name without a version (`opus`, `sonnet`, `gpt-5`, `claude-opus-5`) is refused before
anything is sent. The provider can move those between two trials.

The rule is hangar's `modelpolicy.is_concrete` ([hangar#167](https://github.com/Sean-Koval/hangar/issues/167)), ported
to `src/flightdeck/ported/modelpolicy.py` and checked against hangar's own test table
(`tests/fixtures/hangar/model_concreteness.json`). A concrete id names a version or a date: `claude-opus-5-5`,
`claude-opus-4-5-20251101`, `gpt-6.1-sol`, `gpt-4o-2024-08-06`, `gemini-3.8-flash`,
`openrouter/anthropic/claude-opus-5.5`. `run`, `status` and `ingest` share the rule.

Flightdeck has no provider model list, so it decides by shape only. An id hangar accepts because its provider lists it
(`claude-opus-5`) needs `--allow-model ID`. `hangar env list` shows what a policy resolves to today.

### Harness versions

`harness@version` must be the version hangar's lock pins (`harnesses.lock.yaml`). Otherwise hangar refuses the
experiment and `run` prints hangar's message.

A variant that names a harness lock (`harness_lock: name@sha256:...`, accepted by hangar since
[hangar#135](https://github.com/Sean-Koval/hangar/issues/135)) is refused here for now: `harness_lock isn't a hangar
variant field`. See [Contracts](contracts.md#the-vendored-schemas).

### After the start

`status` checks the index's pins. Every task has a `base_sha`; no variant's model was pinned to an alias; variants
that asked for the same model got the same id. Any of these is a pin problem, and `status` exits 1.

## The cost gate

Before submitting, `run` projects the plan's cost. Each task's historical median `cost_usd` per trial comes from the
data plane's `runs` (`--data` / `FLIGHTDECK_DATA_URI`), else `--assume` (default $3.00); times trials, times variants.

`run` refuses the plan when the projection is over `--max-usd`, over the team's remaining monthly budget, or over the
author's remaining sub-cap. The refusal names the cap and its file. Spend so far is this calendar month's experiment
`cost_usd` in `runs`: the team's, and the author's where `person` is the author.

The gate is advisory and early. Hangar's own budgets (per trial, per experiment, daily) still enforce.

`budgets.yaml` is team configuration and lives in the private data repository, not here. `run` finds it through
`--budgets`, `FLIGHTDECK_BUDGETS`, else `./budgets.yaml` when present:

```yaml
month_usd: 1500       # the team's monthly eval budget
authors:              # per-author monthly sub-caps; with any set, runs must name --author (or FLIGHTDECK_AUTHOR)
  dev-a: 300
  dev-b: 300
```

## Collecting

`collect` is `flightdeck ingest experiment` for each experiment of the run set
([Data plane](data-plane.md#ingest)). The index and each trial's manifest and trace are streamed to
`<data>/raw/<id>/`. They are ingested into every table (runs, grades, spans, events, manifests, test cases) as one
part per experiment and day.

Both commands produce identical tables. Each replaces the other's rows rather than duplicating them.

## Cache

Tokens cost far more than compute: about $2 to $3 a trial against well under a cent. So a trial whose inputs haven't
changed is reused rather than re-run. `experiment run <suite> --cache --data <dir>` looks each planned
`(task, variant)` up in the data plane and submits only what is missing. Code: `src/flightdeck/runners/cache.py`.

### The key

The key is `task_digest`, `variant_digest`, the model id and the task's `base_sha`, all stamped on the runs when
flightdeck collects them. `task_digest` covers the task's tests and grader command, so it stands in for
`grader_digest`; `variant_digest` is the variant's overlay and environment as planned.

On top, the identity hangar recorded must equal the latest one that variant recorded. That identity is
`harness_digest + environment_digest`, else `config_digest` plus the manifest's `environment.build.id`
(`config_digest` alone misses a repository rebuild).

So a changed skill is a new `variant_digest`, and only that variant runs again. A provider or environment change
shows up as a new identity on the next trial, and older trials stop matching.

### What counts

Completed trials only: never `infra_error`, cancelled, human, tainted, contaminated, drifted or `task_invalid` ones.
A pair is a hit only with at least `n` such trials, and the `n` most recent are reused.

### Invalidation

A 30-day TTL; a model change, since it is in the key; and `flightdeck cache drop --task <id>` or
`--identity <digest>`. A drop ignores trials finished before it, and is kept in `<data>/cache-drops.json`.

### In reports

The run set's reused trials go to `trial_reuse`. `stats compare <run-set>` and the report read them with the new
trials, each `run_id` once, and say how many were reused and how old they are. When everything hits, nothing is
submitted and the run set is `reuse-<suite>-<time>`.

Cache reads spend nobody's budget. Trials without an identity (older hangar records) never hit.

### Drift sentinel

A silent provider-side change keeps every key the same. So a nightly suite of about 5 fixed tasks × 2 trials runs on
the `stable` harness *without* `--cache`. It costs about $20 a night, on the team budget line. Then:

```sh
flightdeck cache sentinel sentinel.yaml stable --data <dir> [--alerts-repo owner/repo]
```

compares the latest night with its trailing 14 days. Drift is a resolved rate whose Wilson interval misses the
window's. It is also a median cost or wall time outside 0.67 to 1.5 times the window's. Either prints an alert, opens
an issue and exits 1.

!!! note "Status"
    Code merged ([#55](https://github.com/Sean-Koval/flightdeck/pull/55)). Issue
    [#24](https://github.com/Sean-Koval/flightdeck/issues/24) stays open until the drift sentinel is scheduled nightly
    in the private data repository.

## Local

`flightdeck experiment run <suite> --backend local --data <dir>` runs every trial of the suite now, one after another,
in Docker on this machine. It writes them into the data plane at `<dir>` with `source = local`.

It is for fixtures and CI; this repository's own CI runs `tasks/fixtures/local.yaml` on every PR. It is never for
team tasks: a task with `sealed = true` or `mined_from` set is refused. Team tasks run on hangar, where credentials
and egress policy live.

There is no cost gate. A deterministic run spends nothing, and a real-model run is capped by the suite's `budget_usd`
(below). `status` and `collect` recognize a local run set by its `local-` prefix and read its evidence from
`<dir>/raw/<run-set>/`.

The isolation is ai-dlc's evaluation runner, ported at its handoff commit `f5be4f4` (`src/flightdeck/ported/aidlc/`,
each file listing what changed). The flightdeck side is `src/flightdeck/runners/local.py`.

### Environment

The task's `environment/Dockerfile` is built to an image id. Or `[environment] docker_image`, which must be pinned by
digest, is used as is and never pulled. The project is the image's working directory (`[environment] workdir`, else the
image's `WORKDIR`). The image needs `git`.

### Attempt

A controller-owned stager copies the working directory into a per-attempt volume, dropping any `.git`. The controller
commits it as a fixed anchor (`refs/flightdeck/anchor`, neutral author, fixed date).

The agent's container runs as uid 1000 with `--read-only --cap-drop=ALL --security-opt=no-new-privileges`, memory
and process limits, tmpfs `/tmp` and home, and `--network=none`. Nothing from the host is mounted.

A real-model trial instead joins an internal network whose only other member is ai-dlc's allow-listing proxy: port 443
to `api.anthropic.com` only, decisions kept in `egress.jsonl`.

After the agent stops, a separate read-only collector copies the volume out. Then every container, volume and network
is removed; `cleanup-ledger.jsonl` names any that weren't.

### Grading

The task's `tests/` stay on the controller. The grader command (`[flightdeck.grader] command`) runs on the collected
tree in a fresh container with no network and the same isolation, with `FLIGHTDECK_WORKDIR` and
`FLIGHTDECK_REWARD_DIR` set ([Tasks](tasks.md#writing-a-safe-testsh)). Its `reward.json` is kept beside the trial's
evidence and in `grades.data`; its exit code is `grades.exit_code`.

### Drivers

A variant's `harness` picks the driver.

`deterministic` makes no model calls. It runs the task's `solution/deterministic.json` (ai-dlc's script format:
`{"steps": [argv, or {"write": path, "from": file}]}`, one command per step), else Harbor's oracle (copy `solution/`
in, run `solve.sh`).

`claude-code@<version>` runs one Claude Code print-mode session (`--output-format stream-json`) in the task's image,
which must contain that exact client. It needs `ANTHROPIC_API_KEY` in your environment (an API key, never a
subscription login) and a concrete model id.

It spends at most `trial_budget_usd` per trial (default $2) and `budget_usd` per run set, through ai-dlc's
observed-usage ledger; without `budget_usd` no real-model trial starts. The key's value is redacted from all evidence,
and an attempt where it appeared is `incomplete`.

The real-model path is not run in CI and has not been qualified against a live model since the port.

### Rows

A local run set reads like a hangar experiment to `stats compare`, reports and specs (`experiment_id` = the run set
id):

| Table | From |
| --- | --- |
| `runs` | one per trial: `outcome` `succeeded` (the attempt completed), `failed` (`outcome_class = infra_error` when provisioning, staging or a resource limit failed; else timeout, cancellation or damaged evidence, in `reason`), `cancelled` (the run budget refused it); `diff_files` from the Git observer; `truncated` when the attempt or the observation is incomplete, so specs answer `unknown` rather than pass |
| `grades` | the grader's exit code, seconds, `reward.json` and the tests' `files_digest` |
| `spans` | one `tool.call` per deterministic step (`tool_kind` `shell`, or `edit` for a file write), or per tool call in a Claude Code stream, with hangar's `tool_kind` and `shell_ops` (ported from hangar's `traces.py`) and `seq` in order |
| `events` | one `git.commit` per post-anchor commit the Git observer confirms, placed after the step that made it |
| `test_cases` | one trusted `test.run` per deterministic step whose command is a test (`total` from unittest's or pytest's summary) |

Trust follows hangar's rule. A `test.run` is trusted because the controller ran the command and read its result,
which the agent can't fake. A model's own test commands are spans with the `test` shell op, never `test.run` rows,
and its transcript is never evidence.

So `tests-before-commit` evaluates on local runs. On `tasks/fixtures/local.yaml`, the csv-validator script tests
before committing (`pass`) and semver's `solve.sh` commits without testing (`fail`). A step that both tests and
commits counts the test first, unless its command commits first.

## See also

- [Tasks](tasks.md): the task directories a suite names, and how hangar grades them.
- [Data plane](data-plane.md#ingest): where `collect` puts the results.
- [Statistics](statistics.md): what a plan of this size can and cannot show.
- [Reports](reports.md): the verdict the run set ends in.
