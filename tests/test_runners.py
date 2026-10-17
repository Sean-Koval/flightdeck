"""The experiment submission client (docs/runners.md): plans, model pins, the cost gate, a recorded hangar."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import flatten, schema
from flightdeck.dataplane.duck import connect
from flightdeck.runners import cli as runners_cli
from flightdeck.runners.hangar import (
    Backend,
    RunnerError,
    RunSetStatus,
    TrialPlan,
    build_specs,
    gate,
    history,
    load_plan,
    model_problem,
    pin_problems,
)
from flightdeck.tasks.format import TaskError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPEC_SCHEMA = json.loads((FIXTURES / "hangar" / "experiment-spec.schema.json").read_text())
LOCKED = {"claude-code": "2.3.1", "codex": "0.162.1"}


def _suite(tmp_path: Path, **over: Any) -> Path:
    doc = {"suite": "smoke", "tasks": [str(ROOT / "tasks" / "smoke")], "n": 2, "budget_usd": 20,
           "trial_budget_usd": 3, "parallel": 4,
           "variants": {"control": {"harness": "claude-code", "model": "claude-opus-5-5"},
                        "codex": {"harness": "codex@0.162.1", "model": "gpt-6.1-sol"}}}
    doc.update(over)
    path = tmp_path / "suite.yaml"
    path.write_text(json.dumps(doc))  # JSON is YAML
    return path


class Hangar:
    """A recorded hangar: POST /api/experiments validates the body against hangar's ExperimentSpec schema and its
    harness lock; GET /api/experiments/{id} answers queued once, then with every trial done."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.specs: dict[str, dict] = {}
        self.gets: dict[str, int] = {}

    def index(self, exp: str) -> dict[str, Any]:
        spec, seen = self.specs[exp], self.gets.get(exp, 0)
        self.gets[exp] = seen + 1
        base = {"schema": "hangar.experiment/v1", "id": exp, "name": spec["name"], "person": "dev-a",
                "created_at": time.time(), "spec": spec, "notes": []}
        n = len(spec["tasks"]) * len(spec["variants"]) * spec["trials"]
        if seen == 0:
            return {**base, "state": "queued", "pins": {}, "counts": {"pending": n}, "trials": []}
        pins = {"variants": {k: {"environment": spec["environment"], "harness": (v.get("harness") or "").split("@")[0],
                                 "harness_version": "1", "model": v.get("model"), "approvals": "auto", "skills": None}
                             for k, v in spec["variants"].items()},
                "tasks": {t["id"]: {"repo": None, "base_sha": "c" * 40} for t in spec["tasks"]}}
        trials = [{"key": f"{t['id']}/{v}/{i}", "task": t["id"], "variant": v, "trial": i, "job": f"job-{i}",
                   "state": "done", "outcome": "succeeded", "started_at": time.time(), "finished_at": time.time(),
                   "manifests": [], "config_digest": None, "verify": None, "stored": [], "drift": [], "links": {},
                   "usage": {"cost_usd": 0.25, "model": spec["variants"][v].get("model")},
                   "grade": {"command": spec["grader"]["command"], "exit_code": 0, "data": {"reward": 1}}}
                  for t in spec["tasks"] for v in spec["variants"] for i in range(1, spec["trials"] + 1)]
        return {**base, "state": "succeeded", "pins": pins, "counts": {"done": n}, "trials": trials}

    def serve(self) -> tuple[ThreadingHTTPServer, str]:
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # quiet
                pass

            def _send(self, code: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:  # noqa: N802
                rec.requests.append(("POST", self.path))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                try:
                    jsonschema.validate(body, SPEC_SCHEMA)
                except jsonschema.ValidationError as e:
                    return self._send(422, {"detail": [{"loc": ["body", *e.path], "msg": e.message}]})
                for name, v in body["variants"].items():
                    h, _, ver = (v.get("harness") or "").partition("@")
                    if ver and ver != LOCKED.get(h):
                        return self._send(400, {"detail": f"variant {name}: {h}@{ver} isn't what hangar runs: its "
                                                f"lock pins {LOCKED.get(h)} (harnesses.lock.yaml)"})
                exp = f"exp-{len(rec.specs) + 1}"
                rec.specs[exp] = body
                self._send(200, rec.index(exp))
                rec.gets[exp] = 0  # the submit's answer doesn't count as a status read

            def do_GET(self) -> None:  # noqa: N802
                rec.requests.append(("GET", self.path))
                exp = self.path.rsplit("/", 1)[-1]
                if exp not in rec.specs:
                    return self._send(404, {"detail": "not found"})
                self._send(200, rec.index(exp))

        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def hangar(monkeypatch: pytest.MonkeyPatch):
    rec = Hangar()
    server, url = rec.serve()
    monkeypatch.setenv("HANGAR_URL", url)
    monkeypatch.setenv("HANGAR_TOKEN", "test-token")
    monkeypatch.delenv("FLIGHTDECK_DATA_URI", raising=False)
    monkeypatch.delenv("FLIGHTDECK_BUDGETS", raising=False)
    yield rec
    server.shutdown()


def test_dry_run_prints_the_spec_and_projection_without_calling_hangar(tmp_path: Path, hangar: Hangar) -> None:
    r = CliRunner().invoke(app, ["experiment", "run", str(_suite(tmp_path)), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "projection: $12.00 = 1 task(s) x 2 variant(s) x 2 trial(s)" in r.output
    assert "semver $3.00 (assumed)" in r.output
    spec = json.loads(r.output[r.output.index("{"):])
    jsonschema.validate(spec, SPEC_SCHEMA)
    assert spec["trials"] == 2 and spec["environment"] == "bare" and spec["tasks"][0]["id"] == "semver"
    assert spec["budget"] == {"max_cost_usd": 20} and spec["trial_job_budget"] == {"max_cost_usd": 3}
    assert hangar.requests == []


def test_submit_status_collect_round_trip_into_parquet(tmp_path: Path, hangar: Hangar) -> None:
    runner, data = CliRunner(), str(tmp_path / "plane")
    r = runner.invoke(app, ["experiment", "run", str(_suite(tmp_path))])
    assert r.exit_code == 0, r.output
    assert "submitted exp-1" in r.output and hangar.specs["exp-1"]["variants"]["codex"]["model"] == "gpt-6.1-sol"
    s = runner.invoke(app, ["experiment", "status", "exp-1"])  # first answer: queued, nothing pinned yet
    assert s.exit_code == 0 and "exp-1: queued" in s.output and "pending=4" in s.output
    s = runner.invoke(app, ["experiment", "status", "exp-1", "--json"])
    assert s.exit_code == 0 and json.loads(s.output)["state"] == "succeeded"
    c = runner.invoke(app, ["experiment", "collect", "exp-1", "--data", data])
    assert c.exit_code == 0, c.output
    con = connect(data)
    assert con.sql("select count(*), sum(cost_usd) from runs where experiment_id = 'exp-1'").fetchone() == (4, 1.0)
    assert con.sql("select count(*) from grades").fetchone() == (4,)
    assert runner.invoke(app, ["experiment", "collect", "exp-1", "--data", data]).exit_code == 0  # replaces its part
    assert connect(data).sql("select count(*) from runs").fetchone() == (4,)
    assert [m for m, _ in hangar.requests] == ["POST", "GET", "GET", "GET", "GET"]


@pytest.mark.parametrize("model", ["frontier", "balanced", "latest", "frontier@openai", "claude-opus-latest", "opus",
                                   "sonnet", "gpt-5", "claude-opus-5", "~anthropic/claude-opus", "gemini-flash-latest",
                                   None])
def test_floating_models_are_refused(model: str | None) -> None:
    assert model_problem(model)


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-fable-5-1", "claude-opus-4-5-20251101",
                                   "claude-3-5-sonnet-20241022", "gpt-6.1-sol", "gpt-6-astra", "gpt-4o-2024-08-06",
                                   "gemini-3.8-flash", "gemini-3.8-flash-high", "openrouter/anthropic/claude-opus-5.5"])
def test_concrete_models_pass(model: str) -> None:
    assert model_problem(model) is None


def test_run_refuses_a_floating_alias_with_a_clear_message(tmp_path: Path, hangar: Hangar) -> None:
    suite = _suite(tmp_path, variants={"a": {"model": "balanced"}, "b": {"model": "claude-opus-5-5"}})
    r = CliRunner().invoke(app, ["experiment", "run", str(suite), "--dry-run"])
    assert r.exit_code == 1 and "variant a: 'balanced' is a policy" in r.output and "variant b" not in r.output
    ok = CliRunner().invoke(app, ["experiment", "run", str(suite), "--dry-run", "--allow-model", "balanced"])
    assert ok.exit_code == 0, ok.output


def test_a_harness_version_off_hangars_lock_is_surfaced(tmp_path: Path, hangar: Hangar) -> None:
    suite = _suite(tmp_path, variants={"codex": {"harness": "codex@0.1.0", "model": "gpt-6.1-sol"}})
    r = CliRunner().invoke(app, ["experiment", "run", str(suite)])
    assert r.exit_code == 1
    assert "hangar refused POST /api/experiments (400): variant codex: codex@0.1.0 isn't what hangar runs" in r.output


def test_cost_gate_refuses_over_the_authors_remaining_sub_cap(tmp_path: Path, hangar: Hangar) -> None:
    budgets = tmp_path / "budgets.yaml"
    budgets.write_text("month_usd: 1500\nauthors:\n  dev-a: 10\n  dev-b: 100\n")
    args = ["experiment", "run", str(_suite(tmp_path)), "--budgets", str(budgets)]
    r = CliRunner().invoke(app, [*args, "--author", "dev-a"])
    assert r.exit_code == 1 and f"over dev-a's remaining $10.00 this month (authors.dev-a in {budgets})" in r.output
    assert "projection: $12.00" in r.output and hangar.requests == []
    assert "name the author" in CliRunner().invoke(app, args).output
    assert CliRunner().invoke(app, [*args, "--author", "dev-b", "--dry-run"]).exit_code == 0
    assert "over --max-usd $5.00" in CliRunner().invoke(app, [*args, "--author", "dev-b", "--max-usd", "5"]).output


def test_history_gives_task_p50_and_this_months_spend(tmp_path: Path) -> None:
    now = time.time()
    index = {"schema": "hangar.experiment/v1", "id": "old", "person": "dev-a", "pins": {}, "trials": [
        {"key": f"semver/control/{i}", "task": "semver", "variant": "control", "trial": i, "started_at": now,
         "usage": {"cost_usd": c}} for i, c in enumerate([0.5, 1.0, 4.0], 1)]}
    for name, rows in flatten.flatten_experiment(index).items():
        if rows:
            schema.write_partitioned(name, rows, str(tmp_path))
    p50, team, mine = history(str(tmp_path), "dev-a")
    assert p50 == {"semver": 1.0} and team == mine == 5.5
    assert history(str(tmp_path), "dev-b")[2] == 0
    assert history(str(tmp_path / "empty"), "dev-a") == ({}, 0.0, 0.0)
    budgets = tmp_path / "b.yaml"
    budgets.write_text("month_usd: 8\n")
    assert "team's remaining $2.50" in gate(4.0, None, budgets, None, team, mine)[0]


def test_plans_over_hangars_caps_split_into_experiments_sharing_a_suite_run(tmp_path: Path) -> None:
    plan = load_plan(_suite(tmp_path, n=20))
    plan.tasks = plan.tasks * 3
    with pytest.raises(TaskError, match="unique"):  # one experiment of three semvers would clash
        build_specs(TrialPlan("x", plan.tasks, plan.variants, 20, "bare"))
    specs = build_specs(plan, max_total=40)
    assert [s["name"] for s in specs] == [f"smoke-{plan.suite_run}-{i}" for i in (1, 2, 3)]
    assert [s["budget"]["max_cost_usd"] for s in specs] == [6.67, 6.67, 6.67]
    with pytest.raises(RunnerError, match="1-20 trials"):
        build_specs(TrialPlan("x", plan.tasks, plan.variants, 21, "bare"))


def test_pin_problems_flag_unpinned_bases_and_split_models() -> None:
    index = {"spec": {"variants": {"a": {"model": "claude-opus-5-5"}, "b": {"model": "claude-opus-5-5"}}},
             "pins": {"tasks": {"t1": {"base_sha": None}, "t2": {"base_sha": "c" * 40}},
                      "variants": {"a": {"model": "claude-opus-5-5"}, "b": {"model": "claude-opus-5-6"}}}}
    problems = pin_problems(index)
    assert "task t1: no base_sha pinned" in problems and len(problems) == 2
    assert "pinned to different ids" in problems[1]


class FakeBackend:
    """Implements only the Backend interface; the commands must work through it alone."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, plan: TrialPlan) -> str:
        self.calls.append(f"submit {plan.suite} {len(plan.tasks)}")
        return "rs-1"

    def status(self, run_set: str) -> RunSetStatus:
        self.calls.append(f"status {run_set}")
        return RunSetStatus(run_set, "running", {"done": 1, "running": 3}, {run_set: "running"}, [], [])

    def collect(self, run_set: str) -> Path:
        self.calls.append(f"collect {run_set}")
        return Path("/plane")


def test_commands_use_only_the_backend_interface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBackend()
    typed: Backend = fake  # pyright checks the double against the Protocol
    monkeypatch.setattr(runners_cli, "backend", lambda data=None: typed)
    runner = CliRunner()
    assert runner.invoke(app, ["experiment", "run", str(_suite(tmp_path))]).exit_code == 0
    assert "running  done=1  running=3" in runner.invoke(app, ["experiment", "status", "rs-1"]).output
    assert runner.invoke(app, ["experiment", "collect", "rs-1"]).exit_code == 0
    assert fake.calls == ["submit smoke 1", "status rs-1", "collect rs-1"]
