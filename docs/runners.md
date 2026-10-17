# Runners

Flightdeck decides what to run (task sets, variants, how many trials); hangar runs it. A runner is the backend
that hands flightdeck's plan to hangar and brings the results back into the data plane. Code: `src/flightdeck/runners/`.

## Backends

```python
class Backend(Protocol):
    def submit(self, plan: TrialPlan) -> str          # a run-set id
    def status(self, run_set: str) -> RunSetStatus    # state, trial counts, pin problems, hangar's notes
    def collect(self, run_set: str) -> Path           # writes runs and grades into the data plane
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

- **Models.** Every variant names a concrete model id. Policies (`frontier`, `balanced`, `latest`, `frontier@openai`),
  aliases (`*-latest`, OpenRouter's `~…`) and family names without a version (`opus`, `sonnet`, `gpt-5`,
  `claude-opus-5`) are refused before anything is sent, because the provider can move them between two trials. The rule
  matches hangar #167: a concrete id names a version or a date (`claude-opus-5-5`, `claude-opus-4-5-20251101`,
  `gpt-6.1-sol`, `gpt-4o-2024-08-06`, `gemini-3.8-flash`, `openrouter/anthropic/claude-opus-5.5`). `hangar env list`
  shows what a policy resolves to today; `--allow-model ID` accepts an id the rule doesn't know.
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

`collect` reads each experiment's index and writes its trials (`runs`, one row per trial) and grades (`grades`) as one
Parquet part per experiment and day (`part-experiment-<id>.parquet`); collecting again replaces the experiment's parts
in every day. Traces and manifests come from `flightdeck ingest experiment` (the ingest work, #7), which writes the same
part names, so either replaces the other's rows rather than duplicating them.
