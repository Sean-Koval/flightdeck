# The nightly compactor on Cloud Run

`flightdeck compact` as a Cloud Run job, started by Cloud Scheduler at 02:30 America/New_York, inside the window when
hangar's sandbox pools are off (the control plane and GCS stay up). What it does, the partition layout, late arrivals
and deletions: [docs/data-plane.md#compactor](../../docs/data-plane.md#compactor). The metrics it refreshes:
[docs/metrics.md](../../docs/metrics.md).

| File | What |
| --- | --- |
| `Dockerfile` | `python:3.12-slim` + `uv sync --locked --no-dev --extra gcs`; build from the repository root |
| `nightly.sh` | the job's entrypoint: `flightdeck compact "$@"`, then `flightdeck ingest github` when `FLIGHTDECK_GITHUB_REPOS` is set, then `flightdeck metrics weekly` when `FLIGHTDECK_REPORTS_URI` is set |
| `cloudbuild.yaml` | builds and pushes the image with Cloud Build |
| `cloudrun-job.yaml` | the job: 1 vCPU, 2 GiB, 30-minute timeout, one retry, its service account and environment |
| `setup.sh` | creates everything below; `--dry-run` prints the commands and the rendered job instead |

## Deploy

```sh
sh deploy/compactor/setup.sh --project <team-project> --runs-bucket <hangar-outbox-bucket> \
  --data-bucket <team>-flightdeck [--region us-east1] [--github-repos owner/repo,owner/repo2] --dry-run
```

Read the dry run, then run it without `--dry-run`. It:

1. enables Cloud Run, Cloud Scheduler, Artifact Registry, Cloud Build and Secret Manager;
2. creates the service account `flightdeck-compactor` with `roles/storage.objectViewer` on the outbox bucket and
   `roles/storage.objectAdmin` on the flightdeck bucket only (no hangar token, no project-wide role);
3. with `--github-repos`, grants it `secretAccessor` on the secret `flightdeck-github-token`, a read-only GitHub token
   you create first: `printf %s "$TOKEN" | gcloud secrets create flightdeck-github-token --data-file=-`;
4. builds the image into `<region>-docker.pkg.dev/<project>/flightdeck/compactor:latest`;
5. creates or replaces the job `flightdeck-compactor` with `FLIGHTDECK_RUNS_URI=gs://<runs-bucket>`,
   `FLIGHTDECK_DATA_URI=gs://<data-bucket>/parquet/v1` and `FLIGHTDECK_REPORTS_URI=gs://<data-bucket>/reports`;
6. schedules `flightdeck-compactor-nightly` (`30 2 * * *`, America/New_York), which runs the job as the same service
   account (`roles/run.invoker` on this job only).

Re-running it is safe. No bucket or project names are committed here (ADR-0002): they are arguments.

## Operate

```sh
gcloud run jobs execute flightdeck-compactor --region <r>                                   # tonight's run, now
gcloud run jobs execute flightdeck-compactor --region <r> --args=--date,2026-11-03,--lookback,0,--rebuild
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="flightdeck-compactor"' --limit 50
```

Cost: a few minutes of a 1 vCPU / 2 GiB job per night, and about $0.03 a month of storage at the team's volume.
