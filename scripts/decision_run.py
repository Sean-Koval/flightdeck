"""The flightdeck#20 run (KAN-31): check everything a human can't see at a glance, then start it with one command.

usage:
  python scripts/decision_run.py preflight --harness ~/team-harness [--data DIR] [--assume 3]
  python scripts/decision_run.py start --harness ~/team-harness --data DIR --author NAME --spend   # spends money
  python scripts/decision_run.py finish --harness ~/team-harness --data DIR [--post owner/repo#n]

`preflight` spends nothing and needs no network. It reads the team-harness checkout that holds the pre-registered
`flightdeck/decision.yaml` and `flightdeck/suite.yaml`, and fails on anything that would make the verdict invalid:
an edited or uncommitted decision.yaml, a task that fails `task check`, a model alias, a projection over the suite's
budget, an arm whose environment file sets no restrictive `egress` (trials could read the hidden tests), or
`min_tasks` above the suite's size. Warnings don't block. They are things a person must decide.

`start` runs preflight, refuses without `--spend`, `HANGAR_URL` and `HANGAR_TOKEN`, then runs `flightdeck experiment
run <suite> --max-usd <budget_usd>` (never `--cache`), and writes the run set, the commit and every task digest to
`<data>/flightdeck20.json`. `finish` reads that file, refuses until hangar says the run set is done, collects it,
and writes the report (`<data>/flightdeck20-report.md`), posting it when `--post` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from flightdeck.report.markdown import committed_at, read_decision
from flightdeck.runners import hangar as h
from flightdeck.tasks.format import TaskError, to_hangar_task

DECISION, SUITE, STATE = "flightdeck/decision.yaml", "flightdeck/suite.yaml", "flightdeck20.json"
RULE_KEYS = ("metric", "direction", "margin", "min_tasks")
OPEN = {None, "", "open"}


@dataclass
class Check:
    name: str
    level: str  # ok, warn, fail
    detail: str


def git(root: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def environments(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every hangar environment file in the checkout, by its `name`."""
    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    for p in sorted([*root.glob("harnesses/*/env*.yaml"), *root.glob("environments/**/*.yaml")]):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("name"), str):
            out.setdefault(doc["name"], (p, doc))
    return out


def preflight(root: Path, data: str | None = None, assume: float = 3.0) -> tuple[list[Check], h.TrialPlan | None]:
    """Every check, in order, and the plan when the suite loads."""
    checks: list[Check] = []
    add = lambda name, ok, detail, bad="fail": checks.append(Check(name, "ok" if ok else bad, detail))  # noqa: E731
    decision, suite = root / DECISION, root / SUITE
    if not decision.is_file() or not suite.is_file():
        add("checkout", False, f"{root} has no {DECISION} and {SUITE}: pass --harness <team-harness checkout>")
        return checks, None
    dirty = git(root, "status", "--porcelain", "--", "flightdeck")
    add("checkout", dirty == "", "flightdeck/ is committed as it is" if dirty == "" else
        f"uncommitted changes under flightdeck/ (the report gives No verdict): {dirty or 'not a git checkout'}")
    add("decision committed", committed_at(decision) is not None,
        f"{DECISION} is committed; its commit time pre-registers it" if committed_at(decision) is not None else
        f"{DECISION} is not committed as it is")
    head, main = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "origin/main")
    add("at origin/main", bool(head) and head == main, f"HEAD {head and head[:12]} is origin/main" if head == main
        else f"HEAD {head and head[:12]} is not origin/main {main and main[:12]}: git pull first", "warn")
    rule = read_decision(decision)
    missing = [k for k in RULE_KEYS if k not in rule]
    add("decision rule", not missing, ", ".join(f"{k}={rule[k]}" for k in RULE_KEYS if k in rule)
        + (f"; missing {', '.join(missing)}" if missing else ""))
    try:
        plan = h.load_plan(suite)
    except (h.RunnerError, TaskError) as e:
        add("suite", False, str(e))
        return checks, None
    bad = []
    for t in plan.tasks:
        try:
            to_hangar_task(t)
        except TaskError as e:
            bad.append(f"{t.id}: {e}")
    add("tasks", not bad, f"{len(plan.tasks)} tasks pass task check" if not bad else "; ".join(bad))
    least = int(rule.get("min_tasks") or 0)
    add("min_tasks", least < len(plan.tasks), f"min_tasks {least} < {len(plan.tasks)} tasks" if least < len(plan.tasks)
        else f"min_tasks {least} with {len(plan.tasks)} tasks: one excluded task makes the verdict 'No decision: "
        "underpowered'; lower it in decision.yaml before trial 1, or add tasks",
        "fail" if least > len(plan.tasks) else "warn")
    try:
        h.check_models(plan)
        add("models", True, ", ".join(sorted({str(v.get("model")) for v in plan.variants.values()})))
    except h.RunnerError as e:
        add("models", False, str(e))
    p50, _, _ = h.history(data and os.path.expanduser(data), None)
    total, per = h.project(plan, p50, assume)
    cap, assumed = plan.budget_usd, sum(k not in p50 for k in per)
    add("projection", cap is not None and total <= cap, f"${total:,.2f} for {len(plan.tasks)} x {len(plan.variants)} x "
        f"{plan.n} against budget_usd {cap}" + (f"; {assumed} task(s) at --assume ${assume:.2f} (no cost history)"
                                               if assumed else ""))
    envs = environments(root)
    for name, v in plan.variants.items():
        env = v.get("environment") or plan.environment
        if env not in envs:
            add(f"arm {name}", False, f"environment {env}: no file names it in {root}, so its egress can't be checked")
            continue
        path, doc = envs[env]
        mode = (doc.get("egress") or {}).get("mode") if isinstance(doc.get("egress"), dict) else doc.get("egress")
        presets = (doc.get("egress") or {}).get("presets") or [] if isinstance(doc.get("egress"), dict) else []
        rel = path.relative_to(root)
        add(f"arm {name} egress", mode not in OPEN and "github" not in presets,
            f"{env} ({rel}): egress {mode}" + (f", presets {presets}" if presets else "") if mode not in OPEN else
            f"{env} ({rel}) sets no egress, so hangar's default (open) applies: a trial can fetch the public suite's "
            "hidden tests. Set `egress: {mode: allowlist}` without the github preset, or `none` (KAN-223)")
        revs = re.findall(r"\br\d+\b", str(doc.get("description") or ""))
        if revs:
            said = decision.read_text(encoding="utf-8")
            add(f"arm {name} revision", all(re.search(rf"\b{r}\b", said) for r in revs),
                f"{env} is {', '.join(revs)}" + ("" if all(re.search(rf"\b{r}\b", said) for r in revs) else
                                                f", which {DECISION} doesn't name: the arms aren't the ones it "
                                                "pre-registered. Re-render or amend it before trial 1"), "warn")
    return checks, plan


