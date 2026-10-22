"""Mutation scoring (#16, docs/mutation-scoring.md): plan mutants, score kills, report survivors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.ingest import write_unit
from flightdeck.specs import mutate

ROOT = Path(__file__).resolve().parent.parent
TESTS_LINE = "Write your own tests in `test_semver.py` (unittest) and make them pass with `python3 -m unittest`.\n"
BASE = {"harness": "claude-code", "model": "claude-opus-5-5", "approvals": "deny-risky",
        "skills": [{"name": "tdd"}, {"name": "review"}],
        "instructions_append": "# Testing\n" + TESTS_LINE + "# Delivery\nCommit everything with git.\n"}
SPEC = ROOT / "specs" / "examples" / "team-default.yaml"


def _suite(tmp: Path) -> Path:
    p = tmp / "suite.yaml"
    p.write_text(yaml.safe_dump({"suite": "smoke", "tasks": [str(ROOT / "tasks" / "smoke")], "environment": "bare",
                                 "n": 3, "variants": {"base": BASE}}))
    return p


def test_plan_derives_each_operator_and_flags_equivalents() -> None:
    ms = mutate.plan(BASE, list(mutate.OPS), seen_skills={"tdd"})
    by = {m["component"]: m for m in ms.values()}
    assert set(by) == {"skill:tdd", "skill:review", "instructions_append:1", "instructions_append:2",
                       "approvals:auto", "none"}
    assert by["skill:review"]["equivalent"] and not by["skill:tdd"]["equivalent"]  # review never fired
    assert by["none"]["equivalent"] and by["none"]["variant"] == BASE
    assert TESTS_LINE not in by["instructions_append:1"]["variant"]["instructions_append"]
    assert by["skill:tdd"]["variant"]["skills"] == [{"name": "review"}]
    assert by["approvals:auto"]["variant"]["approvals"] == "auto"
    assert all(k.startswith("mutant-") for k in ms)
    assert mutate.plan({}, ["drop-skill"], {"x"})["mutant-drop-skill-skill-x"]["variant"] == {"skills_remove": ["x"]}
    with pytest.raises(ValueError, match="widen-egress"):
        mutate.plan(BASE, ["widen-egress"])
    assert len(mutate.plan(BASE, list(mutate.OPS), cap=3)) == 3


def test_plan_cli_writes_a_loadable_suite_without_equivalents(tmp_path: Path) -> None:
    out = tmp_path / "mutants.yaml"
    res = CliRunner().invoke(app, ["mutate", "plan", str(_suite(tmp_path)), "--harness", "base", "--out", str(out),
                                   "--ops", "drop-instruction-line,noop"])
    assert res.exit_code == 0, res.output
    doc = yaml.safe_load(out.read_text())
    assert doc["base"] == "base" and doc["n"] == 2 and set(doc["mutants"]) == {
        "mutant-drop-instruction-line-instructions-append-1", "mutant-drop-instruction-line-instructions-append-2",
        "mutant-noop-none"}
    assert "mutant-noop-none" not in doc["variants"]  # equivalent: listed, never run
    assert "not generated\twiden-egress" in res.output


def test_run_goes_through_the_cost_gate_and_prints_the_projection(tmp_path: Path) -> None:
    out = tmp_path / "mutants.yaml"
    CliRunner().invoke(app, ["mutate", "plan", str(_suite(tmp_path)), "--harness", "base", "--out", str(out)])
    res = CliRunner().invoke(app, ["mutate", "run", str(out), "--dry-run"])
    assert res.exit_code == 0 and res.output.startswith("projection: $36.00")  # 1 task x (base + 5) x 2 x $3
    over = CliRunner().invoke(app, ["mutate", "run", str(out), "--max-usd", "20"])
    assert over.exit_code == 1 and "over --max-usd" in over.output


def _plane(tmp: Path, arms: dict[str, tuple[bool, bool]], tasks: int = 10, n: int = 2) -> str:
    """An experiment where each arm's trials (tested before committing?, resolved?) are the same on every task."""
    rows: dict[str, list[dict]] = {k: [] for k in ("runs", "grades", "spans", "events", "test_cases")}
    for arm, (tested, ok) in arms.items():
        for t in range(tasks):
            for i in range(n):
                rid = f"exp/{arm}/t{t}/{i}"
                base = {"run_id": rid, "source": "experiment", "dt": "2026-10-17"}
                rows["runs"].append({**base, "job_id": rid, "experiment_id": "exp", "task_id": f"t{t}", "variant": arm,
                                     "trial": i + 1, "outcome": "succeeded", "trial_key": f"t{t}/{arm}/{i}"})
                rows["grades"].append({**base, "experiment_id": "exp", "trial_key": f"t{t}/{arm}/{i}",
                                       "exit_code": 0 if ok else 1, "applied": True})
                rows["spans"].append({**base, "trace_id": rid, "span_id": "s", "kind": "job", "job_id": rid,
                                      "start_ns": 0, "end_ns": 9})
                rows["events"].append({**base, "trace_id": rid, "span_id": "s", "name": "git.commit", "time_ns": 5})
                if tested:
                    rows["test_cases"].append({**base, "trace_id": rid, "test_run_id": "x", "status": "pass",
                                               "trusted": True, "total": 4, "complete": True, "time_ns": 3})
    write_unit(rows, str(tmp / "plane"), "experiment-exp")
    return str(tmp / "plane")


def test_dropping_the_tests_line_is_killed_by_tests_before_commit(tmp_path: Path) -> None:
    """The acceptance case on stored results: the mutant without 'Write your own tests' commits untested."""
    drop, skill, grader = ("mutant-drop-instruction-line-instructions-append-1", "mutant-drop-skill-skill-review",
                           "mutant-drop-skill-skill-tdd")
    plane = _plane(tmp_path, {"base": (True, True), drop: (False, True), skill: (True, True), grader: (True, False)})
    plan_file = tmp_path / "mutants.yaml"
    mutants = {k: {x: m[x] for x in ("op", "component", "equivalent")}
               for k, m in mutate.plan(BASE, list(mutate.OPS)).items()}
    plan_file.write_text(yaml.safe_dump({"suite": "smoke-mutants", "base": "base", "mutants": mutants}))
    out = tmp_path / "score.md"
    res = CliRunner().invoke(app, ["mutate", "score", str(plan_file), "exp", "--specs", str(SPEC), "--data", plane,
                                   "--out", str(out)])
    assert res.exit_code == 0, res.output
    md = out.read_text()
    assert f"| {drop} | `instructions_append:1` | killed | spec tests-before-commit: pass^k 1.00 -> 0.00 |" in md
    assert f"| {grader} | `skill:tdd` | killed | resolved -100 pp" in md
    assert "| mutant-noop-none | `none` | equivalent |" in md
    assert "- `skill:review`: `eventually: {tool: {skill: review}}`" in md  # a survivor, with a spec to add
    assert "| mutant-approvals-approvals-auto | `approvals:auto` | not run | no trials in the run set |" in md
    assert "**2/3 killed (67%, 95% Wilson" in md and "1 equivalent and 2 not run (not counted)" in md
