"""scripts/mine_regression.py, regression-v1's miner (flightdeck#12, KAN-88), on synthetic labels, a synthetic data
plane and a synthetic git repository: fail-to-pass is checked, and every row that can't be mined says why."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from flightdeck.dataplane.schema import write_partitioned
from flightdeck.tasks.format import load_task

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mine_regression", ROOT / "scripts" / "mine_regression.py")
assert spec and spec.loader
mr = sys.modules["mine_regression"] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n"


def _git(d: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> dict:
    """A repo with a bug at base, a fix that adds its test, a flaky fix, and a fix that changes no test."""
    repo = tmp_path / "calc"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "calc.py").write_text(BUGGY)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "calc.py").write_text(FIXED)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(TEST)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fix")
    fix = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "flaky", base)
    (repo / "tests").mkdir()
    counter = tmp_path / "flips"  # each run flips the outcome, so the first side to run is seen to vary
    (repo / "tests" / "test_flaky.py").write_text(
        f"from pathlib import Path\n\n\ndef test_flip():\n    p = Path({str(counter)!r})\n"
        "    n = int(p.read_text()) if p.exists() else 0\n    p.write_text(str(n + 1))\n    assert n % 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "flaky")
    flaky = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "notest", base)
    (repo / "src" / "calc.py").write_text(FIXED)
    _git(repo, "commit", "-qam", "untested fix")
    notest = _git(repo, "rev-parse", "HEAD")
    plane = tmp_path / "plane"
    runs = [{"run_id": f"r-{j}", "source": "job", "dt": "2026-11-20", "job_id": j, "repo": "example/calc",
             "base_sha": base, "environment": "team-default"} for j in ("j-ok", "j-flaky", "j-notest", "j-nofix")]
    write_partitioned("runs", runs, str(plane))
    row = {"labelled_by": "reviewer", "labelled_at": "2026-11-21", "first_failure_seq": 7, "category": "premature-done",
           "instruction": "add() subtracts. Make it add."}
    labels = [{**row, "job_id": "j-ok", "fixed_by_pr": "example/calc#1", "fix_sha": fix},
              {**row, "job_id": "j-flaky", "fix_sha": flaky, "category": "test-gaming"},
              {**row, "job_id": "j-notest", "fix_sha": notest},
              {**row, "job_id": "j-nofix"}]
    path = tmp_path / "first-failures.yaml"
    path.write_text(yaml.safe_dump(labels))
    return {"repo": repo, "base": base, "fix": fix, "plane": plane, "labels": path, "out": tmp_path / "data"}


def test_validate_names_every_problem(world: dict) -> None:
    rows = mr.load_labels(world["labels"])
    known = mr.jobs(str(world["plane"]))
    assert set(known) == {"j-ok", "j-flaky", "j-notest", "j-nofix"} and known["j-ok"]["base_sha"] == world["base"]
    assert mr.validate(rows, known) == ["4 labelled failures; flightdeck#12 needs 20 (KAN-25)"]
    bad = [{"job_id": "j-x", "category": "lazy", "first_failure_seq": -1, "fix_sha": "abc"}, {"job_id": "j-ok"}]
    got = "\n".join(mr.validate(bad + [{"job_id": "j-ok"}], known))
    for want in ("no job j-x", "category 'lazy'", "first_failure_seq must be", "fix_sha must be a full",
                 "first_failure_seq is missing", "j-ok is labelled twice"):
        assert want in got


def test_mine_checks_fail_to_pass_and_records_each_reason(world: dict) -> None:
    rows, known = mr.load_labels(world["labels"]), mr.jobs(str(world["plane"]))
    lock = mr.mine(rows, known, world["out"], {"example/calc": str(world["repo"])}, runs=3)
    assert list(lock["tasks"]) == ["calc-j-ok"]
    reasons = {u["job_id"]: u["reason"] for u in lock["unmined"]}
    assert reasons["j-flaky"] == "flaky: base passed 1/3, fix passed 2/3"
    assert "changes no tests" in reasons["j-notest"] and reasons["j-nofix"].startswith("needs-tests")
    task = load_task(world["out"] / "tasks" / "regression-v1" / "calc-j-ok")
    fd = task.flightdeck
    assert fd["source"]["base_sha"] == world["base"] and fd["source"]["repo"] == "https://github.com/example/calc.git"
    assert (fd["mined_from"], fd["category"], fd["first_failure_seq"], fd["environment"]) == \
        ("j-ok", "premature-done", 7, "team-default")
    assert set(task.tests) == {"test.sh", "test_calc.py"}
    patch = (task.path / "solution" / "reference.patch").read_text()
    assert "a + b" in patch and "test_calc" not in patch
    saved = json.loads((world["out"] / "suites" / "regression-v1.lock.json").read_text())
    assert saved["tasks"]["calc-j-ok"]["digest"] == task.digest and saved["fail_to_pass_runs"] == 3


def test_a_missing_instruction_or_unreachable_base_is_recorded(world: dict) -> None:
    known = mr.jobs(str(world["plane"]))
    row = {"job_id": "j-ok", "first_failure_seq": 1, "category": "other", "fix_sha": world["fix"]}
    lock = mr.mine([row], known, world["out"], {"calc": str(world["repo"])})
    assert lock["unmined"][0]["reason"].startswith("needs-instruction")
    gone = {**row, "instruction": "x", "base_sha": "0" * 40}
    lock = mr.mine([gone], known, world["out"], {"calc": str(world["repo"])})
    assert "force-pushed" in lock["unmined"][0]["reason"]


def test_cli_validate_and_mine(world: dict, capsys: pytest.CaptureFixture[str]) -> None:
    args = [str(world["labels"]), "--data", str(world["plane"])]
    assert mr.main(["validate", *args]) == 1  # only 4 of 20
    assert mr.main(["mine", *args, "--out", str(world["out"]), "--repo", f"calc={world['repo']}"]) == 1  # 1 < 12
    out = capsys.readouterr().out
    assert "mined    calc-j-ok" in out and "needs at least 12" in out and "this machine" in out
