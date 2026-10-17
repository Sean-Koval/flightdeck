import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from fsspec.implementations.memory import MemoryFileSystem
from hangar_export import EXP, Recorded, export_dir, export_routes, no_proxy, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import ingest, schema
from flightdeck.dataplane.duck import connect

FIX = Path(__file__).resolve().parent / "fixtures" / "hangar"
ROOT = Path(__file__).resolve().parent.parent


def tables(root: str) -> dict[str, list[str]]:
    """Every table's rows, sorted, for comparing two data planes."""
    con = connect(root)
    return {t: sorted(map(repr, con.sql(f"select * exclude (dt) from {t}").fetchall())) for t in schema.TABLES}


def test_export_ingest_fills_all_six_tables_one_run_per_trial(plane: str) -> None:
    con = connect(plane)
    counts = {t: con.sql(f"select count(*) from {t}").fetchone() for t in schema.TABLES}
    assert all(n and n[0] > 0 for n in counts.values()), counts
    keys = con.sql("select trial_key, run_id, source from runs order by trial_key").fetchall()
    assert len(keys) == 72 == len({k for k, _, _ in keys})
    assert all(rid == f"{EXP}/{k}" and src == "experiment" for k, rid, src in keys)
    # a trial's spans hang off the trial's run row
    orphans = con.sql("select count(*) from spans where run_id not in (select run_id from runs)").fetchone()
    assert orphans == (0,)
    assert con.sql("select count(distinct digest), count(*) from manifests").fetchone() == (2, 2)


def test_pending_trial_has_no_outcome_and_truncated_trace_is_flagged(plane: str) -> None:
    con = connect(plane)
    assert con.sql("select outcome from runs where trial_key = 't06/treat/3'").fetchone() == (None,)
    assert con.sql("select trial_key from runs where truncated").fetchall() == [("t07/control/1",)]


def test_reingest_adds_no_duplicates_and_replaces_a_finished_trial(export_dir: Path, tmp_path: Path) -> None:
    out = str(tmp_path)
    ingest.write_unit(ingest.read_export(export_dir), out, f"experiment-{EXP}")
    before = tables(out)
    ingest.write_unit(ingest.read_export(export_dir), out, f"experiment-{EXP}")
    assert tables(out) == before
    # the running trial finishes (on a later day) and the experiment is ingested again
    changed = tmp_path / "export2"
    shutil.copytree(export_dir, changed)
    index = json.loads((changed / "index.json").read_text())
    t = next(x for x in index["trials"] if x["key"] == "t06/treat/3")
    t.update(state="done", outcome="succeeded", finished_at=1760900000.0)
    (changed / "index.json").write_text(json.dumps(index))
    ingest.write_unit(ingest.read_export(changed), out, f"experiment-{EXP}")
    con = connect(out)
    assert con.sql("select count(*), count(distinct run_id) from runs").fetchone() == (72, 72)
    assert con.sql("select outcome from runs where trial_key = 't06/treat/3'").fetchone() == ("succeeded",)