def show(checks: list[Check]) -> bool:
    for c in checks:
        print(f"{c.level:<4}  {c.name:<22} {c.detail}")
    fails = sum(c.level == "fail" for c in checks)
    print(f"preflight: {fails} failed, {sum(c.level == 'warn' for c in checks)} warnings")
    return fails == 0


def flightdeck(*args: str) -> subprocess.CompletedProcess[str]:
    r = subprocess.run([sys.executable, "-c", "from flightdeck.cli import run; run()", *args], capture_output=True,
                       text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r


def start(root: Path, data: str, author: str, spend: bool, assume: float) -> int:
    checks, plan = preflight(root, data, assume)
    if not show(checks) or plan is None:
        return 1
    missing = [k for k in ("HANGAR_URL", "HANGAR_TOKEN") if not os.environ.get(k)]
    if missing or not spend:
        print("not started: " + (f"set {', '.join(missing)}; " if missing else "") +
              ("" if spend else "pass --spend to submit trials that cost money"))
        return 1
    r = flightdeck("experiment", "run", str(root / SUITE), "--max-usd", str(plan.budget_usd), "--assume", str(assume),
                   "--author", author, "--data", data)
    m = re.search(r"^submitted (\S+)", r.stdout, re.M)
    if r.returncode or not m:
        return r.returncode or 1
    state = {"run_set": m.group(1), "suite_run": plan.suite_run, "commit": git(root, "rev-parse", "HEAD"),
             "author": author, "tasks": {t.id: t.digest for t in plan.tasks}}
    out = Path(os.path.expanduser(data)) / STATE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}; when hangar is done: python scripts/decision_run.py finish --harness {root} --data {data}")
    return 0


def finish(root: Path, data: str, post: str | None) -> int:
    path = Path(os.path.expanduser(data)) / STATE
    if not path.is_file():
        print(f"{path}: no run started (python scripts/decision_run.py start ...)")
        return 1
    state = json.loads(path.read_text(encoding="utf-8"))
    head = git(root, "rev-parse", "HEAD")
    if head != state["commit"]:
        print(f"note: the checkout is at {head and head[:12]}, the run started at {state['commit'][:12]}")
    r = flightdeck("experiment", "status", state["run_set"], "--json")
    try:
        st = json.loads(r.stdout).get("state")
    except ValueError:
        return r.returncode or 1
    if st not in ("succeeded", "failed", "cancelled"):
        print(f"run set is {st}: rerun finish once hangar is done (eval jobs start 20:00-00:15 ET)")
        return 1
    if r.returncode:
        print("note: pins break pairing in some trials; the report's exclusions show which")
    if flightdeck("experiment", "collect", state["run_set"], "--data", data).returncode:
        return 1
    report = Path(os.path.expanduser(data)) / "flightdeck20-report.md"
    args = ["report", "experiment", state["run_set"], "--a", "stable", "--b", "candidate", "--decision",
            str(root / DECISION), "--data", data, "--out", str(report)]
    return flightdeck(*args, *(["--post", post] if post else [])).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["preflight", "start", "finish"])
    ap.add_argument("--harness", type=Path, required=True, help="The team-harness checkout.")
    ap.add_argument("--data", default=os.environ.get("FLIGHTDECK_DATA_URI"), help="Data plane directory.")
    ap.add_argument("--assume", type=float, default=3.0, help="$ per trial for a task without cost history.")
    ap.add_argument("--author", default=os.environ.get("FLIGHTDECK_AUTHOR"), help="Whose sub-cap the run spends.")
    ap.add_argument("--spend", action="store_true", help="Really submit trials (start only).")
    ap.add_argument("--post", help="owner/repo#n to post the report on (finish only).")
    a = ap.parse_args(argv)
    root = a.harness.expanduser().resolve()
    if a.command == "preflight":
        return 0 if show(preflight(root, a.data, a.assume)[0]) else 1
    if not a.data or (a.command == "start" and not a.author):
        ap.error("--data (and, for start, --author) are required")
    return start(root, a.data, a.author, a.spend, a.assume) if a.command == "start" else finish(root, a.data, a.post)


if __name__ == "__main__":
    sys.exit(main())
