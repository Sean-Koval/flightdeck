"""deploy/compactor/setup.sh --dry-run prints the gcloud commands and the rendered Cloud Run job; it calls nothing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

SETUP = Path(__file__).resolve().parent.parent / "deploy" / "compactor" / "setup.sh"


def dry_run(*extra: str) -> str:
    env = {**os.environ, "PATH": "/usr/bin:/bin"}  # no gcloud on PATH: a real call would fail
    args = ["sh", str(SETUP), "--project", "p1", "--runs-bucket", "gs://runs-b", "--data-bucket", "data-b", *extra]
    return subprocess.run([*args, "--dry-run"], check=True, capture_output=True, text=True, env=env).stdout


def job(out: str) -> dict:
    return yaml.safe_load("\n".join(line[4:] for line in out.splitlines() if line.startswith("    ")))


def test_dry_run_prints_least_privilege_commands_and_the_schedule() -> None:
    out = dry_run()
    cmds = [line for line in out.splitlines() if line.startswith("+ gcloud")]
    assert any("gs://runs-b" in c and "roles/storage.objectViewer" in c for c in cmds)
    assert any("gs://data-b" in c and "roles/storage.objectAdmin" in c for c in cmds)
    assert not any("projects add-iam-policy-binding" in c for c in cmds) and "secretAccessor" not in out
    # the data plane's bucket is made private; the outbox bucket is hangar's, never created here
    made = [c for c in cmds if "storage buckets create" in c]
    assert len(made) == 1 and "gs://data-b " in made[0] and "--public-access-prevention" in made[0]
    assert "--uniform-bucket-level-access" in made[0]
    assert 'run_bucket_readers = ["serviceAccount:flightdeck-compactor@p1.iam.gserviceaccount.com"]' in out
    assert "FLIGHTDECK_DATA_URI=gs://data-b/parquet/v1 flightdeck query" in out
    sched = next(c for c in cmds if "scheduler jobs create" in c)
    assert "30 2 * * *" in sched and "America/New_York" in sched and "jobs/flightdeck-compactor:run" in sched
    spec = job(out)["spec"]["template"]["spec"]["template"]["spec"]
    env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
    assert env == {"FLIGHTDECK_RUNS_URI": "gs://runs-b", "FLIGHTDECK_DATA_URI": "gs://data-b/parquet/v1",
                   "FLIGHTDECK_REPORTS_URI": "gs://data-b/reports"}
    assert spec["serviceAccountName"] == "flightdeck-compactor@p1.iam.gserviceaccount.com"
    assert spec["containers"][0]["resources"]["limits"] == {"cpu": "1", "memory": "2Gi"}


def test_github_repos_add_the_token_secret() -> None:
    out = dry_run("--github-repos", "acme/app,acme/web")
    env = {e["name"]: e for e in job(out)["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["FLIGHTDECK_GITHUB_REPOS"]["value"] == "acme/app,acme/web"
    assert env["GITHUB_TOKEN"]["valueFrom"]["secretKeyRef"]["name"] == "flightdeck-github-token"
    assert "secretmanager.secretAccessor" in out
