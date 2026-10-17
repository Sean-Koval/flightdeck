"""The local Docker backend (docs/runners.md#local): ai-dlc's isolated attempt, flightdeck's tasks in, data-plane rows
out. The Docker boundary is faked except in the tests at the end, which skip without Docker."""

import io
import json
import shutil
import socket
import socketserver
import subprocess
import tarfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import ingest
from flightdeck.dataplane.duck import connect
from flightdeck.ported.aidlc import attempt, budgets, drivers, test_proxy
from flightdeck.runners import local
from flightdeck.runners.hangar import RunnerError, TrialPlan
from flightdeck.specs import lang
from flightdeck.tasks.format import load_task

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "tasks" / "smoke"
FIXTURES = ROOT / "tasks" / "fixtures"
IMAGE = "python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de"
ANCHOR = "1" * 40
PLANNED = {"scenario": "csv", "arm": "oracle", "attempt": 1, "image": IMAGE, "workdir": "/workspace/csv",
           "limits": {"timeout_minutes": 30}}
TESTS_BEFORE_COMMIT = lang.load((ROOT / "specs/examples/team-default.yaml").read_text())[0]


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeDocker:
    """Replaces only the docker process boundary (ported from ai-dlc's tests); records every invocation in order."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail: dict[str, str] = {}
        self.tree = archive({"./app.py": b"print('v2')\n"})

    def __call__(self, args, *, timeout, input=None, cancel=None):
        del timeout, input, cancel
        self.calls.append(list(args))
        verb = self.verb(args)
        if verb in self.fail:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=self.fail[verb].encode())
        out = b""
        if verb == "collect":
            out = self.tree
        elif args[0] == "exec" and "rev-parse" in args:
            out = f"{ANCHOR}\n".encode()
        elif args[0] == "exec" and "rev-list" in args:
            out = b"2" * 40 + b"\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr=b"")

    @staticmethod
    def verb(args: list[str]) -> str:
        if args[0] == "run" and "tar" in args and "-c" in args:
            return "collect"
        if args[0] == "run":
            return "run" if "-d" in args else "stage"
        if args[0] == "exec":
            return "exec:" + args[-1]
        return " ".join(args[:2]) if args[0] in ("volume", "network") else args[0]

    def verbs(self) -> list[str]:
        return [self.verb(c) for c in self.calls]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    docker = FakeDocker()
    monkeypatch.setattr(attempt, "_docker", docker)
    monkeypatch.setattr(attempt.shutil, "which", lambda name: "/usr/bin/" + name)
    return docker


def run(tmp_path: Path, **options):
    options.setdefault("steps", [["sh", "-c", "step-one"]])
    return attempt.run_attempt(options.pop("planned", PLANNED), run_dir=tmp_path / "run", fixture=None, **options)


# ---------------------------------------------------------------------------------------------------- isolation
def test_containers_start_isolated_with_no_network_and_no_host_path(tmp_path: Path, fake: FakeDocker) -> None:
    result = run(tmp_path)
    create = next(c for c in fake.calls if c[0] == "create")
    for control in ["--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--network=none",
                    "--user=1000:1000", "--workdir=/workspace/csv"]:
        assert control in create
    assert any(p.startswith("--memory=") for p in create) and any(p.startswith("--pids-limit=") for p in create)
    assert "type=volume,src=" + result["resources"]["volume"] + ",dst=/workspace/csv" in create
    flat = [p for c in fake.calls for p in c]
    assert not [p for p in flat if p.startswith(("type=bind", "/home", str(tmp_path)))]
    # the stager copies the image's own working directory into the volume, without its .git
    stage = next(c for c in fake.calls if fake.verb(c) == "stage")
    assert "--network=none" in stage and "--cap-drop=ALL" in stage and stage[-1] == "/workspace/csv"
    assert "rm -rf /w/.git" in stage[-3]
    grader = []
    monkey = lambda args, **kw: grader.append(args) or SimpleNamespace(returncode=0, stdout=b"", stderr=b"")  # noqa: E731
    attempt._docker = monkey  # type: ignore[assignment]  # restored by the fixture's monkeypatch
    attempt.run_isolated(IMAGE, b"", "true", timeout=5)
    for control in ["--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges"]:
        assert control in grader[0]


def test_evidence_is_collected_before_cleanup_and_steps_carry_timing_and_commits(tmp_path: Path,
                                                                                fake: FakeDocker) -> None:
    result = run(tmp_path)
    verbs = fake.verbs()
    assert verbs.index("collect") < verbs.index("rm") < verbs.index("volume rm")
    assert result["outcome"] == "completed" and result["git_anchor"] == ANCHOR
    assert (tmp_path / "run/tree/project/app.py").read_text() == "print('v2')\n"
    commit = next(c for c in fake.calls if c[0] == "exec" and "commit" in c)
    assert "--allow-empty" in commit and "--env=GIT_AUTHOR_DATE=2000-01-01T00:00:00Z" in commit
    assert next(c for c in fake.calls if "update-ref" in c)[-2:] == ["refs/flightdeck/anchor", ANCHOR]
    step = json.loads((tmp_path / "run/steps/01.json").read_text())
    assert step["commits"] == ["2" * 40] and step["start_ns"] <= step["end_ns"]


def test_failed_step_setup_is_infrastructure_and_unsafe_archives_are_incomplete(tmp_path: Path,
                                                                                fake: FakeDocker) -> None:
    fake.fail["stage"] = "no such image"
    result = run(tmp_path)
    assert (result["outcome"], result["stage"]) == ("infrastructure", "stage-fixture")
    assert "exec:step-one" not in fake.verbs() and "rm" in fake.verbs()
    fake.fail.clear()
    fake.tree = archive({"../escaped.txt": b"x"})
    result = run(tmp_path / "again")
    assert (result["outcome"], result["stage"]) == ("incomplete", "collect")
    assert not (tmp_path / "again/escaped.txt").exists()


def test_missing_docker_is_infrastructure_with_no_host_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(attempt.shutil, "which", lambda name: None)
    monkeypatch.setattr(attempt, "_docker", lambda *a, **k: pytest.fail("no host execution"))
    result = run(tmp_path)
    assert (result["outcome"], result["stage"]) == ("infrastructure", "provision") and "Docker" in result["detail"]


def test_egress_goes_only_through_the_pinned_proxy_given_as_text(tmp_path: Path, fake: FakeDocker) -> None:
    with pytest.raises(ValueError, match="pinned"):
        run(tmp_path, egress={"hosts": ["api.anthropic.com"], "proxy_image": "python:3"})
    run(tmp_path, egress={"hosts": ["api.anthropic.com"], "proxy_image": IMAGE})
    proxy = next(c for c in fake.calls if fake.verb(c) == "run")
    assert proxy[-1] == (Path(attempt.__file__).parent / "test_proxy.py").read_text()
    assert "--env=ALLOW_HOSTS=api.anthropic.com" in proxy and "--cap-drop=ALL" in proxy
    create = next(c for c in fake.calls if c[0] == "create")
    assert "--network=none" not in create and any(p.endswith("-int") for p in create if p.startswith("--network="))


def test_the_proxy_logs_each_decision_as_one_json_line(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ALLOW_HOSTS", "api.anthropic.com")
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), test_proxy.Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address[:2]
        with socket.create_connection((str(host), int(port)), timeout=5) as client:
            client.sendall(b"CONNECT pypi.org:443 HTTP/1.1\r\n\r\n")
            assert b"403" in client.recv(200)
        server.shutdown()
    assert [json.loads(x) for x in capsys.readouterr().out.splitlines()] == [
        {"allowed": False, "host": "pypi.org", "port": 443}]


# ---------------------------------------------------------------------------------------------------- tasks
def _copy(tmp_path: Path, name: str, **flightdeck: object) -> Path:
    d = tmp_path / name
    shutil.copytree(SMOKE / name if (SMOKE / name).is_dir() else FIXTURES / name, d)
    text = (d / "task.toml").read_text()
    for k, v in flightdeck.items():
        text = text.replace("[flightdeck]\n", f"[flightdeck]\n{k} = {json.dumps(v)}\n", 1)
    (d / "task.toml").write_text(text)
    return d


def test_sealed_and_mined_tasks_are_refused_before_anything_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local.subprocess, "run", lambda *a, **k: pytest.fail("nothing may run"))
    sealed = _copy(tmp_path, "semver")
    (sealed / "task.toml").write_text((sealed / "task.toml").read_text().replace("sealed = false", "sealed = true"))
    mined = _copy(tmp_path, "csv-validator", mined_from="https://example.invalid/pr/1")
    backend = local.LocalDockerBackend(str(tmp_path / "plane"))
    for d, word in ((sealed, "sealed"), (mined, "mined")):
        with pytest.raises(RunnerError, match=f"is {word}: team tasks run on hangar"):
            backend.submit(TrialPlan("s", [load_task(d)], {"oracle": {"harness": "deterministic"}}, environment="b"))
    assert not (tmp_path / "plane").exists()
    with pytest.raises(RunnerError, match="--data"):
        local.LocalDockerBackend(None)


def test_drivers_come_from_the_variant_and_the_task_solution(monkeypatch) -> None:
    oracle, client = local.pick_driver(load_task(SMOKE / "semver"), "o", {"harness": "deterministic"})
    assert client is None and oracle.steps({})[-1] == ["bash", f"{local.SOLUTION}/solve.sh"]
    assert oracle.steps({})[0][:3] == ["python", "-c", drivers.WRITER]
    scripted, _ = local.pick_driver(load_task(FIXTURES / "csv-validator"), "o", {"harness": "deterministic"})
    assert [s[0] for s in scripted.steps({})[1:]] == ["python", "git", "git"]
    real, client = local.pick_driver(load_task(SMOKE / "semver"), "c", {"harness": "claude-code@2.1.296",
                                                                         "model": "claude-opus-5-5"})
    assert isinstance(real, drivers.ClaudeCode) and real.install({}) == [] and client == {
        "kind": "claude-code", "version": "2.1.296", "model": "claude-opus-5-5"}
    for v in ({"harness": "claude-code"}, {"harness": "codex@1"}):
        with pytest.raises(RunnerError, match="the local backend runs"):
            local.pick_driver(load_task(SMOKE / "semver"), "x", v)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = TrialPlan("s", [load_task(SMOKE / "semver")], {"c": {"harness": "claude-code@2.1.296",
                                                                 "model": "claude-opus-5-5"}}, environment="b")
    with pytest.raises(RunnerError, match="ANTHROPIC_API_KEY"):
        local.LocalDockerBackend("/nonexistent").submit(plan)
    plan.variants["c"]["model"] = "opus"
    with pytest.raises(RunnerError, match="concrete model"):
        local.LocalDockerBackend("/nonexistent").submit(plan)


# ---------------------------------------------------------------------------------------------------- rows
def _trial(d: Path, steps: list[dict], outcome: str = "completed", git: str = "available", client=None) -> Path:
    (d / "steps").mkdir(parents=True)
    (d / "grading").mkdir()
    planned = {**PLANNED, **({"client": client} if client else {})}
    (d / "inputs.json").write_text(json.dumps({"planned": planned}))
    (d / "attempt.json").write_text(json.dumps({"outcome": outcome, "stage": "provision" if outcome != "completed"
                                                else None, "detail": "x", "git_anchor": ANCHOR, "client": None}))
    for i, s in enumerate(steps, 1):
        (d / "steps" / f"{i:02d}.json").write_text(json.dumps(
            {"stdout": "", "stderr": "", "exit_code": 0, "commits": [], "start_ns": 10 * i, "end_ns": 10 * i + 5, **s}))
    commits = [{"hash": ANCHOR, "anchor": True, "paths": ["README.md"]},
               {"hash": "2" * 40, "anchor": False, "paths": ["csvcheck/validate.py"]}]
    (d / "grading/git.json").write_text(json.dumps({"status": git, "commits": commits, "dirty_paths": []}))
    (d / "grading/hidden-tests.json").write_text(json.dumps(
        {"command": "bash tests/test.sh", "exit_code": 0, "seconds": 1.5, "digest": "sha256:d",
         "reward": {"reward": 1, "passed": 10, "total": 10}}))
    return d


TEST = {"command": ["python", "-m", "unittest", "discover", "-s", "tests"], "stderr": "Ran 3 tests in 0.01s\n\nOK\n"}
COMMIT = {"command": ["git", "commit", "-qm", "x"], "commits": ["2" * 40]}


def _spec(tables: dict) -> str:
    py = lang.evaluate(TESTS_BEFORE_COMMIT, tables)
    assert py == lang.evaluate_sql(TESTS_BEFORE_COMMIT, lang.connect_tables(tables))
    return next(iter(py.values()))


def test_rows_carry_hangar_columns_and_tests_before_commit_evaluates(tmp_path: Path) -> None:
    passing = local.rows("local-rs", _trial(tmp_path / "a", [TEST, COMMIT]), "csv", "oracle", 1)
    run = passing["runs"][0]
    assert (run["source"], run["experiment_id"], run["outcome"], run["harness"]) == (
        "local", "local-rs", "succeeded", "deterministic")
    assert run["diff_files"] == ["csvcheck/validate.py"] and run["truncated"] is False
    tool = passing["spans"][1]
    assert (tool["kind"], tool["tool_kind"], tool["shell_ops"], tool["job_id"]) == (
        "tool.call", "shell", ["test"], run["run_id"])
    tc = passing["test_cases"][0]
    assert {k: tc[k] for k in ("trusted", "total", "passed", "complete")} == {
        "trusted": True, "total": 3, "passed": 3, "complete": True}
    assert [e["name"] for e in passing["events"]] == ["git.commit"]
    assert passing["grades"][0]["exit_code"] == 0 and json.loads(passing["grades"][0]["data"])["passed"] == 10
    assert _spec(passing) == "pass"
    assert _spec(local.rows("local-rs", _trial(tmp_path / "b", [COMMIT, TEST]), "csv", "oracle", 1)) == "fail"
    one = {"command": ["sh", "-c", "git commit -qm x && python -m pytest"], "stdout": "1 passed in 0.1s",
           "commits": ["2" * 40]}
    assert _spec(local.rows("local-rs", _trial(tmp_path / "c", [one]), "csv", "oracle", 1)) == "fail"
    # the observer saw no history: never a pass
    assert _spec(local.rows("local-rs", _trial(tmp_path / "d", [TEST, COMMIT], git="unavailable"), "c", "o", 1)) == (
        "unknown")
    infra = local.rows("local-rs", _trial(tmp_path / "e", [], outcome="infrastructure"), "csv", "oracle", 1)["runs"][0]
    assert (infra["outcome"], infra["outcome_class"]) == ("failed", "infra_error")
    assert infra["infra_reason"] == "provision: x"


def test_a_models_test_commands_are_spans_never_trusted_test_runs(tmp_path: Path) -> None:
    client = {"kind": "claude-code", "version": "2.1.296", "model": "claude-opus-5-5"}
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q && git commit -m x"}},
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/workspace/csv/a.py"}},
            {"type": "tool_use", "id": "t3", "name": "mcp__docs__search", "input": {"query": "csv"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q && git commit -m x"}}]}},
    ])
    session = {"command": ["claude", "-p", "--output-format", "stream-json"], "stdout": stream}
    out = local.rows("local-rs", _trial(tmp_path / "a", [session, COMMIT], client=client), "csv", "cc", 1)
    tools = [(s["tool_name"], s["tool_kind"], s["shell_ops"], s["tool_ok"], s["file_repo_path"])
             for s in out["spans"][1:]]
    assert tools[:3] == [("Bash", "shell", ["test", "git.commit"], False, None), ("Edit", "edit", None, None, "a.py"),
                         ("mcp__docs__search", "mcp", None, None, None)]
    assert out["test_cases"] == [] and out["runs"][0]["harness"] == "claude-code"
    assert _spec(out) == "fail"  # a commit and no trusted test run before it


def test_totals_read_unittest_and_pytest_summaries() -> None:
    assert local.totals("Ran 5 tests in 0.1s\n\nFAILED (failures=1, errors=1)") == {
        "total": 5, "passed": 3, "failed": 1, "errors": 1, "skipped": 0, "complete": True}
    assert local.totals("== 3 passed, 1 failed, 2 skipped in 0.2s ==")["total"] == 6
    assert local.totals("collected 0 items") == {"complete": False}


def test_collect_and_status_rebuild_the_run_set_from_its_evidence(tmp_path: Path) -> None:
    root = tmp_path / "plane" / "raw" / "local-rs"
    _trial(root / "csv" / "oracle" / "1", [TEST, COMMIT])
    (root / "plan.json").write_text(json.dumps({"tasks": ["csv"], "variants": {"oracle": {}}, "n": 2}))
    backend = local.LocalDockerBackend(str(tmp_path / "plane"))
    backend.collect("local-rs")
    backend.collect("local-rs")  # replaces, never duplicates
    con = connect(str(tmp_path / "plane"))
    assert con.sql("select count(*), any_value(source) from runs").fetchone() == (1, "local")
    assert con.sql("select count(*) from test_cases where trusted").fetchone() == (1,)
    st = backend.status("local-rs")
    assert (st.state, st.counts) == ("running", {"completed": 1})
    with pytest.raises(RunnerError, match="no local run set"):
        backend.status("local-other")
    assert ingest.write_unit  # the same merge path hangar's ingest uses


# ---------------------------------------------------------------------------------------------------- ported pieces
STREAM = Path(__file__).resolve().parent / "fixtures" / "local" / "claude-code-2.1.220.jsonl"
CLIENT = {"kind": "claude-code", "version": "2.1.220", "model": "claude-sonnet-4-6"}


def test_claude_stream_meters_the_native_result_and_refuses_damaged_identity() -> None:
    # Stale on purpose (2.1.220, before hangar's pinned 2.1.296): it checks the parser, not today's stream shape
    parsed = drivers.parse_claude_stream(STREAM.read_bytes(), CLIENT)
    assert parsed["complete"] and parsed["usage"]["total_tokens"] == sum(
        parsed["usage"][k] for k in drivers.TOKEN_FIELDS)
    events = [json.loads(x) for x in STREAM.read_bytes().splitlines()]
    events[0]["model"] = "claude-opus-5-5"
    with pytest.raises(ValueError, match="malformed"):
        drivers.parse_claude_stream(b"\n".join(json.dumps(e).encode() for e in events), CLIENT)
    with pytest.raises(ValueError, match="malformed"):
        drivers.parse_claude_stream(STREAM.read_bytes()[:-40], CLIENT)


def test_run_budget_refuses_past_the_worst_observed_usage() -> None:
    planned = {"scenario": "s", "arm": "a", "attempt": 1, "limits": {"max_spend_usd": 2}}
    assert budgets.RunBudget({"max_tokens": 10, "max_spend_usd": 0}).decision(planned)["limit"] == "max_spend_usd"
    ledger = budgets.RunBudget({"max_tokens": 100, "max_spend_usd": 3})
    assert ledger.decision(planned)["start"]
    ledger.observe({"usage": {"total_tokens": 60, "cost_usd": 1.5}})
    assert ledger.decision(planned)["limit"] == "max_tokens"  # 40 left < 60 seen
    ledger.observe(None)
    assert ledger.decision(planned)["limit"] == "unknown-usage"
    assert budgets.refused_attempt(ledger.decision(planned))["outcome"] == "not-started"


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin"}
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid", *args],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_git_observer_reads_only_post_anchor_history_and_dirty_paths(tmp_path: Path) -> None:
    from flightdeck.ported.aidlc import git_observer as go

    project = tmp_path / "tree/project"
    project.mkdir(parents=True)
    _git(project, "init", "-q", "-b", "main")
    _git(project, "commit", "-q", "--allow-empty", "-m", "anchor")
    anchor = _git(project, "rev-parse", "HEAD")
    _git(project, "update-ref", go.ANCHOR_REF, anchor)
    (project / "a.py").write_text("x\n")
    _git(project, "add", "a.py")
    _git(project, "commit", "-qm", "a")
    (project / "a.py").write_text("changed\n")
    (project / ".git/hooks/post-checkout").write_text("#!/bin/sh\ntouch /tmp/pwned\n")
    seen = go.retain_git_observation(tmp_path, expected_anchor=anchor)
    assert seen["status"] == "available" and [c["paths"] for c in seen["commits"]] == [[], ["a.py"]]
    assert seen["dirty_paths"] == ["a.py"]
    assert go.evaluate_git_assertion(tmp_path, "path-committed", path="a.py", before=None, after=None)[0] == "fail"
    assert go.evaluate_git_assertion(tmp_path, "commit-present", path=None, before=None, after=None)[0] == "pass"
    assert go.retain_git_observation(tmp_path, expected_anchor="3" * 40)["status"] == "unavailable"


# ---------------------------------------------------------------------------------------------------- real Docker
def _docker_ready() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True,
                                                           timeout=60).returncode == 0


docker = pytest.mark.skipif(not _docker_ready(), reason="Docker is unavailable: the local backend has no host fallback")


@docker
def test_real_smoke_suite_gets_rewards_and_spec_results(tmp_path: Path) -> None:
    """CI's acceptance: semver and the csv-validator fixture run on local with the deterministic driver."""
    plane = tmp_path / "plane"
    done = CliRunner().invoke(app, ["experiment", "run", str(FIXTURES / "local.yaml"), "--backend", "local",
                                    "--data", str(plane)])
    assert done.exit_code == 0, done.output
    run_set = done.output.split()[1]
    for task, total in (("semver", 116), ("csv-validator", 10)):
        d = plane / "raw" / run_set / task / "oracle" / "1"
        assert json.loads((d / "reward.json").read_text()) == {"reward": 1, "passed": total, "total": total}
        assert json.loads((d / "attempt.json").read_text())["cleanup"]["clean"] is True
    con = connect(str(plane))
    assert con.sql("select count(*) from grades where exit_code = 0").fetchone() == (2,)
    lang.prepare(con)
    results = {k.split("/")[-3]: v for k, v in lang.evaluate_sql(TESTS_BEFORE_COMMIT, con).items()}
    assert results == {"csv-validator": "pass", "semver": "fail"}  # semver's solve.sh commits without testing
    status = CliRunner().invoke(app, ["experiment", "status", run_set, "--data", str(plane)])
    assert "succeeded" in status.output and "completed=2" in status.output


@docker
def test_real_attempt_has_no_network_and_an_empty_change_fails_the_grader(tmp_path: Path) -> None:
    task = _copy(tmp_path, "csv-validator")
    probe = "import socket; socket.create_connection(('1.1.1.1', 443), 3)"
    (task / "solution/deterministic.json").write_text(json.dumps({"steps": [["sh", "-c", f'! python -c "{probe}"']]}))
    backend = local.LocalDockerBackend(str(tmp_path / "plane"))
    run_set = backend.submit(TrialPlan("neg", [load_task(task)], {"noop": {"harness": "deterministic"}},
                                       environment="bare"))
    d = tmp_path / "plane/raw" / run_set / "csv-validator/noop/1"
    assert json.loads((d / "attempt.json").read_text())["outcome"] == "completed"  # the probe could not connect
    assert json.loads((d / "reward.json").read_text())["reward"] == 0
    con = connect(str(tmp_path / "plane"))  # kept: the relation reads through it
    row = con.sql("select exit_code from grades").fetchone()
    assert row is not None and row[0] != 0
