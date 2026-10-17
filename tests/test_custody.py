"""Sealed holdout custody (#13, docs/holdouts.md): manifest hashes, canaries, blind writers, scored once."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from spec_traces import trace
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.dataplane.ingest import write_unit
from flightdeck.tasks import custody
from flightdeck.tasks.format import load_task

run = CliRunner().invoke
AGAINST = "sha256:" + "c" * 64


def _writer_task(root: Path, writer: str, tid: str, mined_after: str = "2026-10-10", sealed: bool = True) -> Path:
    d = root / "incoming" / writer / tid
    assert run(app, ["task", "new", str(d)]).exit_code == 0
    toml = d / "task.toml"
    toml.write_text(toml.read_text().replace("sealed = false", f"sealed = {str(sealed).lower()}\n"
                                             f'mined_after = "{mined_after}"'))
    return d


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    root = tmp_path / "holdouts"
    for w, tid in (("a", "fix-retry"), ("a", "add-flag"), ("b", "port-parser")):
        _writer_task(root, w, tid)
    res = run(app, ["holdout", "seal", "reg-1", "--writer", "a=claude-haiku-5-5", "--writer", "b=dev-c",
                    "--fresh-after", "2026-10-01", "--holdouts", str(root)])
    assert res.exit_code == 0, res.output
    return root


def _trial(task: str, ok: bool = True, digest: str = AGAINST, version: str | None = "0.9.0") -> dict:
    return {"task_id": task, "harness_digest": digest, "hangar_version": version, "outcome": "succeeded",
            "grade_exit": 0 if ok else 1, "grade_applied": True}


def test_seal_hashes_moves_and_plants_canaries(sealed: Path) -> None:
    doc = custody.load(sealed)
    s = doc["sets"]["reg-1"]
    assert s["status"] == "sealed" and s["tasks"] == {"fix-retry": "a", "add-flag": "a", "port-parser": "b"}
    assert s["writers"] == {"a": "claude-haiku-5-5", "b": "dev-c"}
    assert not list((sealed / "incoming").glob("*/*"))  # moved, not copied
    for tid, c in s["canaries"].items():
        d = sealed / "sealed" / "reg-1" / tid
        assert c in (d / "instruction.md").read_text() and c in (d / "tests" / "test.sh").read_text()
        assert load_task(d).sealed  # files_digest rewritten after the canary went into tests/
    assert len(set(s["canaries"].values())) == 3
    assert all(k.startswith("sealed/reg-1/") for k in doc["files"])
    custody.check_manifest(sealed, doc)


def test_editing_a_sealed_file_makes_score_refuse_with_path_and_both_hashes(sealed: Path) -> None:
    doc = custody.load(sealed)
    p = sealed / "sealed" / "reg-1" / "fix-retry" / "tests" / "test.sh"
    before = doc["files"]["sealed/reg-1/fix-retry/tests/test.sh"]
    p.write_text(p.read_text() + "exit 0\n")
    trials = [_trial(t) for t in ("fix-retry", "add-flag", "port-parser")]
    with pytest.raises(custody.CustodyError) as e:
        custody.score(sealed, doc, "reg-1", AGAINST, "lead", "dev-a", "dev-b", trials, "0.1")
    assert "sealed/reg-1/fix-retry/tests/test.sh" in str(e.value) and before in str(e.value)
    assert custody.sha256(p) in str(e.value)


@pytest.mark.parametrize(("approver", "author", "by"), [("dev-a", "dev-a", "dev-b"), ("dev-b", "dev-a", "dev-b"),
                                                         ("lead", "dev-c", "dev-b")])  # dev-c wrote part of it
def test_score_refuses_the_wrong_people(sealed: Path, approver: str, author: str, by: str) -> None:
    trials = [_trial(t) for t in ("fix-retry", "add-flag", "port-parser")]
    with pytest.raises(custody.CustodyError, match="approver"):
        custody.score(sealed, custody.load(sealed), "reg-1", AGAINST, approver, author, by, trials, "0.1")


def test_score_needs_the_whole_set_on_the_candidate_and_a_recent_hangar(sealed: Path) -> None:
    doc = custody.load(sealed)
    good = [_trial(t) for t in ("fix-retry", "add-flag", "port-parser")]
    for bad in (good[:2], [*good[:2], _trial("port-parser", digest="sha256:other")],
                [*good[:2], _trial("port-parser", version="0.8.9")], [*good[:2], _trial("port-parser", version=None)]):
        with pytest.raises(custody.CustodyError, match="must cover"):
            custody.score(sealed, doc, "reg-1", AGAINST, "lead", "dev-a", "dev-b", bad, "0.9")
    assert doc["sets"]["reg-1"]["status"] == "sealed"


def test_scored_once(sealed: Path) -> None:
    doc = custody.load(sealed)
    trials = [_trial("fix-retry"), _trial("add-flag", ok=False), _trial("port-parser")]
    r = custody.score(sealed, doc, "reg-1", AGAINST, "lead", "dev-a", "dev-b", trials, "0.9")
    assert (r["resolved"], r["n"]) == (2, 3) and r["per_task"]["add-flag"] == [False]
    s = doc["sets"]["reg-1"]
    assert s["status"] == "scored" and s["scored_by"] == "dev-b" and s["scored_against"] == AGAINST
    with pytest.raises(custody.CustodyError, match="scored once"):
        custody.score(sealed, doc, "reg-1", AGAINST, "lead", "dev-a", "dev-b", trials, "0.9")


def test_seal_refusals(tmp_path: Path) -> None:
    root = tmp_path / "h"
    args = ["holdout", "seal", "s", "--writer", "a=x", "--fresh-after", "2026-10-01", "--holdouts", str(root)]
    _writer_task(root, "a", "old", mined_after="2026-09-30")
    assert "mined_after" in run(app, args).output
    (root / "incoming" / "a" / "old" / "task.toml").unlink()
    _writer_task(root, "a", "open", sealed=False)
    assert "sealed = true" in run(app, args).output
    (root / "incoming" / "a" / "open" / "task.toml").unlink()
    _writer_task(root, "a", "ok")
    assert run(app, args).exit_code == 0
    _writer_task(root, "a", "more")
    assert "spent once" in run(app, args).output


def test_canary_in_a_trace_voids_the_set(sealed: Path, tmp_path: Path) -> None:
    c = custody.load(sealed)["sets"]["reg-1"]["canaries"]["add-flag"]
    plane = str(tmp_path / "plane")
    otlp = trace([("tool", "shell", f"grep -r {c} /", ["test"])])
    write_unit(flatten_trace(otlp), plane, "job-x")
    clean = run(app, ["holdout", "canary-scan", "--data", plane, "--since", "100000", "--holdouts",
                      str(tmp_path / "none")])
    assert clean.exit_code == 1 and "\t?\t?\t" in clean.output  # unknown canary still reported
    res = run(app, ["holdout", "canary-scan", "--data", plane, "--since", "100000", "--holdouts", str(sealed)])
    assert res.exit_code == 1 and "CANARY\treg-1\tadd-flag\tspans" in res.output
    s = custody.load(sealed)["sets"]["reg-1"]
    assert s["status"] == "void" and "add-flag" in s["void_reason"]
    log = tmp_path / "retrieval.log"
    log.write_text("nothing here\n")
    assert run(app, ["holdout", "canary-scan", "--data", str(tmp_path / "empty"), "--logs", str(log),
                     "--holdouts", str(sealed)]).exit_code == 0


def test_score_cli_reads_the_plane_and_commits_manifest_with_result(sealed: Path, tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in (("NAME", "t"), ("EMAIL", "t@example.com")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    git = ["git", "-C", str(sealed)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    plane = str(tmp_path / "plane")
    base = {"source": "experiment", "dt": "2026-10-17", "experiment_id": "exp1"}
    runs, grades, manifests = [], [], []
    for i, t in enumerate(("fix-retry", "add-flag", "port-parser")):
        rid = f"exp1/{t}"
        runs.append({**base, "run_id": rid, "task_id": t, "variant": "cand", "trial": 1, "outcome": "succeeded",
                     "config_digest": AGAINST, "trial_key": t})
        grades.append({**base, "run_id": rid, "trial_key": t, "exit_code": 0, "applied": True})
        manifests.append({"run_id": rid, "source": "experiment", "dt": "2026-10-17", "digest": f"m{i}",
                          "json": json.dumps({"hangar": {"version": "1.2.0"}})})
    write_unit({"runs": runs, "grades": grades, "manifests": manifests}, plane, "experiment-exp1")
    cmd = ["holdout", "score", "reg-1", "--run-set", "exp1", "--against", AGAINST, "--approve", "lead", "--author",
           "dev-a", "--by", "dev-b", "--data", plane, "--holdouts", str(sealed)]
    custody.save(sealed, {**custody.load(sealed), "min_hangar_version": "1.3"})
    assert "hangar >= 1.3" in run(app, cmd).output
    custody.save(sealed, {**custody.load(sealed), "min_hangar_version": "1.0"})
    res = run(app, cmd)
    assert res.exit_code == 0, res.output
    assert "3/3 resolved" in res.output
    assert json.loads((sealed / "results" / "reg-1.json").read_text())["approved_by"] == "lead"
    assert custody.load(sealed)["sets"]["reg-1"]["status"] == "scored"
    assert run(app, cmd).exit_code == 1
    shown = subprocess.run([*git, "show", "--name-only", "--format=%s"], capture_output=True, text=True).stdout
    assert shown.split() == ["holdout:", "score", "reg-1", "against", AGAINST, "manifest.json", "results/reg-1.json"]


def test_brief_follows_the_blind_writer_shape(tmp_path: Path) -> None:
    res = run(app, ["holdout", "brief", "reg-2", "--writers", "2", "--count", "24", "--mined-after", "2026-10-01",
                    "--holdouts", str(tmp_path)])
    assert res.exit_code == 0
    a, b = (tmp_path / "briefs" / f"reg-2_writer_{w}.txt" for w in "ab")
    assert "do NOT read any file in this repository" in a.read_text() and "incoming/b/" in b.read_text()
    assert "At least 24 tasks" in a.read_text() and not re.search(r"\{\w+\}", a.read_text())
