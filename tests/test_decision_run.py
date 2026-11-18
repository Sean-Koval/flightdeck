"""scripts/decision_run.py, the flightdeck#20 run (KAN-31): preflight blocks what would void the verdict, and start
never spends without --spend and hangar's credentials. Synthetic team-harness checkouts only; nothing is submitted."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("decision_run", ROOT / "scripts" / "decision_run.py")
assert spec and spec.loader
dr = sys.modules["decision_run"] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

DECISION = """# Decision: does stable move from r1 to r2?
metric: cost_usd
direction: lower
margin: 0.40
min_tasks: {least}
"""
SUITE = """suite: ab
tasks: ["tasks"]
environment: bare
n: 3
budget_usd: {budget}
variants:
  stable: {{environment: env-a, model: claude-opus-5-5}}
  candidate: {{environment: env-b, model: claude-opus-5-5}}
"""
ENV = "name: {name}\ndescription: harness x, {rev}\n{egress}"


def harness(tmp: Path, *, least: int = 1, budget: float = 100, egress: str = "egress: {mode: none}\n",
            revs: tuple[str, str] = ("r1", "r2"), commit: bool = True) -> Path:
    root = tmp / "team-harness"
    shutil.copytree(ROOT / "tasks" / "smoke" / "semver", root / "flightdeck" / "tasks" / "semver")
    (root / "flightdeck" / "decision.yaml").write_text(DECISION.format(least=least))
    (root / "flightdeck" / "suite.yaml").write_text(SUITE.format(budget=budget))
    (root / "harnesses" / "x").mkdir(parents=True)
    for name, rev, f in (("env-a", revs[0], "env.stable.yaml"), ("env-b", revs[1], "env.candidate.yaml")):
        (root / "harnesses" / "x" / f).write_text(ENV.format(name=name, rev=rev, egress=egress))
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    if commit:
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "pre-register")
    return root


def levels(root: Path, **kw) -> dict[str, str]:
    return {c.name: c.level for c in dr.preflight(root, **kw)[0]}


def test_a_sound_checkout_passes(tmp_path: Path) -> None:
    got = levels(harness(tmp_path), assume=3.0)
    assert {k: v for k, v in got.items() if v == "fail"} == {}
    assert got["tasks"] == got["projection"] == got["arm stable egress"] == got["arm candidate revision"] == "ok"
    assert got["at origin/main"] == "warn"  # no remote in a fixture


def test_open_egress_fails_both_arms(tmp_path: Path) -> None:
    got = levels(harness(tmp_path, egress=""))
    assert got["arm stable egress"] == got["arm candidate egress"] == "fail"
    gh = levels(harness(tmp_path / "gh", egress="egress: {mode: allowlist, presets: [packages, github]}\n"))
    assert gh["arm candidate egress"] == "fail"  # the github preset reaches the public suite


def test_projection_over_budget_fails(tmp_path: Path) -> None:
    root = harness(tmp_path, budget=10)  # 1 task x 2 arms x 3 trials x $3 = $18
    assert levels(root)["projection"] == "fail"
    assert levels(root, assume=1.0)["projection"] == "ok"


def test_min_tasks_at_or_over_the_suite(tmp_path: Path) -> None:
    assert levels(harness(tmp_path / "a", least=1))["min_tasks"] == "warn"
    assert levels(harness(tmp_path / "b", least=2))["min_tasks"] == "fail"


def test_an_arm_the_decision_does_not_name_warns(tmp_path: Path) -> None:
    assert levels(harness(tmp_path, revs=("r1", "r9")))["arm candidate revision"] == "warn"


def test_uncommitted_decision_fails(tmp_path: Path) -> None:
    got = levels(harness(tmp_path, commit=False))
    assert got["checkout"] == got["decision committed"] == "fail"


def test_start_spends_nothing_without_spend_and_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    called = []
    monkeypatch.setattr(dr, "flightdeck", lambda *a: called.append(a))
    monkeypatch.delenv("HANGAR_URL", raising=False)
    root = harness(tmp_path)
    assert dr.main(["start", "--harness", str(root), "--data", str(tmp_path / "plane"), "--author", "a"]) == 1
    monkeypatch.setenv("HANGAR_URL", "http://hangar.invalid")
    monkeypatch.setenv("HANGAR_TOKEN", "x")
    assert dr.main(["start", "--harness", str(root), "--data", str(tmp_path / "plane"), "--author", "a"]) == 1
    assert called == [] and "pass --spend" in capsys.readouterr().out


def test_start_submits_once_and_records_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake(*a: str) -> subprocess.CompletedProcess[str]:
        calls.append(a)
        return subprocess.CompletedProcess(a, 0, "submitted ab-1+ab-2 (suite run 1): ...\n", "")

    monkeypatch.setattr(dr, "flightdeck", fake)
    monkeypatch.setenv("HANGAR_URL", "http://hangar.invalid")
    monkeypatch.setenv("HANGAR_TOKEN", "x")
    root, plane = harness(tmp_path), tmp_path / "plane"
    assert dr.main(["start", "--harness", str(root), "--data", str(plane), "--author", "a", "--spend"]) == 0
    (args,) = calls
    assert args[:2] == ("experiment", "run") and "--cache" not in args and args[args.index("--max-usd") + 1] == "100"
    state = __import__("json").loads((plane / dr.STATE).read_text())
    assert state["run_set"] == "ab-1+ab-2" and set(state["tasks"]) == {"semver"} and len(state["commit"]) == 40
