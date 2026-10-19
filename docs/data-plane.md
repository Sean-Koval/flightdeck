# Data plane: `flightdeck.parquet/v1`

Flightdeck reads hangar's runs from Parquet files, never from a live hangar (ADR-0001 point 3), so reports work while
hangar's sandbox pools are off. Hangar writes each finished run once to a GCS outbox (`hangar.run/v1`, hangar
`docs/api/outbox.md`), the nightly [compactor](#compactor) turns it into these tables, and DuckDB queries them. For
one experiment's results right away, the same flatteners run over `hangar experiment export` and REST exports
([ingest](#ingest)).

<div class="af-figure" markdown>
--8<-- "docs/assets/flow-data-plane.svg"
<figcaption>Two ways in (the nightly compactor, ingest on demand), one set of tables out</figcaption>
</div>

Code: `src/flightdeck/dataplane/` (`schema.py` the tables, `flatten.py` the flatteners, `duck.py` the views,
`compact.py` the compactor, `github.py` the `prs` table).

## Layout and versioning

```
<root>/<table>/dt=YYYY-MM-DD/part-*.parquet      zstd; dt is in the path (hive partitioning), not the file
```

`<root>` is `FLIGHTDECK_DATA_URI`: a local directory or a private `gs://` bucket (ADR-0002). Each file's schema
metadata carries `flightdeck.schema = flightdeck.parquet/v1` and its table name. Within v1, columns are only added;
removing or renaming one is v2. Rows are wide and denormalized: resource attributes (job, session, environment,
person) are copied onto every span row. Every row has `run_id`, `source` (`job`, `session`, `experiment`,
`shadow`, or `local` for the [local backend](runners.md#local)) and `dt`.

## Tables

| Table | Grain | From | Notes |
| --- | --- | --- | --- |
| `runs` | one turn (`run_id` = `hangar.run.id`) or one trial (`run_id` = `<experiment>/<task>/<variant>/<n>`) | trace `turn` span + its job's events; experiment `trials[]` | `verify_passed` from the job's `verify` event (`phase = after_turn`) or the trial's `verify.passed`; `diff_files` from `hangar.diff.files`, since shell writes aren't `file.change` events; `merged`/`merged_by` from `pr.merge`; `truncated` from `hangar.export.truncated` |
| `spans` | one OTLP span | trace | Columns for the taxonomy (`kind` = `hangar.kind`, `tool_kind`, `shell_ops`, `seq`, `seq_end`, `file_repo_path`, `mcp_*`, `approval_*`); everything else in `attrs` JSON. Job/session root spans take the job or session id as `run_id` |
| `events` | one span event, except test results | trace | `steer`/`interrupt` events carry `seq` and, in `attrs`, `hangar.steer.class` since hangar#162; older ones have no seq, so their order is by time only |
| `manifests` | one `hangar.manifest/v1`, deduplicated by `digest` | manifest | `skills_effective` as `name@digest`; `json` keeps the whole manifest |
| `grades` | one grader result for a trial | experiment `trials[].grade` | `data` is the JSON the grader wrote to `$HANGAR_GRADE_OUT` |
| `test_cases` | one `test.run` (its `case_name` is null) or one `test.case` | trace `test.run`/`test.case` events; outbox `tests.json` | `trusted` is false for the agent's own in-turn runs; specs that need proof of testing use `trusted and total > 0` |
| `job_events` | one `hangar.job_event/v1` (`run_id` = job id) | outbox `v1/jobs/{date}/{job_id}/events/` | `kind` (`pr.open`, `review.first`, `pr.merge`, `pr.close`, `abandon`, ...); `reason`, `by` and `green_to_merge_seconds` lifted from `data`, which keeps the rest |
| `prs` | one closed GitHub pull request on the team's repos (`run_id` null, `source` = `github`) | GitHub REST, `flightdeck ingest github` | `reverts` is the number of the PR it reverts; for [agent share and reverts](metrics.md#where-the-data-comes-from) |

From the outbox, `runs` also carries `run.json`'s `outcome_class`, `infra_reason`, `job_source`, `job_turn`,
`job_state`, `steers` (`steers.n`), `questions`, `untrusted` (the job's task text came from outside the trusted list)
and `tainted` (the turn read untrusted content). Promotion evidence leaves out runs with either flag set. Tapes stay
objects under hangar's `v1/tapes/`; they are not compacted.

Flightdeck stamps `runs.task_digest` (the task directory's digest, [tasks.md](tasks.md#digests)) and
`runs.variant_digest` (the variant as planned: its hangar overlay and environment) on the trials it submitted, when it
collects them; they key the [trial cache](runners.md#cache). `trial_reuse` is written by flightdeck too: one row per
trial the cache reused for a run set (`run_id` is the reused trial's, `experiment_id` the run set's, `age_days`).

`judge_labels` is flightdeck's as well: one judge label per run, with the rubric version and digest, the judge model,
the rationale's digest and the rubric's calibration status ([judges.md](judges.md)).

`spec_results` is written by flightdeck, not flattened from hangar: one row per spec or ADR check and unit (a turn, job
or session id in `run_id`), with `spec_id`, `spec_source` (`spec` or `adr:<repo>/<adr>`), `scope`, `result` (`pass`,
`fail`, `not_applicable`, `unknown`), `repo`, `harness_digest` and `knowledge_snapshot`
([behavior-specs.md](behavior-specs.md)).

Nullable now, filled as soon as hangar emits them with no schema change: `harness_digest`, `environment_digest`,
`knowledge_snapshot`, `grader_digest`. `runs.outcome_class` (`agent`, `infra_error`, `cancelled`, `human`; null for
records from before hangar#166) and `infra_reason` come from the trial or the turn span's `hangar.outcome.class` and
`hangar.outcome.infra_reason`; `excluded` and `attempt` from the trial.

## Decoding

OTLP/JSON per opentelemetry-proto 1.11.1: `intValue` is a decimal string, lists are `arrayValue.values`,
`kvlistValue` becomes a dict. Unknown attributes are kept in `attrs`, never an error (hangar adds fields within v1).
A different `hangar.trace.schema`, manifest or experiment schema is refused. Hangar redacts every export; the
flatteners also mask anything that still looks like a credential (private keys, GitHub, Anthropic/OpenAI, AWS and
Slack tokens) as `***`, and clip event text to 2,000 characters.

## Ingest

For an author who wants one experiment's results now, without waiting for the night's compaction (or where the
outbox is off), `flightdeck ingest` pulls from hangar directly. Code: `src/flightdeck/dataplane/ingest.py`.

```sh
flightdeck ingest export DIR                                  # files from `hangar experiment export <id> -o DIR`
flightdeck ingest experiment <id> --hangar URL                # REST; bearer token from HANGAR_TOKEN
flightdeck ingest job <id> --hangar URL                       # GET /api/jobs/{id}/trace + /manifest?turn=N
flightdeck ingest session <name> [--turn N] --hangar URL      # GET /api/sessions/{name}/trace + /manifest?turn=N
```

All write to `--out` (default `~/.flightdeck/data`, or `FLIGHTDECK_DATA_URI`), with `source` = `experiment`, `job` or
`session`.

- **REST and export are one path.** REST ingest streams the index and each trial's `links.manifest`/`links.trace` to
  `<out>/raw/<id>/` in `hangar experiment export`'s layout (`index.json`, `trials/<task>__<variant>__<n>[~<attempt>]/*.json`), then
  reads that directory like an export. Both produce identical tables, and nothing large is held in memory.
- **Experiments.** One `runs` row per trial, from the index. A trial's spans, events and test results take the
  trial's `run_id` (`<experiment>/<task>/<variant>/<n>`), and its run row is `truncated` when its trace was. A trial
  hangar retried after an infrastructure error (hangar#166) keeps its row, `excluded`, and the retry is a second row
  under the same `trial_key` with `run_id` `<experiment>/<task>/<variant>/<n>~<attempt>`. Pins that break hangar's
  model rule are warned about, as `experiment status` reports them. A trial
  still pending or running has `outcome` null; statistics leave it out. Drifted trials (`trials[].drift`) are kept,
  with `drift` set; `flightdeck stats compare` excludes them unless `--include-drift`. Hangar's #127 anti-forgery
  fields land in `runs.task_invalid`, `runs.contaminated` and `runs.grade_trust`.
- **Idempotent.** Each unit (an experiment, a job, a session) owns one Parquet part per table and day,
  `part-<unit>.parquet`. Re-ingesting replaces the unit's rows by `run_id`, so it adds no duplicates, and a trial that
  finished on a later day moves partitions instead of staying behind.
- **Validation.** The index and manifests are checked against hangar's `experiment.schema.json` and
  `manifest.schema.json`, vendored in `src/flightdeck/dataplane/hangar_schemas/` with the hangar commit they came from
  (`SOURCE.json`); `python scripts/sync_hangar_schemas.py --hangar ../hangar` refreshes them. A mismatch warns and the
  ingest continues: the flatteners keep what they understand, and the raw JSON stays in the export or `raw/` directory.
- **Tokens.** Hangar scopes every record to its owner (spec 0014 §1): a member token sees its own experiments, jobs and
  sessions, an admin token everyone's, a `jobs` token what it submitted. A 404 means missing *or not yours* and is
  reported that way. A report on your own experiment needs only your member token; a team-wide report needs an admin
  token, kept in the operator's environment.

## Compactor

`flightdeck compact` turns hangar's outbox into the tables above. Code: `src/flightdeck/dataplane/compact.py`;
deployment: [`deploy/compactor/`](https://github.com/Sean-Koval/flightdeck/tree/main/deploy/compactor). It runs as a
Cloud Run job at 02:30 ET, inside the pools-off window: the control plane and GCS stay up, the cluster doesn't need to.

```sh
flightdeck compact --input gs://<runs-bucket> --out gs://<team>-flightdeck/parquet/v1     # today and 3 days back
flightdeck compact --date 2026-11-03 --rebuild                                            # rewrite those dates
flightdeck compact --input file:///tmp/outbox --out /tmp/plane                            # a local outbox tree
```

`--input` (`FLIGHTDECK_RUNS_URI`) and `--out` (`FLIGHTDECK_DATA_URI`) take `gs://`, `file://`, a plain path or any
fsspec URL; `gs://` needs the `gcs` extra.

- **Complete runs only.** It reads `v1/runs/{date}/{session_id}.{run_id}/` directories that have a `run.json`: hangar
  uploads it after the run's other objects, so a directory without one is still arriving and waits for a later night.
  A run's rows come from `run.json` (the `runs` row, laid over the trace's turn row), `trace.otlp.json` (spans,
  events), `tests.json` (test_cases), `manifest.json` and `grade.json`. Job events come from `v1/jobs/{date}/`.
  Everything passes through the flatteners' credential masking again.
- **One partition per date.** Each outbox date is one `dt=` partition per table, `part-0.parquet`, rewritten whole:
  written as `part-0.parquet.tmp`, then renamed, so readers never see half a file. Rows are sorted by `run_id, seq`,
  so a rebuild of the same inputs is byte-identical. Row groups are sized to about 64 MB.
- **Late arrivals.** `<out>/_compactor/{date}.json` records the date's input objects (path, size, GCS generation and,
  for what was read, sha256). Each night looks back `--lookback` days (3) and recompacts a date only when its listing
  changed: a late `run.json`, a `grade.json` that followed its run, or a deleted run. One prefix listing per date, no
  per-object metadata calls.
- **Identity.** The job's service account has `storage.objectViewer` on the outbox bucket and `storage.objectAdmin`
  on the flightdeck bucket, nothing else; no hangar endpoint or token (a test asserts the module imports no HTTP
  client).

### Runbook

- **Rebuild a date** (after a fix to the flatteners, or to pick up something older than the lookback):
  `gcloud run jobs execute flightdeck-compactor --region <r> --args=--date,2026-11-03,--lookback,0,--rebuild`, or run
  `flightdeck compact --date 2026-11-03 --lookback 0 --rebuild` locally with read access to both buckets.
- **Delete a run** (personal data): delete its objects from the outbox with an admin credential
  (`gcloud storage rm -r gs://<runs-bucket>/v1/runs/<date>/<session_id>.<run_id>/`, and its job's event objects), or,
  where objects can't be deleted yet, list it in `gs://<runs-bucket>/v1/_deletions/<request>.json` as
  `{"runs": ["<session_id>.<run_id>" or "<run_id>", ...]}`. Then rebuild its date. Within the lookback window the next
  night does this on its own, so a deletion is out of Parquet within 24 hours.
- **Deploy:** `sh deploy/compactor/setup.sh --project <p> --runs-bucket <hangar's run_bucket> --data-bucket <team>-flightdeck`
  ([its README](https://github.com/Sean-Koval/flightdeck/tree/main/deploy/compactor#deploy); `--dry-run` first). Hangar's
  GKE terraform makes the outbox bucket (output `run_bucket`) and its `deploy/gke/up.sh` turns the outbox on.
- **Check a night:** the job's log prints rows per table per date, or `unchanged`; `flightdeck query --data
  gs://<team>-flightdeck/parquet/v1 "select dt, count(*) from runs group by dt"` reads what it wrote.

## `flightdeck.weekly/v1`

[`flightdeck metrics weekly`](metrics.md) writes `<reports>/weekly/<week>.json`, `<week>.md` and `latest.json`, with
`FLIGHTDECK_REPORTS_URI` = `gs://<team>-flightdeck/reports`. Hangar's standup line and digest read `latest.json` and
never recompute. JSON Schema:
[`src/flightdeck/metrics/weekly.schema.json`](https://github.com/Sean-Koval/flightdeck/blob/main/src/flightdeck/metrics/weekly.schema.json);
additive within v1.

| Field | Meaning |
| --- | --- |
| `schema`, `week`, `start`, `end` | `flightdeck.weekly/v1`; the ISO week (`2026-W45`), its Monday and the next Monday (UTC) |
| `scope` | `{person, repo}`; both null in the shared files |
| `metrics` | one object per metric in [metrics.md](metrics.md): rates as `{k, n, rate, ci95}` (Wilson 95%; null when `n` is 0), `review_wait` and `green_to_merge` as `{n, p50_h, p90_h}`, the rest as `{n, value}`; `abandon.by_reason` maps reason to count |
| `trailing` | the four weeks ending with `week`, oldest first, each `{week, metrics}` |

## Querying

```sh
flightdeck query "select variant, count(*) from runs join grades using (run_id) group by 1" --data ./plane
```

`duck.connect(uri)` registers one view per table (`read_parquet(..., hive_partitioning=true, union_by_name=true)`); a
table without files is an empty view of its schema. Timestamps are shown in UTC. For `gs://`, install the `gcs` extra
(`uv sync --extra gcs`, or `pip install 'flightdeck[gcs]'`): DuckDB then reads through gcsfs with your Google
application-default credentials (`gcloud auth application-default login`). Without it, DuckDB's `httpfs` is loaded and
the caller supplies a DuckDB GCS secret (HMAC keys). Flightdeck holds no credentials either way.

```sh
uv sync --extra gcs
flightdeck query "select count(*) from runs" --data gs://<private-bucket>/plane
```

Truncated exports (`hangar.export.truncated`, hangar's 20,000-item cap) set `runs.truncated`; process metrics (tool
calls, cost, wall time) leave those trials out by default and say so, while outcome metrics keep them.

## Size

About 1.5 MiB of OTLP per run gives roughly 1.5 GiB a month as zstd Parquet at the team's volume. DuckDB over Parquet
is enough until about 1 TB.
