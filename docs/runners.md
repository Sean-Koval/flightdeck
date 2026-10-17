# Runners

Flightdeck decides what to run (task sets, variants, how many trials); hangar runs it. A runner is the backend
that hands flightdeck's plan to hangar and brings the results back into the data plane. Code: `src/flightdeck/runners/`.

## Backends

```python
class Backend(Protocol):
    def submit(self, plan: TrialPlan) -> str          # a run-set id
    def status(self, run_set: str) -> RunSetStatus    # state, trial counts, pin problems, hangar's notes
    def collect(self, run_set: str) -> Path           # ingests runs, grades, traces and manifests
```

The CLI and suites call only this interface (a test double proves it), so pin-set trials (`POST /api/trials`, #25)
can replace today's backend without touching them.

**`HangarBatchBackend`** uses hangar's batch experiments (hangar spec 0014 §4): `POST /api/experiments` with tasks ×
variants × a fixed trial count, `GET /api/experiments/{id}` for the `hangar.experiment/v1` index. `HANGAR_URL` names
hangar and `HANGAR_TOKEN` is the bearer token; flightdeck checks nothing about credentials (hangar refuses subscription
logins for experiments and owns API keys and their spend caps). Hangar caps one experiment at 100 tasks, 8 variants,
20 trials per task and variant, and 200 trials in all (`HANGAR_EXPERIMENT_MAX_TRIALS`). A larger plan becomes several
experiments named `<suite>-<suite_run>-<i>`, and its run-set id is their ids joined by `+`; the plan's `budget_usd`
is split between them by task count.

Hangar does the interleaving, isolation and pinning. Experiments queue as eval-class work (after 20:00, within API
headroom), so `status` can say `queued` for hours. A trial whose agent asks a question is cancelled (nobody is there to
answer) and counts as `cancelled`, not as a failure.

**`LocalDockerBackend`** (`--backend local`) runs trials in Docker on this machine, for fixtures and CI only; see
[Local](#local).

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

The tasks become the experiment's tasks and its one grader (docs/tasks.md#on-hangar).

## Pins

- **Models.** Every variant names a concrete model id. Policies (`frontier`, `balanced`, `frontier@openai`),
  aliases (`*-latest`, OpenRouter's `~…`) and family names without a version (`opus`, `sonnet`, `gpt-5`,
  `claude-opus-5`) are refused before anything is sent, because the provider can move them between two trials. The rule
  is hangar's `modelpolicy.is_concrete` (#167), ported to `src/flightdeck/ported/modelpolicy.py` and checked against
  hangar's own test table (`tests/fixtures/hangar/model_concreteness.json`): a concrete id names a version or a date
  (`claude-opus-5-5`, `claude-opus-4-5-20251101`, `gpt-6.1-sol`, `gpt-4o-2024-08-06`, `gemini-3.8-flash`,
  `openrouter/anthropic/claude-opus-5.5`). `run`, `status` and `ingest` share it. Without the provider's model list
  flightdeck decides by shape only, so an id hangar accepts because its provider lists it (`claude-opus-5`) needs
  `--allow-model ID`; `hangar env list` shows what a policy resolves to today.
- **Harness versions.** `harness@version` must be the version hangar's lock pins (`harnesses.lock.yaml`); hangar
  refuses the experiment otherwise, and `run` prints hangar's message.
- **After the start**, `status` checks the index's pins: every task has a `base_sha`, no variant's model was pinned to
  an alias, and variants that asked for the same model got the same id. Any of these is a pin problem and `status`
  exits 1.

## The cost gate

Before submitting, `run` projects the plan's cost: each task's historical median `cost_usd` per trial from the data
plane's `runs` (`--data` / `FLIGHTDECK_DATA_URI`), else `--assume` (default $3.00), × trials × variants. It refuses the
plan when the projection is over `--max-usd`, over the team's remaining monthly budget, or over the author's remaining
sub-cap, and names the cap and its file. Spend so far is this calendar month's experiment `cost_usd` in `runs` (team;
and `person` = the author). The gate is advisory and early: hangar's own budgets (per trial, per experiment, daily)
still enforce.

`budgets.yaml` (`--budgets`, `FLIGHTDECK_BUDGETS`, else `./budgets.yaml` when present) is team configuration and lives
in the private data repository, not here:

```yaml
month_usd: 1500       # the team's monthly eval budget
authors:              # per-author monthly sub-caps; with any set, runs must name --author (or FLIGHTDECK_AUTHOR)
  dev-a: 300
  dev-b: 300
```

## Collecting

`collect` is `flightdeck ingest experiment` for each experiment of the run set ([data-plane.md](data-plane.md#ingest)):
the index, and each trial's manifest and trace, are streamed to `<data>/raw/<id>/` and ingested into every table (runs,
grades, spans, events, manifests, test cases) as one part per experiment and day. Both commands produce identical
tables and replace each other's rows rather than duplicating them.

## Cache

Tokens cost far more than compute (about $2-3 a trial against well under a cent), so a trial whose inputs haven't
changed is reused rather than re-run. `experiment run <suite> --cache --data <dir>` looks each planned
`(task, variant)` up in the data plane and submits only what is missing; code: `src/flightdeck/runners/cache.py`.

- **Key.** `task_digest` (which covers the task's tests and grader command, so it stands in for `grader_digest`),
  `variant_digest` (the variant's overlay and environment as planned), the model id and the task's `base_sha`, all
  stamped on the runs when flightdeck collects them. On top, the identity hangar recorded must equal the latest one
  that variant recorded: `harness_digest + environment_digest`, else `config_digest` plus the manifest's
  `environment.build.id`, since `config_digest` misses a repository rebuild. A changed skill is a new
  `variant_digest`, so only that variant runs again; a provider or environment change shows up as a new identity on
  the next trial, and older trials stop matching.
- **What counts.** Completed trials only: never `infra_error`, cancelled, human, tainted, contaminated, drifted or
  `task_invalid` ones. A pair is a hit only with at least `n` such trials; the `n` most recent are reused.
- **Invalidation.** A 30-day TTL; a model change (it's in the key); and `flightdeck cache drop --task <id>` or
  `--identity <digest>`, which ignores trials finished before the drop (kept in `<data>/cache-drops.json`).
- **Reports.** The run set's reused trials go to `trial_reuse`, so `stats compare <run-set>` and the report read them
  with the new trials, each `run_id` once, and say how many were reused and how old they are. When everything hits,
  nothing is submitted and the run set is `reuse-<suite>-<time>`.
- Cache reads spend nobody's budget. Trials without an identity (older hangar records) never hit.

**Drift sentinel.** A silent provider-side change keeps every key the same, so a nightly suite of about 5 fixed
tasks × 2 trials runs on the `stable` harness *without* `--cache` (about $20 a night, on the team budget line), and

```sh
flightdeck cache sentinel sentinel.yaml stable --data <dir> [--alerts-repo owner/repo]
```

compares the latest night with its trailing 14 days: a resolved rate whose Wilson interval misses the window's, or a
median cost or wall time outside 0.67-1.5× the window's, prints an alert (and opens an issue), exit 1.

## Local

`flightdeck experiment run <suite> --backend local --data <dir>` runs every trial of the suite now, one after another,
in Docker on this machine, and writes them into the data plane at `<dir>` with `source = local`. It is for fixtures and
CI (this repository's own CI runs `tasks/fixtures/local.yaml` on every PR), never for team tasks: a task with
`sealed = true` or `mined_from` set is refused, because team tasks run on hangar, where credentials and egress policy
live. There is no cost gate: a deterministic run spends nothing, and a real-model run is capped by the suite's
`budget_usd` (below). `status` and `collect` recognize a local run set by its `local-` prefix and read its evidence
from `<dir>/raw/<run-set>/`.

The isolation is ai-dlc's evaluation runner, ported at its handoff commit `f5be4f4` (`src/flightdeck/ported/aidlc/`,
each file listing what changed; the flightdeck side is `src/flightdeck/runners/local.py`):

- **Environment.** The task's `environment/Dockerfile` is built to an image id (or `[environment] docker_image`, which
  must be pinned by digest, is used as is and never pulled). The project is the image's working directory
  (`[environment] workdir`, else the image's `WORKDIR`). The image needs `git`.
- **Attempt.** A controller-owned stager copies the working directory into a per-attempt volume (dropping any `.git`)
  and the controller commits it as a fixed anchor (`refs/flightdeck/anchor`, neutral author, fixed date). The agent's
  container runs as uid 1000 with `--read-only --cap-drop=ALL --security-opt=no-new-privileges`, memory and process
  limits, tmpfs `/tmp` and home, and `--network=none`; nothing from the host is mounted. A real-model trial instead joins
  an internal network whose only other member is ai-dlc's allow-listing proxy (port 443 to `api.anthropic.com` only;
  decisions kept in `egress.jsonl`). After the agent stops, a separate read-only collector copies the volume out; then
  every container, volume and network is removed (`cleanup-ledger.jsonl` names any that weren't).
- **Grading.** The task's `tests/` stay on the controller. The grader command (`[flightdeck.grader] command`) runs on
  the collected tree in a fresh container with no network, the same isolation and `FLIGHTDECK_WORKDIR` /
  `FLIGHTDECK_REWARD_DIR` set ([docs/tasks.md](tasks.md#writing-a-safe-testsh)); its `reward.json` is kept beside the
  trial's evidence and in `grades.data`, its exit code is `grades.exit_code`.
- **Drivers.** A variant's `harness` picks the driver. `deterministic` makes no model calls: it runs the task's
  `solution/deterministic.json` (ai-dlc's script format: `{"steps": [argv, or {"write": path, "from": file}]}`, one
  command per step), else Harbor's oracle (copy `solution/` in, run `solve.sh`). `claude-code@<version>` runs one
  Claude Code print-mode session (`--output-format stream-json`) in the task's image, which must contain that exact
  client; it needs `ANTHROPIC_API_KEY` in your environment (an API key, never a subscription login), a concrete model id,
  and spends at most `trial_budget_usd` per trial (default $2) and `budget_usd` per run set (ai-dlc's observed-usage
  ledger; without `budget_usd` no real-model trial starts). The
  key's value is redacted from all evidence, and an attempt where it appeared is `incomplete`. The real-model path is
  not run in CI and has not been qualified against a live model since the port.

Rows, so `stats compare`, reports and specs read a local run set like a hangar experiment (`experiment_id` = the run
set id):

| Table | From |
| --- | --- |
| `runs` | one per trial: `outcome` `succeeded` (the attempt completed), `failed` (`outcome_class = infra_error` when provisioning, staging or a resource limit failed; else timeout, cancellation or damaged evidence, in `reason`), `cancelled` (the run budget refused it); `diff_files` from the Git observer; `truncated` when the attempt or the observation is incomplete, so specs answer `unknown` rather than pass |
| `grades` | the grader's exit code, seconds, `reward.json` and the tests' `files_digest` |
| `spans` | one `tool.call` per deterministic step (`tool_kind` `shell`, or `edit` for a file write), or per tool call in a Claude Code stream, with hangar's `tool_kind` and `shell_ops` (ported from hangar's `traces.py`) and `seq` in order |
| `events` | one `git.commit` per post-anchor commit the Git observer confirms, placed after the step that made it |
| `test_cases` | one trusted `test.run` per deterministic step whose command is a test (`total` from unittest's or pytest's summary) |

Trust follows hangar's rule: a `test.run` is trusted because the controller ran the command and read its result, which
the agent can't fake. A model's own test commands are spans with the `test` shell op, never `test.run` rows, and its
transcript is never evidence. So `tests-before-commit` evaluates on local runs: on `tasks/fixtures/local.yaml`, the
csv-validator script tests before committing (`pass`) and semver's `solve.sh` commits without testing (`fail`). A step
that both tests and commits counts the test first unless its command commits first.

