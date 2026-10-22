# Running experiments

flightdeck decides what to run; hangar runs it. A runner hands flightdeck's plan to hangar and brings the results back
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

`HANGAR_URL` names hangar and `HANGAR_TOKEN` is the bearer token. flightdeck checks nothing about credentials: hangar
refuses subscription logins for experiments and owns API keys and their spend caps.

hangar caps one experiment at 100 tasks, 8 variants, 20 trials per task and variant, and 200 trials in all
(`HANGAR_EXPERIMENT_MAX_TRIALS`). A larger plan becomes several experiments named `<suite>-<suite_run>-<i>`. Their
ids joined by `+` are the run-set id, and the plan's `budget_usd` is split between them by task count.

hangar does the interleaving, isolation and pinning. Experiments queue as eval-class work (after 20:00, within API
headroom), so `status` can say `queued` for hours. A trial whose agent asks a question is cancelled, since nobody is
there to answer; it counts as `cancelled`, not as a failure.

### LocalDockerBackend

`--backend local` runs trials in Docker on this machine, for fixtures and CI only. See [Local runs](local.md).

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

## Collecting

`collect` is `flightdeck ingest experiment` for each experiment of the run set
([Data plane](data-plane.md#ingest)). The index and each trial's manifest and trace are streamed to
`<data>/raw/<id>/`. They are ingested into every table (runs, grades, spans, events, manifests, test cases) as one
part per experiment and day.

Both commands produce identical tables. Each replaces the other's rows rather than duplicating them.

## Next

- <span id="pins"></span><span id="models"></span><span id="harness-versions"></span><span id="after-the-start"></span><span id="the-cost-gate"></span>[Pins and the cost gate](pins.md):
  the model and harness pins, and the projected cost a plan must fit.
- <span id="cache"></span><span id="the-key"></span><span id="what-counts"></span><span id="invalidation"></span><span id="in-reports"></span><span id="drift-sentinel"></span>[The trial cache](cache.md):
  reusing trials whose inputs haven't changed, and the drift sentinel.
- <span id="local"></span><span id="environment"></span><span id="attempt"></span><span id="grading"></span><span id="drivers"></span><span id="rows"></span>[Local runs](local.md):
  Docker trials on this machine, for fixtures and CI.

## See also

- [Tasks](tasks.md): the task directories a suite names, and how hangar grades them.
- [Data plane](data-plane.md#ingest): where `collect` puts the results.
- [Statistics](statistics.md): what a plan of this size can and cannot show.
- [Reports](reports.md): the verdict the run set ends in.
