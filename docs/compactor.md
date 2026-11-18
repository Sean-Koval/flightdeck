# The compactor

How do every night's runs reach the data plane? `flightdeck compact` turns hangar's outbox into Parquet, as a Cloud
Run job.

It writes the [data plane](data-plane.md)'s tables. Code: `src/flightdeck/dataplane/compact.py`;
deployment: [`deploy/compactor/`](https://github.com/Sean-Koval/flightdeck/tree/main/deploy/compactor).

It runs as a Cloud Run job at 02:30 ET, inside the pools-off window. The control plane and GCS stay up; the cluster
doesn't need to.

```sh
flightdeck compact --input gs://<runs-bucket> --out gs://<team>-flightdeck/parquet/v1     # today and 3 days back
flightdeck compact --date 2026-11-03 --rebuild                                            # rewrite those dates
flightdeck compact --input file:///tmp/outbox --out /tmp/plane                            # a local outbox tree
```

`--input` (`FLIGHTDECK_RUNS_URI`) and `--out` (`FLIGHTDECK_DATA_URI`) take `gs://`, `file://`, a plain path or any
fsspec URL. `gs://` needs the `gcs` extra.

## Complete runs only

It reads `v1/runs/{date}/{session_id}.{run_id}/` directories that have a `run.json`. hangar uploads that file after
the run's other objects, so a directory without one is still arriving and waits for a later night.

A run's rows come from `run.json` (the `runs` row, laid over the trace's turn row), `trace.otlp.json` (spans,
events), `tests.json` (test_cases), `manifest.json` and `grade.json`. Job events come from `v1/jobs/{date}/`.
Everything passes through the flatteners' credential masking again.

## One partition per date

Each outbox date is one `dt=` partition per table, `part-0.parquet`, rewritten whole. It is written as
`part-0.parquet.tmp`, then renamed, so readers never see half a file.

Rows are sorted by `run_id, seq`, so a rebuild of the same inputs is byte-identical. Row groups are sized to about
64 MB.

## Late arrivals

`<out>/_compactor/{date}.json` records the date's input objects: path, size, GCS generation and, for what was read,
sha256. Each night looks back `--lookback` days (3) and recompacts a date only when its listing changed: a late
`run.json` or `grade.json`, or a deleted run. One prefix listing per date, no per-object metadata calls.

## Identity

The job's service account has `storage.objectViewer` on the outbox bucket and `storage.objectAdmin` on the
flightdeck bucket, nothing else. No hangar endpoint or token; a test asserts the module imports no HTTP client.

## Runbook

**Rebuild a date**, after a fix to the flatteners or to pick up something older than the lookback:
`gcloud run jobs execute flightdeck-compactor --region <r> --args=--date,2026-11-03,--lookback,0,--rebuild`. Or run
`flightdeck compact --date 2026-11-03 --lookback 0 --rebuild` locally with read access to both buckets.

**Delete a run** (personal data): delete its objects from the outbox with an admin credential
(`gcloud storage rm -r gs://<runs-bucket>/v1/runs/<date>/<session_id>.<run_id>/`, and its job's event objects). Where
objects can't be deleted yet, list it in `gs://<runs-bucket>/v1/_deletions/<request>.json` as
`{"runs": ["<session_id>.<run_id>" or "<run_id>", ...]}`. Then rebuild its date.

Within the lookback window the next night does this on its own, so a deletion is out of Parquet within 24 hours.

**Deploy:**
`sh deploy/compactor/setup.sh --project <p> --runs-bucket <hangar's run_bucket> --data-bucket <team>-flightdeck`
([its README](https://github.com/Sean-Koval/flightdeck/tree/main/deploy/compactor#deploy); `--dry-run` first).
hangar's GKE terraform makes the outbox bucket (output `run_bucket`), and its `deploy/gke/up.sh` turns the outbox on.

**Check a night:** the job's log prints rows per table per date, or `unchanged`.
`flightdeck query --data gs://<team>-flightdeck/parquet/v1 "select dt, count(*) from runs group by dt"` reads what it
wrote.

## Next

- [Data plane](data-plane.md): the tables and their layout.
- [Ingest](ingest.md): one experiment now, without waiting for the night.
- [Weekly metrics](metrics.md): the scorecard the nightly job refreshes.
