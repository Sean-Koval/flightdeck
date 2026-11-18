"""KAN-360: `scripts/flightdeck_doctor.py`. Each check has a passing and a failing case, and setup then doctor on an
empty HOME passes every required check. Nothing here touches the network or the real HOME."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from flightdeck.dataplane import schema

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "flightdeck_doctor.py"
spec = importlib.util.spec_from_file_location("flightdeck_doctor", SCRIPT)
assert spec and spec.loader
doc = importlib.util.module_from_spec(spec)
sys.modules["flightdeck_doctor"] = doc  # dataclasses look the module up
spec.loader.exec_module(doc)

posix = pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty HOME outside any git checkout, with nothing on PATH that the checks look for."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    for var in ("FLIGHTDECK_DATA_URI", "CLAUDE_CONFIG_DIR", "GITHUB_TOKEN", "GITHUB_API_URL"):
        monkeypatch.delenv(var, raising=False)
    assert doc.git_checkout(h) is None, "the temp folder must not sit in a git checkout"
    return h


def by_name(checks: list) -> dict:
    return {c.name: c for c in checks}


# --- duckdb ------------------------------------------------------------------------------------------------------


def test_duckdb_works_offline():
    assert doc.check_duckdb().status == "ok"


def test_duckdb_that_needs_a_download_fails(monkeypatch: pytest.MonkeyPatch):
    real = duckdb.connect

    class NoIcu:
        def __init__(self, con):
            self.con = con

        def execute(self, sql, *a):
            if "TimeZone" in sql:
                raise duckdb.IOException("Extension icu not found: autoinstall is off")
            return self.con.execute(sql, *a)

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: NoIcu(real(*a, **k)))
    c = doc.check_duckdb()
    assert c.status == "fail" and "icu" in c.detail and "uv sync --locked" in c.fix


# --- data location and data plane --------------------------------------------------------------------------------


def test_a_local_data_plane_stays_on_the_laptop():
    assert doc.check_data_uri("~/.flightdeck/data").status == "ok"


@pytest.mark.parametrize("uri", ["gs://team-bucket/plane", "s3://b/p"])
def test_a_bucket_warns_that_data_leaves_the_laptop(uri: str):
    c = doc.check_data_uri(uri)
    assert c.status == "warn" and "leaves this laptop" in c.detail


@posix
def test_a_private_data_plane_passes(home: Path):
    (home / "plane").mkdir(mode=0o700)
    checks = by_name(doc.check_data_plane(str(home / "plane")))
    assert {n: c.status for n, c in checks.items()} == {"data-plane": "ok", "data-not-in-git": "ok",
                                                        "data-not-synced": "ok"}


@posix
def test_a_world_readable_data_plane_fails(home: Path):
    (home / "plane").mkdir()
    os.chmod(home / "plane", 0o755)
    c = by_name(doc.check_data_plane(str(home / "plane")))["data-plane"]
    assert c.status == "fail" and "0755" in c.detail and c.fix.startswith("chmod -R go-rwx")


def test_a_missing_data_plane_fails_with_setup_as_the_fix(home: Path):
    c = by_name(doc.check_data_plane(str(home / "nope")))["data-plane"]
    assert c.status == "fail" and "setup" in c.fix


def test_a_data_plane_inside_a_git_checkout_fails(home: Path):
    (home / "repo" / ".git").mkdir(parents=True)
    (home / "repo" / "plane").mkdir(mode=0o700)
    c = by_name(doc.check_data_plane(str(home / "repo" / "plane")))["data-not-in-git"]
    assert c.status == "fail" and str(home / "repo") in c.detail


SYNCED = ["Library/CloudStorage/OneDrive-Acme", "Library/Mobile Documents/com~apple~CloudDocs", "Dropbox",
          "OneDrive - Acme", "Google Drive/My Drive"]


@pytest.mark.parametrize("folder", SYNCED)
def test_a_data_plane_inside_a_synced_folder_fails(home: Path, folder: str):
    c = by_name(doc.check_data_plane(str(home / folder / "plane")))["data-not-synced"]
    assert c.status == "fail" and "cloud-synced" in c.detail


def test_a_remote_data_plane_skips_the_local_checks():
    assert [c.status for c in doc.check_data_plane("gs://b/p")] == ["skip"]


# --- capture -----------------------------------------------------------------------------------------------------


def _fake_exe(tmp_path: Path, name: str, code: int) -> Path:
    exe = tmp_path / "bin" / name
    exe.parent.mkdir(exist_ok=True)
    exe.write_text(f"#!/bin/sh\nexit {code}\n")
    exe.chmod(0o755)
    return exe


@posix
def test_hangar_with_trace_import_passes(tmp_path: Path):
    exe = _fake_exe(tmp_path, "hangar", 0)
    assert doc.check_hangar(lambda _: str(exe)).status == "ok"


@posix
def test_hangar_without_trace_import_or_missing_warns(tmp_path: Path):
    exe = _fake_exe(tmp_path, "hangar", 2)
    assert doc.check_hangar(lambda _: str(exe)).status == "warn"
    c = doc.check_hangar(lambda _: None)
    assert c.status == "warn" and "PATH" in c.detail


def _session(projects: Path, sid: str) -> Path:
    p = projects / "-home-me-repo" / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"type":"user"}\n')
    return p


def test_sessions_counted_and_the_uningested_ones_named(home: Path):
    projects = home / ".claude" / "projects"
    _session(projects, "aaa")
    newest = _session(projects, "bbb")
    os.utime(newest, (2_000_000_000, 2_000_000_000))
    plane = home / "plane"
    schema.write_partitioned("runs", [{"run_id": "r1", "source": "session", "dt": "2026-11-18",
                                       "session_id": "aaa"}], str(plane))
    checks = by_name(doc.check_sessions({}, str(plane)))
    assert checks["capture-sessions"].status == "ok" and "2 sessions" in checks["capture-sessions"].detail
    assert "2033-05-18" in checks["capture-sessions"].detail
    pending = checks["capture-pending"]
    assert pending.status == "warn" and "1 of 2" in pending.detail and "bbb.jsonl" in pending.fix


def test_every_session_ingested_passes(home: Path):
    _session(home / ".claude" / "projects", "aaa")
    schema.write_partitioned("runs", [{"run_id": "r1", "source": "session", "dt": "2026-11-18",
                                       "session_id": "aaa"}], str(home / "plane"))
    assert by_name(doc.check_sessions({}, str(home / "plane")))["capture-pending"].status == "ok"


def test_no_claude_code_projects_warns_and_claude_config_dir_is_followed(home: Path):
    assert doc.check_sessions({}, str(home / "plane"))[0].status == "warn"
    _session(home / "other" / "projects", "aaa")
    c = doc.check_sessions({"CLAUDE_CONFIG_DIR": str(home / "other")}, str(home / "plane"))[0]
    assert c.status == "ok" and "1 session in" in c.detail


# --- github and docker -------------------------------------------------------------------------------------------


def test_github_dot_com_with_a_token_passes_and_never_prints_it():
    checks = by_name(doc.check_github({"GITHUB_TOKEN": "ghp_secretvalue"}, "github.com"))
    assert checks["github-host"].status == "ok" and checks["github-token"].status == "ok"
    assert all("ghp_secretvalue" not in c.line() for c in checks.values())


def test_enterprise_host_without_api_url_and_no_token_warn():
    checks = by_name(doc.check_github({}, "github.acme.com"))
    assert checks["github-host"].status == "warn" and "https://github.acme.com/api/v3" in checks["github-host"].fix
    assert checks["github-token"].status == "warn"
    ok = by_name(doc.check_github({"GITHUB_API_URL": "https://github.acme.com/api/v3"}, "github.acme.com"))
    assert ok["github-host"].status == "ok"


@pytest.mark.parametrize(("url", "host"), [("https://github.com/o/r.git", "github.com"),
                                           ("git@github.acme.com:o/r.git", "github.acme.com"),
                                           ("ssh://git@ghe.example:22/o/r", "ghe.example")])
def test_remote_host_reads_https_ssh_and_scp_urls(tmp_path: Path, url: str, host: str):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
    assert doc.remote_host(repo) == host
    assert doc.remote_host(tmp_path) is None  # no checkout, no remote


@posix
def test_docker_running_passes_stopped_warns_absent_skips(tmp_path: Path):
    assert doc.check_docker(lambda _: str(_fake_exe(tmp_path, "docker", 0))).status == "ok"
    assert doc.check_docker(lambda _: str(_fake_exe(tmp_path, "docker", 1))).status == "warn"
    assert doc.check_docker(lambda _: None).status == "skip"


# --- setup, then doctor ------------------------------------------------------------------------------------------


@posix
def test_setup_then_doctor_on_an_empty_home_passes_every_required_check(home: Path, capsys: pytest.CaptureFixture):
    assert doc.main(["setup"]) == 0
    plane = home / ".flightdeck" / "data"
    assert stat.S_IMODE(plane.stat().st_mode) == 0o700
    envf = home / ".flightdeck" / "env"
    assert stat.S_IMODE(envf.stat().st_mode) == 0o600
    assert f"export FLIGHTDECK_DATA_URI={plane}" in envf.read_text()
    assert "next: ." in capsys.readouterr().out
    assert doc.main(["doctor"]) == 0
    assert "all required checks pass" in capsys.readouterr().out


@posix
def test_setup_tightens_a_world_readable_plane(home: Path):
    plane = home / "plane"
    (plane / "runs" / "dt=2026-11-18").mkdir(parents=True)
    (plane / "runs" / "dt=2026-11-18" / "part-0.parquet").write_bytes(b"x")
    for p in (plane, plane / "runs", plane / "runs" / "dt=2026-11-18"):
        os.chmod(p, 0o755)
    os.chmod(plane / "runs" / "dt=2026-11-18" / "part-0.parquet", 0o644)
    assert doc.setup(str(plane), env={}) == 0
    assert all(not stat.S_IMODE(p.stat().st_mode) & 0o077 for p in (plane, *plane.rglob("*")))


def test_setup_refuses_git_checkouts_synced_folders_and_buckets(home: Path, capsys: pytest.CaptureFixture):
    (home / "repo" / ".git").mkdir(parents=True)
    assert doc.setup(str(home / "repo" / "plane"), env={}) == 1
    assert doc.setup(str(home / "Dropbox" / "plane"), env={}) == 1
    assert doc.setup("gs://b/p", env={}) == 1
    assert not (home / "repo" / "plane").exists() and not (home / "Dropbox").exists()
    assert "refusing" in capsys.readouterr().err


@posix
def test_doctor_fails_on_a_required_check(home: Path, capsys: pytest.CaptureFixture):
    (home / "plane").mkdir()
    os.chmod(home / "plane", 0o755)
    assert doc.main(["doctor", "--data", str(home / "plane")]) == 1
    assert "1 failed: data-plane" in capsys.readouterr().out
