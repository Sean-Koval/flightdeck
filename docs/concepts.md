# Concepts

One vocabulary for flightdeck's code, docs and reports, and the status of each feature. Where hangar or ai-dlc uses
a word differently, the entry says so.

| Term | Meaning | Source |
| --- | --- | --- |
| **verdict** | A report's one-word judgement of an experiment: "better", "non-inferior", "worse", "No decision" or "No verdict". "No decision": the interval spans the margin, or too few tasks are paired; "No verdict": no valid `decision.yaml`. The report's headline: the candidate arm against the control arm on one metric, with the paired difference and its interval beside it. See [reports.md](reports.md#pre-registration) | flightdeck report |
| **decision.yaml** | The pre-registered rule a verdict follows: `metric`, `direction`, `margin`, `min_tasks`. Committed before the first trial finishes; the commit time, not the file's, is what counts. Written, edited or committed later: No verdict | [reports.md](reports.md#pre-registration) |
| **variant** / **arm** | One configuration under comparison in an experiment (a harness, model, skill set or instruction). Every trial belongs to one. A comparison has two arms | `hangar.experiment/v1` |
| **control** / **candidate** | The two default arms: *control* is what runs today, *candidate* is the change under judgement. The verdict is always *candidate against control* (`--baseline` and `--candidate` rename them); the report names each arm as hangar's experiment described it | `flightdeck stats compare` |
| **margin** | The pre-registered non-inferiority margin, in the metric's units (a proportion for resolved: `-0.05` is 5 points worse). An interval wholly above it is non-inferior; wholly below it is worse | `decision.yaml` |
| **pp** | Percentage points: the difference between two rates. Resolved going from 40% to 55% is +15 pp (not +37%) | reports, `stats compare` |
| **CI** | The 95% confidence interval around a paired difference, from a task bootstrap. A verdict reads the interval, never the point estimate alone: "better" means the whole interval is above zero | [statistics.md](statistics.md) |
| **runtime** | The agent CLI or loop (Claude Code, Codex, pi, Antigravity) at a version. hangar calls this the *harness* in its manifest (`harness.name`, `harness.version`) | hangar `harnesses.lock.yaml`, manifest `harness` |
| **harness** | A git directory of native files: `AGENTS.md`, skills, one plugin, per-runtime fragments. Its `harness.lock` pins each component's digest, the CLI version and the concrete model. Identity: `harness_digest = sha256(canonical lock)`. Not portable across runtimes; its components are. Note: hangar's manifest `harness` section names the runtime, and its `config_digest` mixes harness and environment | team plan; hangar manifest |
| **environment** | Image, services, egress, resources and credential policy a sandbox gets (`environment_digest`). Not part of the harness | hangar manifest `environment`, `egress`, `resources` |
| **session** | A hangar conversation over time, with its sandbox and checkpoints | hangar `docs/sessions.md` |
| **turn** / **run** | One agent invocation: `hangar.run.id`, one `invoke_agent` span with `hangar.kind = turn`. flightdeck's `runs` table has one row per turn or per trial | `hangar.trace/v1` |
| **job** | A hangar unit of delivered work: turns, verify, git, PR. Its `source` says where it came from (api, jira, github, ..., experiment) | hangar jobs |
| **work item** | The ticket or issue a job serves (Jira, GitHub) | |
| **trial** | One job run for `(task, variant, n)` under pinned conditions, keyed `<task>/<variant>/<n>` | `hangar.experiment/v1` |
| **experiment** | A batch of trials across tasks and variants. hangar runs it; flightdeck designs and judges it | hangar spec 0014 §4 |
| **pin set** | The immutable `{harness_digest, environment_digest, model_id, base_sha, grader_digest, knowledge_snapshot?}` a trial runs against | team plan |
| **task** | A Harbor task directory: `task.toml` (flightdeck's keys under `[flightdeck]`), `instruction.md`, `environment/`, hidden `tests/`, optional `solution/`. Identity: `task_digest`. See [tasks.md](tasks.md) | hangar spec 0008; Harbor |
| **suite** | A versioned list of tasks and specs | |
| **holdout** | A sealed suite, scored once | |
| **knowledge snapshot** | The identity of what a retrieval tool could read for a trial: an index's version or digest. Recorded in the manifest as `knowledge.snapshot` and in the pin set. The knowledge gold set ([knowledge-evals.md](knowledge-evals.md)) pins questions to `as_of` commits instead | hangar manifest `knowledge` |
| **check** | The repository's own command hangar runs after a turn (`verify`), recorded as a `test.run` event; `hangar.test.run.trusted = true` when hangar ran it, false for the agent's own in-turn runs. The agent can see and change it; a grader it never sees | `hangar.trace/v1` |
| **grader** | A task's hidden tests (`tests/test.sh`, which writes `reward.json`), run on the trial's patch in a clean sandbox outside the agent's reach, from a pristine copy. Identity: `files_digest`. Unlike a check, the agent never sees it | `hangar.experiment/v1` `grade`; [tasks.md](tasks.md) |
| **spec** | A behavior predicate over a trace export | |
| **judge** | A model rubric, used only once calibrated against people (κ ≥ 0.6) | |
| **resolved** | The grader passed (`exit_code == 0` and `applied`), else hangar's verify after the turn passed. Reports always say which | |
| **infra_error** | A trial that failed for infrastructure reasons, not the agent's. Retried, and excluded from statistics | |
| **drift** | A trial whose configuration differs from its variant's other trials (`trial.drift`) | `hangar.experiment/v1` |
| **tainted** | A run that read untrusted content; excluded from promotion evidence | |
| **saturated task** | A task where every trial of every arm had the same outcome: it carries no information for a comparison | |
| **discordant pair** | A task where the two arms disagree on the outcome | |

## Words we don't use

- "eval run" for a trial; "test" for a grader (a test is one case in a check or a grader).
- "harness" for the runtime alone, in flightdeck's own text: say runtime.

## What's shipped

Each feature's status, and the page that explains it. *Code merged* means the code is in, and an issue stays open
until it has run for real.

| Feature | Status | Docs |
| --- | --- | --- |
| **Ingest**: hangar REST or `hangar experiment export` into the Parquet data plane, idempotent; `flightdeck query` over it | Shipped ([#7](https://github.com/Sean-Koval/flightdeck/issues/7)) | [Data plane](data-plane.md) |
| **Compactor**: hangar's GCS outbox into the data plane, nightly on Cloud Run | Shipped ([#5](https://github.com/Sean-Koval/flightdeck/issues/5)); needs hangar's outbox on (`HANGAR_OUTBOX_URL`) | [Data plane](data-plane.md#compactor) |
| **Paired statistics**: task bootstrap, Wilson, pass@k and pass^k, $ per resolved task, a power estimate; exclusions always printed | Shipped ([#8](https://github.com/Sean-Koval/flightdeck/issues/8)) | [Statistics](statistics.md) |
| **Behavior specs**: YAML predicates over traces that count only trusted test runs | Shipped ([#14](https://github.com/Sean-Koval/flightdeck/issues/14)) | [Behavior specs](behavior-specs.md) |
| **Nightly checks**: `check run` over a day of the data plane, ADR `checks:`, change-point alerts | Code merged; [#15](https://github.com/Sean-Koval/flightdeck/issues/15) open until it is scheduled with a real team ADR | [ADR checks](adr-checks.md) |
| **Reports**: the pre-registered verdict, pins, outcome, process, cost and spec pass rates, as one PR comment | Shipped ([#9](https://github.com/Sean-Koval/flightdeck/issues/9)) | [Reports](reports.md) |
| **Experiments**: suites of Harbor-compatible tasks submitted to hangar with concrete model pins and a cost gate; a local Docker backend for fixtures and CI | Shipped ([#11](https://github.com/Sean-Koval/flightdeck/issues/11), [#18](https://github.com/Sean-Koval/flightdeck/issues/18)); `harness_lock` variants not yet | [Running experiments](runners.md), [Tasks](tasks.md) |
| **Weekly metrics**: the team's weekly scorecard, one SQL definition over Parquet, as JSON for hangar's digest | Shipped ([#6](https://github.com/Sean-Koval/flightdeck/issues/6)) | [Weekly metrics](metrics.md) |
| **Judges**: rubric judges used only once calibrated against people (κ ≥ 0.6); estimates by prediction-powered inference | Shipped ([#27](https://github.com/Sean-Koval/flightdeck/issues/27)) | [Judges](judges.md) |
| **Sealed holdouts**: hash-manifested, canaried task sets written blind and scored once | Code merged; [#13](https://github.com/Sean-Koval/flightdeck/issues/13) open until the first set is sealed | [Holdouts](holdouts.md) |
| **Knowledge evals**: a 40-question gold set scored on correctness and citation validity | Code merged; [#21](https://github.com/Sean-Koval/flightdeck/issues/21) open until the gold set is written and scored | [Knowledge evals](knowledge-evals.md) |
| **Trial cache**: reuse trials whose inputs haven't changed; a nightly drift sentinel | Code merged; [#24](https://github.com/Sean-Koval/flightdeck/issues/24) open until the sentinel runs nightly | [The trial cache](cache.md) |
| **Mutation scoring**: remove one harness component at a time and check that a grader or spec notices | Code merged; [#16](https://github.com/Sean-Koval/flightdeck/issues/16) open until the first live run | [Mutation scoring](mutation-scoring.md) |
| **Small by design**: 3,785 counted lines of analysis code, enforced in CI | The budget is full; any increase needs a new ADR | [ADR-0005](decisions/0005-post-v0-budget.md) |

Every command and flag is in the [CLI reference](cli.md); what flightdeck reads, writes and pins is in
[Contracts](contracts.md).

## See also

- [Getting started](getting-started.md): the words in use, on the fixture experiment.
- [Reports](reports.md#pre-registration): the verdict rule in full.
- [Statistics](statistics.md): pp, CI, margin and the paired bootstrap, with the numbers.
- [Contracts](contracts.md): what each term maps to in hangar's interfaces and the data plane.
