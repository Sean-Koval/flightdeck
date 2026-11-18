# Ingest

How does one experiment get into the data plane now, without waiting for the night? `flightdeck ingest` pulls
it from hangar, or reads an export.

It covers the wait for the night's [compaction](compactor.md), and a hangar whose outbox is off. Code:
`src/flightdeck/dataplane/ingest.py`.

```sh
flightdeck ingest export DIR                                  # files from `hangar experiment export <id> -o DIR`
flightdeck ingest experiment <id> --hangar URL                # REST; bearer token from HANGAR_TOKEN
flightdeck ingest job <id> --hangar URL                       # GET /api/jobs/{id}/trace + /manifest?turn=N
flightdeck ingest session <name> [--turn N] --hangar URL      # GET /api/sessions/{name}/trace + /manifest?turn=N
flightdeck ingest file TRACE.json [--manifest M.json]         # a saved trace: the same rows, no hangar or token
```

All write to `--out` (default `~/.flightdeck/data`, or `FLIGHTDECK_DATA_URI`), with `source` = `experiment`, `job` or
`session`.

## REST and export are one path

REST ingest streams the index and each trial's `links.manifest` and `links.trace` to `<out>/raw/<id>/`, in
`hangar experiment export`'s layout (`index.json`, `trials/<task>__<variant>__<n>[~<attempt>]/*.json`). Then it reads
that directory like an export. Both produce identical tables, and nothing large is held in memory.

## Experiments

One `runs` row per trial, from the index. A trial's spans, events and test results take the trial's `run_id`
(`<experiment>/<task>/<variant>/<n>`), and its run row is `truncated` when its trace was.

A trial hangar retried after an infrastructure error (hangar#166) keeps its row, `excluded`. The retry is a second
row under the same `trial_key`, with `run_id` `<experiment>/<task>/<variant>/<n>~<attempt>`.

Pins that break hangar's model rule are warned about, as `experiment status` reports them. A trial still pending or
running has `outcome` null, and statistics leave it out.

Drifted trials (`trials[].drift`) are kept, with `drift` set; `flightdeck stats compare` excludes them unless
`--include-drift`. hangar's #127 anti-forgery fields land in `runs.task_invalid`, `runs.contaminated` and
`runs.grade_trust`.

## Idempotent

Each unit (an experiment, a job, a session) owns one Parquet part per table and day, `part-<unit>.parquet`.
Re-ingesting replaces the unit's rows by `run_id`, so it adds no duplicates. A trial that finished on a later day
moves partitions instead of staying behind.

## Validation

The index and manifests are checked against hangar's `experiment.schema.json` and `manifest.schema.json`. Those are
vendored in `src/flightdeck/dataplane/hangar_schemas/` with the hangar commit they came from (`SOURCE.json`);
`python scripts/sync_hangar_schemas.py --hangar ../hangar` refreshes them.

A mismatch warns and the ingest continues. The flatteners keep what they understand, and the raw JSON stays in the
export or `raw/` directory.

## Tokens

hangar scopes every record to its owner (spec 0014 §1). A member token sees its own experiments, jobs and sessions;
an admin token sees everyone's; a `jobs` token sees what it submitted. A 404 means missing *or not yours*, and is
reported that way.

A report on your own experiment needs only your member token. A team-wide report needs an admin token, kept in the
operator's environment.

## Next

- [Data plane](data-plane.md): the tables these rows land in.
- [The compactor](compactor.md): the nightly path from hangar's outbox.
- [Statistics](statistics.md): what reads the trials once they are in.
