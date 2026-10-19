# Contracts

What flightdeck reads, what it writes, the files a team commits for it, and the pin set it judges trials by.

Every contract here is additive within its version. A new optional field is not a new version; removing or renaming
one is.

## What flightdeck reads

Only hangar's versioned interfaces and the Parquet data plane, never hangar's database or data directory
([ADR-0001](decisions/0001-boundary-with-hangar.md)).

| Interface | What it is | Read by |
| --- | --- | --- |
| `hangar.manifest/v1` | The effective harness manifest a turn ran with (hangar [`manifest.schema.json`](https://github.com/Sean-Koval/hangar/blob/main/docs/api/manifest.schema.json)) | `ingest`, `experiment collect`, and the compactor (`manifest.json`), into `manifests` |
| `hangar.trace/v1` | A turn's, job's or session's OTLP/JSON trace export (hangar [`traces.md`](https://github.com/Sean-Koval/hangar/blob/main/docs/api/traces.md)) | `ingest`, `experiment collect`, and the compactor (`trace.otlp.json`), into `spans`, `events`, `test_cases` |
| `hangar.experiment/v1` | An experiment's index of trials, `GET /api/experiments/{id}` (hangar [`experiment.schema.json`](https://github.com/Sean-Koval/hangar/blob/main/docs/api/experiment.schema.json)) | `ingest experiment`, `ingest export`, `experiment status` and `collect`, into `runs`, `grades` |
| `hangar.run/v1` | One finished run's `run.json` in hangar's GCS outbox (hangar [`outbox.md`](https://github.com/Sean-Koval/hangar/blob/main/docs/api/outbox.md)), with `tests.json` (`hangar.tests/v1`) and, for a trial, `grade.json` (`hangar.grade/v1`) | `compact`, into `runs`, `test_cases`, `grades` |
| `hangar.job_event/v1` | A fact about a job that arrives after its runs (`pr.open`, `review.first`, `pr.merge`, `pr.close`, `revert`, `abandon`, `label`), under `v1/jobs/{date}/{job_id}/events/` (`$defs.job_event` in `run.schema.json`) | `compact`, into `job_events` |

How they're checked:

- **Manifests and experiment indexes** are validated against the vendored JSON Schemas (below). A mismatch warns and
  the ingest goes on. A document whose `schema` isn't `hangar.manifest/v1` or `hangar.experiment/v1` is refused.
- **Traces** have no JSON Schema: the resource's `hangar.trace.schema` must be `hangar.trace/v1`, and unknown
  attributes are kept in `attrs`.
- **Outbox objects** (`run.json`, job events) aren't validated at compaction; the compactor keeps what it understands.
  The test fixtures that stand in for them are checked against the vendored `run.schema.json`.

Flightdeck also reads GitHub REST for closed pull requests (`ingest github` → `prs`) and ADRs from git
(`check run --adrs`).

### The vendored schemas

`src/flightdeck/dataplane/hangar_schemas/` holds `experiment.schema.json`, `manifest.schema.json` and
`run.schema.json`, copied from hangar commit
[`6dc8a39`](https://github.com/Sean-Koval/hangar/commit/6dc8a395639c164dd884f10f8baa32ba2cc85c49) (2026-10-17;
`SOURCE.json`). They lag hangar's main. Since then hangar has added, within v1:

- `hangar.experiment/v1`: a variant's `harness_lock`, `harness_revision`, `harness_digest`, `pin_set` and
  `model_source` (and `harness_lock` as a `model_concrete_basis`), a task's `task_digest`, a trial's `pin_set` and
  `cached`, and the spec's `pin_sets`, `task_digests`, `cache_record` and `source`;
- `hangar.run/v1`: the `pr.ready` job event, and `counted` and `agent_run_id` on test runs;
- `hangar.manifest/v1`: nothing.

flightdeck also reads one optional field hangar does not write yet: a `description` on each of `pins.variants`
(one line saying what the arm is, such as *the review skill*). The report names the arms with it; without it the
arms are their names. The fixture carries it, and an experiment index may add it by hand.

So the index of an experiment whose variants run from harness locks fails the vendored check:
`model_concrete_basis: harness_lock` isn't in its enum. Ingest warns and goes on, and the new fields stay in the raw
JSON.

`python scripts/sync_hangar_schemas.py --hangar ../hangar` refreshes the copies. That refresh goes with accepting
`harness_lock` variants in `experiment run`, which refuses them today (`VARIANT_KEYS` in
`src/flightdeck/runners/hangar.py`). That needs counted lines, and the [line budget](decisions/0005-post-v0-budget.md)
has none left, so both wait for a new budget ADR.

## What flightdeck writes

| Contract | What | Where | Defined in |
| --- | --- | --- | --- |
| `flightdeck.parquet/v1` | The data plane: one table per kind of record, partitioned by day | `<root>/<table>/dt=YYYY-MM-DD/part-*.parquet`, `<root>` = `FLIGHTDECK_DATA_URI` (private) | `src/flightdeck/dataplane/schema.py`; [Data plane](data-plane.md); columns below |
| `flightdeck.spec/v1` | Behavior specs and ADR `checks:`: YAML predicates over `hangar.trace/v1` | Team specs in the private data repository; public examples in [`specs/examples/`](https://github.com/Sean-Koval/flightdeck/tree/main/specs/examples) | `src/flightdeck/specs/lang.py`; [Behavior specs](behavior-specs.md) |
| `flightdeck.weekly/v1` | The weekly team metrics as JSON (and markdown) | `<reports>/weekly/<week>.json`, `<week>.md`, `latest.json`, `<reports>` = `FLIGHTDECK_REPORTS_URI` | [`weekly.schema.json`](https://github.com/Sean-Koval/flightdeck/blob/main/src/flightdeck/metrics/weekly.schema.json); [Data plane](data-plane.md#flightdeckweeklyv1) |
| `hangar.experiment/v1` spec | What `experiment run` submits: tasks, variants, trials, one grader, budgets | `POST /api/experiments` on hangar | [Running experiments](runners.md) |
| Report | One markdown comment per experiment, first line `<!-- flightdeck:report:<experiment> -->`, updated in place | The pull request or issue named by `--post` / `--to` | [Reports](reports.md) |

In the private data repository flightdeck also writes `holdouts/manifest.json` and `holdouts/results/<set>.json`
([Holdouts](holdouts.md)), the knowledge suite's `manifest.json` ([Knowledge evals](knowledge-evals.md)) and a
rubric's `<rubric>.calibration.json` ([Judges](judges.md)).

### `flightdeck.parquet/v1` columns

<!-- generated:parquet by scripts/docs_reference.py -->

Every table also has `run_id`, `source` and `dt` (`flightdeck.parquet/v1`; `dt` is the partition, in the path). Columns are text unless a type is given.

| Flattened from hangar | Columns |
| --- | --- |
| `runs` | `job_id`, `session_id`, `turn` int, `experiment_id`, `trial_key`, `task_id`, `variant`, `trial` int, `person`, `repo`, `environment`, `harness`, `harness_version`, `model_id`, `outcome`, `reason`, `outcome_class`, `infra_reason`, `excluded` bool, `attempt` int, `config_digest`, `harness_digest`, `environment_digest`, `manifest_digest`, `base_sha`, `cost_usd` float, `cost_source`, `input_tokens` int, `output_tokens` int, `cache_read_tokens` int, `started_at` timestamp, `finished_at` timestamp, `verify_passed` bool, `pr_url`, `pr_number` int, `merged` bool, `merged_by`, `diff_files` list of strings, `drift` list of strings, `truncated` bool, `task_invalid` bool, `contaminated` bool, `grade_trust`, `job_source`, `job_turn` int, `job_state`, `steers` int, `questions` int, `untrusted` bool, `tainted` bool, `task_digest`, `variant_digest`, `variant_description` |
| `spans` | `trace_id`, `span_id`, `parent_span_id`, `job_id`, `session_id`, `environment`, `person`, `kind`, `name`, `start_ns` int, `end_ns` int, `seq` int, `seq_end` int, `status_code` int, `tool_kind`, `tool_name`, `tool_input`, `tool_output`, `tool_ok` bool, `shell_ops` list of strings, `file_repo_path`, `mcp_server`, `mcp_tool`, `skill_name`, `approval_status`, `approval_by`, `attrs` |
| `events` | `trace_id`, `span_id`, `span_kind`, `name`, `time_ns` int, `seq` int, `file_repo_path`, `file_op`, `text`, `attrs` |
| `manifests` | `digest`, `config_digest`, `captured_at` timestamp, `subject_kind`, `session_id`, `turn` int, `job_id`, `person`, `harness_name`, `harness_version`, `harness_locked`, `harness_mode`, `harness_digest`, `model_id`, `model_policy`, `model_provider`, `skills_effective` list of strings, `mcp_servers` list of strings, `hooks` list of strings, `approvals`, `egress_mode`, `environment_name`, `environment_spec_digest`, `environment_digest`, `knowledge_snapshot`, `repo_url`, `base_sha`, `json` |
| `grades` | `experiment_id`, `trial_key`, `command`, `exit_code` int, `applied` bool, `seconds` float, `error`, `data`, `grader_digest` |
| `test_cases` | `trace_id`, `test_run_id`, `suite`, `status`, `run_kind`, `trusted` bool, `exit_code` int, `total` int, `passed` int, `failed` int, `errors` int, `skipped` int, `complete` bool, `flaky` int, `time_ns` int, `case_name`, `case_status`, `case_outcome`, `sha` |

| From the outbox and GitHub | Columns |
| --- | --- |
| `job_events` | `job_id`, `kind`, `ts` timestamp, `job_source`, `repo`, `person`, `environment`, `session_id`, `run_ids` list of strings, `pr_url`, `pr_number` int, `untrusted` bool, `reason`, `by`, `green_to_merge_seconds` float, `data` |
| `prs` | `repo`, `number` int, `url`, `title`, `author`, `author_bot` bool, `created_at` timestamp, `merged_at` timestamp, `closed_at` timestamp, `merge_sha`, `reverts` int |

| Written by flightdeck | Columns |
| --- | --- |
| `spec_results` | `spec_id`, `spec_source`, `scope`, `result`, `repo`, `harness_digest`, `knowledge_snapshot` |
| `trial_reuse` | `experiment_id`, `task_id`, `variant`, `age_days` float |
| `judge_labels` | `rubric`, `rubric_digest`, `judge`, `label` float, `rationale_digest`, `status` |

<!-- /generated:parquet -->

## Files a team commits

| File | Read by | Keys | Lives in | Docs |
| --- | --- | --- | --- | --- |
| A suite (`suite.yaml`, any name) | `experiment run`, `mutate plan`, `cache sentinel` | `suite`, `tasks` (task directories or directories of them, relative to the file), `variants` (hangar's overlay: `environment`, `harness[@version]`, `model`, `approvals`, `skills`, `skills_remove`, `instructions`, `instructions_append`), `n`, `environment`, `budget_usd`, `trial_budget_usd`, `parallel` | Beside its tasks | [Running experiments](runners.md#commands) |
| `decision.yaml` | `report experiment --decision` | `metric` (`resolved`, `cost_usd`, `tool_calls`, `wall_s`), `direction` (`higher` or `lower`), `margin` (in the metric's units), `min_tasks` (default 10), optional `rubric` | Committed before the first trial finishes | [Reports](reports.md#pre-registration) |
| `budgets.yaml` | `experiment run`'s cost gate (`--budgets`, `FLIGHTDECK_BUDGETS`, else `./budgets.yaml`) | `month_usd`, `authors: {<login>: <usd>}` | The private data repository | [Running experiments](runners.md#the-cost-gate) |
| `task.toml`, `[flightdeck]` | Every command that loads a task | `tags`, `sealed`, `environment`, `mined_after`, `mined_from`; `[flightdeck.source]` `repo`, `base_sha`, `base_branch`, `issue`, `verify`; `[flightdeck.grader]` `command`, `files_digest` | Each task directory (Harbor's keys stay where Harbor puts them) | [Tasks](tasks.md#layout) |
| A rubric (YAML) | `judge label` / `calibrate` / `score` / `estimate`, and `decision.yaml`'s `rubric` | `id`, `version`, `question`, `scale` (`binary`, or `ordinal` with `levels`), `criteria`, `examples`, `judge: {model, prompt}` (a concrete model id) | The private data repository | [Judges](judges.md#a-rubric-version) |
| An ADR with `checks:` | `check run --adrs` | `checks:` in its front matter with `status: accepted`, or in a fenced `yaml` block under a `Status: Accepted` line; each check is a spec without the header (`id`, `scope`, `applies_when`, `harness`, `assert`) | The team's repositories, `docs/decisions/` | [Behavior specs](behavior-specs.md#adr-checks-and-the-nightly-runner) |

## The pin set

The seam between hangar and flightdeck is a trial run against an immutable **pin set**: what the trial runs with,
content-addressed. So a baseline pinned today re-runs identically next month (hangar
[`docs/api/trials.md`](https://github.com/Sean-Koval/hangar/blob/main/docs/api/trials.md), `hangar.pinset/v1`).

Flightdeck owns the sampling: which tasks, how many trials, against which pin sets, when to stop. Hangar runs each
trial as pinned. Flightdeck still submits batch experiments, whose variants hangar records as pin sets; submitting
trials against pin sets directly is [#25](https://github.com/Sean-Koval/flightdeck/issues/25).

| Field | What it pins | In hangar today | In flightdeck's data plane |
| --- | --- | --- | --- |
| `harness_digest` | A SHA-256 over the harness lock's identity fields (the lock projected onto the manifest's harness sections), equal to the manifest's `harness_digest` | Optional in manifests (absent from those stored before it); required with its lock in a pin set; an overlay variant's is null until its first trial finishes | `runs.harness_digest`, `manifests.harness_digest`; null for older records |
| `environment_digest` | Image, build, effective egress, resources and isolation | Optional in manifests and in pin sets: without it a pin set pins `environment_spec_digest`, and the trial cache keys on `environment_digest`, else `environment_spec_digest` | `runs.environment_digest`; `manifests.environment_digest` and `environment_spec_digest` |
| `model_id` | The concrete model id ([hangar#167](https://github.com/Sean-Koval/hangar/issues/167)) | Required to be concrete; null when the harness runs its own default | `runs.model_id`, `manifests.model_id` |
| `base_sha` | Each task's base commit | Required per task in a pin set; `pins.tasks.<id>.base_sha` in the experiment index | `runs.base_sha` |
| `grader_digest` | The grader's command, files, mode, network and timeout | In pin sets; not in the experiment index or the outbox's `grade.json` | `grades.grader_digest`: null today. The trial cache uses `task_digest`, which covers the tests and the grader command, in its place |
| `knowledge_snapshot` | What a retrieval tool could read | Optional, once a retrieval tool exists; the manifest schema has no `knowledge` section yet | `manifests.knowledge_snapshot`: null today |

Hangar's pin set also records the harness and its CLI version, the lock reference, the environment, the approvals
policy and the egress policy's digest.

Until every trial carries `harness_digest` and `environment_digest`, flightdeck's reports and cache fall back to
`config_digest`, which mixes the two halves. The cache adds the manifest's `environment.build.id`. See the report's
Pins table ([Reports](reports.md#anatomy)) and the cache key ([Running experiments](runners.md#cache)).

## See also

- [Data plane](data-plane.md): the tables behind `flightdeck.parquet/v1`, and how they are filled.
- [CLI reference](cli.md): every command and option, generated from the code.
- [ADR 0001: Boundary with hangar](decisions/0001-boundary-with-hangar.md): why only these interfaces.
- [Concepts](concepts.md): the words the contracts use.
