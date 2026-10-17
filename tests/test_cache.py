"""The trial-result cache and the drift sentinel (#24, docs/runners.md#cache)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_runners import Hangar, _suite, hangar  # noqa: F401
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.dataplane.ingest import write_unit
from flightdeck.runners import cache
from flightdeck.runners.hangar import load_plan
from flightdeck.stats.compare import load_trials

run = CliRunner().invoke


@pytest.fixture
def digests(hangar: Hangar, monkeypatch: pytest.MonkeyPatch) -> Hangar:  # noqa: F811
    """Hangar records an identity per trial, as it does once manifests carry harness and environment digests."""
    plain = hangar.index

    def index(exp: str) -> dict:
        doc = plain(exp)
        for t in doc["trials"]:
            v = doc["spec"]["variants"][t["variant"]]
            t.update(harness_digest="sha256:h-" + json.dumps(v, sort_keys=True), environment_digest="sha256:env-1")
        return doc

    monkeypatch.setattr(hangar, "index", index)
    return hangar


def _round(tmp: Path, suite: Path, data: str, *extra: str) -> str:
    r = run(app, ["experiment", "run", str(suite), "--data", data, *extra])
    assert r.exit_code == 0, r.output
    run_set = r.output.split("submitted ")[1].split()[0]
    for exp in run_set.split("+") if not r.output.count("submitted nothing") else []:
        assert run(app, ["experiment", "status", exp]).exit_code == 0  # hangar answers queued first
        assert run(app, ["experiment", "collect", exp, "--data", data]).exit_code == 0
    return r.output


def test_an_unchanged_suite_submits_nothing_and_reports_every_trial_reused(tmp_path: Path, digests: Hangar) -> None:
    data, suite = str(tmp_path / "plane"), _suite(tmp_path)
    _round(tmp_path, suite, data)
    assert connect(data).sql("select count(*) from runs where task_digest is not null and variant_digest is not "
                             "null").fetchone() == (4,)
    posts = len([m for m, _ in digests.requests if m == "POST"])
    out = _round(tmp_path, suite, data, "--cache")
    assert "cache: 2 of 2 (task, variant) pairs reused, 0-0 days old" in out and "projection: $0.00" in out
    assert "submitted nothing" in out and len([m for m, _ in digests.requests if m == "POST"]) == posts
    run_set = out.split("flightdeck stats compare ")[1].split()[0]
    cmp = run(app, ["stats", "compare", run_set, "--a", "control", "--b", "codex", "--data", data])
    assert cmp.exit_code == 0, cmp.output
    assert "Reused from the trial cache: 4 of 4 trials, 0-0 days old." in cmp.output


def test_changing_one_skill_reruns_only_that_variant(tmp_path: Path, digests: Hangar) -> None:
    data = str(tmp_path / "plane")
    _round(tmp_path, _suite(tmp_path), data)
    changed = _suite(tmp_path, variants={"control": {"harness": "claude-code", "model": "claude-opus-5-5"},
                                         "codex": {"harness": "codex@0.162.1", "model": "gpt-6.1-sol",
                                                   "skills": [{"name": "tdd"}]}})
    out = _round(tmp_path, changed, data, "--cache")
    assert "cache: 1 of 2" in out
    last = digests.specs[max(digests.specs)]
    assert set(last["variants"]) == {"codex"} and last["trials"] == 2
    run_set = out.split("submitted ")[1].split()[0]
    trials = load_trials(connect(data), run_set)
    assert sorted((t["variant"], t["reused_age_days"] is not None) for t in trials) == [
        ("codex", False), ("codex", False), ("control", True), ("control", True)]
    both = load_trials(connect(data), f"exp-1+{run_set}")  # exp-1's control trials are also the reused ones
    assert len(both) == len({t["run_id"] for t in both}) == 6


def test_drop_ttl_and_identity_changes_stop_reuse(tmp_path: Path, digests: Hangar) -> None:
    data, suite = str(tmp_path / "plane"), _suite(tmp_path)
    _round(tmp_path, suite, data)
    plan, con = load_plan(suite), connect(data)
    assert len(cache.lookup(con, plan, data)) == 2
    assert cache.lookup(con, plan, data, ttl_days=-1) == {}
    assert run(app, ["cache", "drop", "--task", "semver", "--data", data]).exit_code == 0
    assert cache.lookup(con, plan, data) == {}


def _row(i: int, d: dict, ident: str, fin: str, **kw) -> dict:
    return {"run_id": f"r{i}", "source": "experiment", "dt": fin[:10], "experiment_id": "e", "task_id": "semver",
            "variant": "control", "trial": i, "outcome": "succeeded", "harness_digest": ident,
            "environment_digest": "env", "model_id": "claude-opus-5-5", "started_at": None,
            "finished_at": __import__("datetime").datetime.fromisoformat(fin + "+00:00"),
            "task_digest": d["task_digests"]["semver"], "variant_digest": d["variant_digests"]["control"], **kw}


def test_only_clean_trials_of_the_current_identity_are_reused(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    plan = load_plan(_suite(tmp_path, n=2))
    plan.variants = {"control": plan.variants["control"]}
    d, now = cache.digests(plan), datetime.now(UTC)
    ago = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
    rows = [_row(1, d, "h1", ago(5)), _row(2, d, "h1", ago(4)), _row(3, d, "h1", ago(3), outcome_class="infra_error"),
            _row(4, d, "h1", ago(2), tainted=True)]
    write_unit({"runs": rows}, str(tmp_path / "p"), "u")
    hits = cache.lookup(connect(str(tmp_path / "p")), plan, str(tmp_path / "p"))
    assert [r for r, _ in hits[("semver", "control")]] == ["r2", "r1"]  # never the infra_error or tainted ones
    write_unit({"runs": [*rows, _row(5, d, "h2", ago(1))]}, str(tmp_path / "p"), "u")  # the provider moved
    assert cache.lookup(connect(str(tmp_path / "p")), plan, str(tmp_path / "p")) == {}  # one h2 trial < n


def test_drift_sentinel_alerts_on_a_step_change(tmp_path: Path) -> None:
    steady = [(f"2026-10-{d:02d}", 9, 10, 2.0, 300.0) for d in range(1, 15)]
    assert cache.drift(steady + [("2026-10-15", 9, 10, 2.1, 310.0)]) == []
    alerts = cache.drift(steady + [("2026-10-15", 2, 10, 4.0, 300.0)])
    assert len(alerts) == 2 and "resolved 2/10" in alerts[0] and "median cost 4.00" in alerts[1]
    suite = _suite(tmp_path, variants={"stable": {"harness": "claude-code", "model": "claude-opus-5-5"}})
    plan = load_plan(suite)
    vd = cache.variant_digest(plan.variants["stable"], plan.environment)
    runs, grades = [], []
    for day in range(1, 16):
        for i in range(10):
            rid, key = f"s{day}-{i}", f"semver/stable/{i}"
            ok = i < (9 if day < 15 else 1)  # a synthetic step on the last night
            runs.append({"run_id": rid, "source": "experiment", "dt": f"2026-10-{day:02d}", "experiment_id": f"x{day}",
                         "task_id": "semver", "variant": "stable", "trial": i, "outcome": "succeeded",
                         "variant_digest": vd, "trial_key": key, "cost_usd": 2.0})
            grades.append({"run_id": rid, "source": "experiment", "dt": f"2026-10-{day:02d}", "experiment_id":
                           f"x{day}", "trial_key": key, "exit_code": 0 if ok else 1, "applied": True})
    write_unit({"runs": runs, "grades": grades}, str(tmp_path / "plane"), "sentinel")
    r = run(app, ["cache", "sentinel", str(suite), "stable", "--data", str(tmp_path / "plane")])
    assert r.exit_code == 1 and "ALERT\t2026-10-15: resolved 1/10" in r.output and "15 day(s), 1 alert(s)" in r.output
