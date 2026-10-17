# Data plane: `flightdeck.parquet/v1`

Flightdeck reads hangar's runs from Parquet files, never from a live hangar (ADR-0001 point 3), so reports work while
hangar's sandbox pools are off. The plan: hangar writes each finished run to a GCS outbox
(`gs://<bucket>/v1/{date}/{run_id}/{manifest.json, trace.otlp.json, grade.json, ...}`), a nightly compactor turns it
into these tables, and DuckDB queries them. Until the outbox exists, the same flatteners run over
`hangar experiment export` and REST exports.

Code: `src/flightdeck/dataplane/` (`schema.py` the tables, `flatten.py` the flatteners, `duck.py` the views).

## Layout and versioning

```
<root>/<table>/dt=YYYY-MM-DD/part-*.parquet      zstd; dt is in the path (hive partitioning), not the file
```

`<root>` is `FLIGHTDECK_DATA_URI`: a local directory or a private `gs://` bucket (ADR-0002). Each file's schema
metadata carries `flightdeck.schema = flightdeck.parquet/v1` and its table name. Within v1, columns are only added;
removing or renaming one is v2. Rows are wide and denormalized: resource attributes (job, session, environment,
person) are copied onto every span row. Every row has `run_id`, `source` (`job`, `session`, `experiment`,
`shadow`) and `dt`.

## Tables

| Table | Grain | From | Notes |
| --- | --- | --- | --- |
| `runs` | one turn (`run_id` = `hangar.run.id`) or one trial (`run_id` = `<experiment>/<task>/<variant>/<n>`) | trace `turn` span + its job's events; experiment `trials[]` | `verify_passed` from the job's `verify` event (`phase = after_turn`) or the trial's `verify.passed`; `diff_files` from `hangar.diff.files`, since shell writes aren't `file.change` events; `merged`/`merged_by` from `pr.merge`; `truncated` from `hangar.export.truncated` |
| `spans` | one OTLP span | trace | Columns for the taxonomy (`kind` = `hangar.kind`, `tool_kind`, `shell_ops`, `seq`, `seq_end`, `file_repo_path`, `mcp_*`, `approval_*`); everything else in `attrs` JSON. Job/session root spans take the job or session id as `run_id` |
| `events` | one span event, except test results | trace | `seq` is null for `steer`/`interrupt` (hangar gives them none yet), so their order is by time only |
| `manifests` | one `hangar.manifest/v1`, deduplicated by `digest` | manifest | `skills_effective` as `name@digest`; `json` keeps the whole manifest |
| `grades` | one grader result for a trial | experiment `trials[].grade` | `data` is the JSON the grader wrote to `$HANGAR_GRADE_OUT` |
| `test_cases` | one `test.run` (its `case_name` is null) or one `test.case` | trace `test.run`/`test.case` events | `trusted` is false for the agent's own in-turn runs; specs that need proof of testing use `trusted and total > 0` |

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

Until the outbox and compactor exist (and afterwards, for an author who wants one experiment's results now),
`flightdeck ingest` pulls from hangar directly. Code: `src/flightdeck/dataplane/ingest.py`.

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