def test_rest_and_export_ingest_yield_identical_tables(
    export_dir: Path, plane: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_proxy: None
) -> None:
    monkeypatch.setenv("HANGAR_TOKEN", "member-token")
    with Recorded(export_routes(export_dir)) as hangar:
        result = CliRunner().invoke(app, ["ingest", "experiment", EXP, "--hangar", hangar.url, "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert tables(str(tmp_path)) == tables(plane)
    assert {auth for _, auth in hangar.requests} == {"Bearer member-token"}
    assert (tmp_path / "raw" / EXP / "index.json").is_file()  # streamed to disk, in the export layout


def test_rest_404_is_reported_as_missing_or_not_yours(tmp_path: Path, no_proxy: None) -> None:
    with Recorded({}) as hangar:
        result = CliRunner().invoke(app, ["ingest", "experiment", "nope", "--hangar", hangar.url, "--out",
                                          str(tmp_path)])
    assert result.exit_code == 1
    assert "not visible to this token" in result.output


def test_job_and_session_ingest_over_rest(tmp_path: Path, no_proxy: None) -> None:
    routes = {"/api/jobs/job-fixture01/trace": FIX / "trace_job.json",
              "/api/jobs/job-fixture01/manifest?turn=1": FIX / "manifest_turn.json",
              "/api/sessions/dev-a-s1/trace?turn=1": FIX / "trace_session_good.json"}
    with Recorded(routes) as hangar:
        for args in (["job", "job-fixture01"], ["job", "job-fixture01"], ["session", "dev-a-s1", "--turn", "1"]):
            result = CliRunner().invoke(app, ["ingest", *args, "--hangar", hangar.url, "--out", str(tmp_path)])
            assert result.exit_code == 0, result.output
    con = connect(str(tmp_path))
    assert con.sql("select source, count(*) from runs group by 1 order by 1").fetchall() == [("job", 1),
                                                                                         ("session", 1)]
    assert con.sql("select digest from manifests").fetchall() == [("sha256:" + "1" * 64,)]


def test_ingest_without_hangar_url_is_a_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HANGAR_URL", raising=False)
    result = CliRunner().invoke(app, ["ingest", "job", "j", "--out", str(tmp_path)])
    assert result.exit_code == 2 and "HANGAR_URL" in result.output


def test_schema_mismatch_warns_and_keeps_going(export_dir: Path, tmp_path: Path) -> None:
    bad = tmp_path / "export"
    shutil.copytree(export_dir, bad)
    index = json.loads((bad / "index.json").read_text())
    index["trials"][0]["turns"] = "one"  # an integer in hangar.experiment/v1
    (bad / "index.json").write_text(json.dumps(index))
    result = CliRunner().invoke(app, ["ingest", "export", str(bad), "--out", str(tmp_path / "plane")])
    assert result.exit_code == 0, result.output
    assert "does not match hangar experiment.schema.json" in result.output and "72 runs" in result.output


def test_vendored_schemas_carry_their_hangar_commit_and_the_sync_script_updates_them(tmp_path: Path) -> None:
    pinned = json.loads((ROOT / "src/flightdeck/dataplane/hangar_schemas/SOURCE.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", pinned["commit"])
    repo = tmp_path / "hangar"
    (repo / "docs" / "api").mkdir(parents=True)
    for name in ("experiment.schema.json", "manifest.schema.json", "run.schema.json"):
        (repo / "docs" / "api" / name).write_text(json.dumps({"title": name}))
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "schemas"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    dest = tmp_path / "vendored"
    spec = importlib.util.spec_from_file_location("sync_hangar_schemas", ROOT / "scripts/sync_hangar_schemas.py")
    assert spec and spec.loader
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    assert sync.sync(repo, "HEAD", dest) == head
    assert json.loads((dest / "SOURCE.json").read_text())["commit"] == head
    assert json.loads((dest / "manifest.schema.json").read_text()) == {"title": "manifest.schema.json"}


def test_query_reads_gs_through_the_gcs_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gs://` goes through gcsfs when the `gcs` extra is installed; a memory filesystem stands in for GCS."""

    class FakeGCS(MemoryFileSystem):
        protocol = ("gs", "gcs")
        root_marker = ""

    fake = types.ModuleType("gcsfs")
    fake.__spec__ = importlib.machinery.ModuleSpec("gcsfs", None)
    fake.GCSFileSystem = FakeGCS  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gcsfs", fake)
    fs = FakeGCS()
    try:
        with fs.open("gs://bucket/plane/runs/dt=2025-10-16/part-0.parquet", "wb") as f:
            pq.write_table(schema.to_table("runs", [{"run_id": "r1", "source": "job"}]).drop_columns(["dt"]), f)
        result = CliRunner().invoke(app, ["query", "select count(*) from runs", "--data", "gs://bucket/plane"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[1] == "1"
    finally:
        MemoryFileSystem.store.clear()


def test_write_partitioned_replaces_a_part_across_days(tmp_path: Path) -> None:
    rows = [{"run_id": "r", "source": "job", "dt": "2025-10-15"}]
    schema.write_partitioned("runs", rows, str(tmp_path), "part-x")
    schema.write_partitioned("runs", [{**rows[0], "dt": "2025-10-16"}], str(tmp_path), "part-x")
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    assert files == ["runs/dt=2025-10-16/part-x.parquet"]
    assert pq.read_table(tmp_path / files[0]).num_rows == 1
