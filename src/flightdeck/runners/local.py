"""`--backend local`: trials in local Docker containers, for fixtures and CI only (docs/local.md).

ai-dlc's attempt runner (`flightdeck.ported.aidlc`) does the isolation. This module maps flightdeck's model onto it: a
task directory in (its environment built to an image id, its tests kept on the controller and run on the collected
tree), `flightdeck.parquet/v1` rows out with `source=local` (runs, grades, spans, events, test_cases), so stats, reports
and specs read a local run set like a hangar experiment. Only the deterministic driver runs here: no model, no
credentials, no network. Model trials and team tasks (sealed or mined) run on hangar.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shlex
import subprocess
import tarfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flightdeck.dataplane import ingest
from flightdeck.ported.aidlc import attempt, drivers, evidence, git_observer
from flightdeck.ported.hangar_traces import shell_ops
from flightdeck.runners import cache
from flightdeck.runners.hangar import RunnerError, RunSetStatus, TrialPlan
from flightdeck.tasks.format import DEFAULT_COMMAND, Task

SOLUTION = "/tmp/flightdeck-solution"
OUTCOMES = {"completed": ("succeeded", None), "infrastructure": ("failed", "infra_error")}  # else failed
Row = dict[str, Any]


def refusal(task: Task) -> str | None:
    if task.sealed or task.flightdeck.get("mined_from"):
        return f"task {task.id} is {'sealed' if task.sealed else 'mined'}: team tasks run on hangar, not locally"
    return None


def pick_driver(task: Task, name: str, v: dict[str, Any]) -> drivers.Deterministic:
    """The variant's driver: `deterministic`, the task's solution with no model."""
    sol = task.path / "solution"
    if v.get("harness") == "deterministic" and (sol / "deterministic.json").is_file():
        return drivers.Deterministic(sol, json.loads((sol / "deterministic.json").read_text(encoding="utf-8")))
    if v.get("harness") == "deterministic" and (sol / "solve.sh").is_file():  # Harbor's oracle: copy solution/ in
        files = [p.relative_to(sol).as_posix() for p in sorted(sol.rglob("*")) if p.is_file()]
        steps = [*({"write": f"{SOLUTION}/{f}", "from": f} for f in files), ["bash", f"{SOLUTION}/solve.sh"]]
        return drivers.Deterministic(sol, {"steps": steps})
    raise RunnerError(f"variant {name}, task {task.id}: the local backend runs only `deterministic` (needs "
                      "solution/solve.sh or solution/deterministic.json); model trials run on hangar")


def build(task: Task) -> tuple[str, str]:
    """(image id, working directory): environment/ built, else a digest-pinned `[environment] docker_image`."""
    env = task.config.get("environment") or {}
    image = env.get("docker_image") if not task.environment else None
    if image and not attempt.PINNED.fullmatch(image):
        raise RunnerError(f"task {task.id}: [environment] docker_image must be pinned by digest (never pulled)")
    if not image:
        done = subprocess.run(["docker", "build", "-q", str(task.path / "environment")], capture_output=True, text=True)
        if done.returncode:
            raise RunnerError(f"task {task.id}: docker build failed: {done.stderr.strip()[-2000:]}")
        image = done.stdout.strip().splitlines()[-1]
    wd = env.get("workdir") or subprocess.run(["docker", "image", "inspect", "-f", "{{.Config.WorkingDir}}", image],
                                              capture_output=True, text=True).stdout.strip()
    return image, wd if wd not in ("", "/") else attempt.WORKDIR


def grade(task: Task, image: str, d: Path) -> None:
    """Run the task's grader on the collected tree in a fresh container (no network) and keep reward.json."""
    buf, nonce, cmd = io.BytesIO(), uuid.uuid4().hex, task.grader.get("command") or DEFAULT_COMMAND
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(d / "tree" / "project", arcname="work")
        tar.add(task.path / "tests", arcname="task/tests")
    script = (f"mkdir -p /g/reward && cd /g/task && export FLIGHTDECK_WORKDIR=/g/work FLIGHTDECK_REWARD_DIR=/g/reward"
              f" && {cmd}; rc=$?; echo; echo {nonce} $(cat /g/reward/reward.json 2>/dev/null); exit $rc")
    started = time.monotonic()
    try:
        out: dict[str, Any] = attempt.run_isolated(image, buf.getvalue(), script, timeout=float(
            (task.config.get("verifier") or {}).get("timeout_sec") or 600))
    except (attempt.Stopped, OSError, ValueError) as e:
        out = {"exit_code": None, "error": f"grader did not finish: {e}"}
    marks = [x[len(nonce):].strip() for x in out.get("stdout", "").splitlines() if x.startswith(nonce)]
    try:
        reward = json.loads(marks[-1]) if marks else None
    except ValueError:
        reward = None
    if isinstance(reward, dict):
        (d / "reward.json").write_text(json.dumps(reward) + "\n")
    (d / "grading").mkdir(exist_ok=True)
    (d / "grading" / "hidden-tests.json").write_text(json.dumps(
        {**out, "command": cmd, "digest": task.files_digest, "seconds": round(time.monotonic() - started, 3),
         "reward": reward if isinstance(reward, dict) else None}, indent=1, sort_keys=True))


class LocalDockerBackend:
    """Runs a plan's trials one after another in local Docker and writes them into the data plane at once. A run set's
    evidence stays under `<data>/raw/<run-set>/<task>/<variant>/<trial>/`; `collect` rebuilds the rows from it."""

    def __init__(self, out: str | None, cancel: threading.Event | None = None) -> None:
        if not out:
            raise RunnerError("the local backend writes a data plane: pass --data or set FLIGHTDECK_DATA_URI")
        self.out, self.cancel = out, cancel

    def submit(self, plan: TrialPlan) -> str:
        if refused := [r for t in plan.tasks if (r := refusal(t))]:
            raise RunnerError("\n".join(refused))
        picked = {(t.id, k): pick_driver(t, k, v) for t in plan.tasks for k, v in plan.variants.items()}
        run_set = f"local-{plan.suite}-{plan.suite_run}-{uuid.uuid4().hex[:6]}"
        root = Path(self.out) / "raw" / run_set
        root.mkdir(parents=True)
        (root / "plan.json").write_text(json.dumps({"suite": plan.suite, "tasks": [t.id for t in plan.tasks],
                                                    "variants": plan.variants, "n": plan.n, **cache.digests(plan)},
                                                   indent=1))
        for task in plan.tasks:
            image, wd = build(task)
            for name in plan.variants:
                for n in range(1, plan.n + 1):
                    self.trial(task, image, wd, name, n, picked[task.id, name], root / task.id / name / str(n))
        self.collect(run_set)
        return run_set

    def trial(self, task: Task, image: str, wd: str, variant: str, n: int, driver: drivers.Deterministic,
              d: Path) -> None:
        timeout = float((task.config.get("agent") or {}).get("timeout_sec") or 1800)
        planned = {"scenario": task.id, "arm": variant, "attempt": n, "image": image, "workdir": wd,
                   "limits": {"timeout_minutes": timeout / 60}}
        result = attempt.run_attempt(planned, run_dir=d, fixture=None, steps=driver.steps(planned),
                                     install=driver.install(planned), cancel=self.cancel, driver=driver)
        if (d / "tree" / "project").is_dir():
            grade(task, image, d)
        git_observer.retain_git_observation(d, expected_anchor=result.get("git_anchor"))
        (d / "attempt.json").write_text(json.dumps(result, indent=1, sort_keys=True))
        (d / evidence.MANIFEST).write_text(json.dumps(evidence.manifest_of(d), indent=1, sort_keys=True))

    def status(self, run_set: str) -> RunSetStatus:
        root = Path(self.out) / "raw" / run_set
        if not (root / "plan.json").is_file():
            raise RunnerError(f"no local run set {run_set} under {self.out}/raw")
        plan, counts = json.loads((root / "plan.json").read_text()), {}
        for a in root.glob("*/*/*/attempt.json"):
            o = json.loads(a.read_text())["outcome"]
            counts[o] = counts.get(o, 0) + 1
        expected = len(plan["tasks"]) * len(plan["variants"]) * plan["n"]
        state = "succeeded" if sum(counts.values()) >= expected else "running"
        return RunSetStatus(run_set, state, counts, {run_set: state}, [], [f"{expected} trial(s) planned"])

    def collect(self, run_set: str) -> Path:
        root = Path(self.out) / "raw" / run_set
        tables: dict[str, list[Row]] = {k: [] for k in ("runs", "grades", "spans", "events", "test_cases")}
        for a in sorted(root.glob("*/*/*/attempt.json")):
            task, variant, n = a.parent.relative_to(root).parts
            for k, v in rows(run_set, a.parent, task, variant, int(n)).items():
                tables[k] += v
        if not tables["runs"]:
            raise RunnerError(f"no local trials of {run_set} under {self.out}/raw")
        if "task_digests" in (plan := json.loads((root / "plan.json").read_text())):
            cache.stamp(tables["runs"], plan)
        ingest.write_unit(tables, self.out, run_set)
        return Path(self.out)


# ---------------------------------------------------------------------------------------------------- rows
def totals(text: str) -> dict[str, Any]:
    """Counts from unittest's or pytest's summary; `complete` is false when there is none."""
    if m := re.search(r"^Ran (\d+) tests? in ", text, re.M):
        c = {k: int(v) for k, v in re.findall(r"(failures|errors|skipped)=(\d+)", text)}
        f, e, s = c.get("failures", 0), c.get("errors", 0), c.get("skipped", 0)
        return {"total": int(m[1]), "passed": int(m[1]) - f - e - s, "failed": f, "errors": e, "skipped": s,
                "complete": True}
    c = {k.rstrip("s") if k.startswith("error") else k: int(v)
         for v, k in re.findall(r"(\d+) (passed|failed|errors?|skipped)\b", text)}
    return {"total": sum(c.values()), "passed": c.get("passed", 0), "failed": c.get("failed", 0),
            "errors": c.get("error", 0), "skipped": c.get("skipped", 0), "complete": True} if c else {"complete": False}


def call(step: dict) -> tuple[str, str, str, bool, str | None]:
    """A step's command as one tool call: a file write is an edit, anything else a shell command."""
    cmd, ok = step["command"], step["exit_code"] == 0
    if cmd[1:3] == ["-c", drivers.WRITER]:
        return "Write", "edit", f"write {cmd[3]}", ok, None if cmd[3].startswith("/") else cmd[3]
    text = cmd[2] if len(cmd) == 3 and cmd[:2] in (["sh", "-c"], ["bash", "-c"]) else shlex.join(cmd)
    return "exec", "shell", text[:2000], ok, None


def rows(run_set: str, d: Path, task: str, variant: str, n: int) -> dict[str, list[Row]]:
    """One trial's evidence as data-plane rows. Test runs come only from commands the controller ran for a
    deterministic driver (trusted: the agent can't write them)."""
    a = json.loads((d / "attempt.json").read_text())
    load = lambda p: json.loads((d / p).read_text()) if (d / p).is_file() else {}  # noqa: E731
    git, graded = load("grading/git.json"), load("grading/hidden-tests.json")
    steps = [json.loads(p.read_text()) for p in sorted((d / "steps").glob("*.json"))]
    end = (d / "attempt.json").stat().st_mtime_ns
    t0 = steps[0]["start_ns"] if steps else end
    rid, key = f"{run_set}/{task}/{variant}/{n}", f"{task}/{variant}/{n}"
    trace = hashlib.sha256(rid.encode()).hexdigest()[:32]
    sid = lambda i: hashlib.sha256(f"{rid}#{i}".encode()).hexdigest()[:16]  # noqa: E731
    base = {"run_id": rid, "source": "local", "dt": datetime.fromtimestamp(t0 / 1e9, UTC).strftime("%Y-%m-%d")}
    span = {**base, "trace_id": trace, "job_id": rid, "environment": "local"}
    spans: list[Row] = [{**span, "span_id": sid(0), "kind": "job", "name": f"local {key}", "start_ns": t0,
                         "end_ns": end, "seq": 0}]
    events: list[Row] = []
    tests: list[Row] = []
    commits = [c for c in git.get("commits") or [] if not c.get("anchor")] if git.get("status") == "available" else []
    real, placed, seq = [c["hash"] for c in commits], set(), 0
    for s in steps:
        name, kind, inp, ok, path = call(s)
        seq += 1
        ops = shell_ops(inp) if kind == "shell" else []
        spans.append({**span, "span_id": sid(seq), "parent_span_id": sid(0), "kind": "tool.call",
                      "name": f"execute_tool {name}", "start_ns": s["start_ns"], "end_ns": s["end_ns"], "seq": seq,
                      "tool_kind": kind, "tool_name": name, "tool_input": inp, "tool_ok": ok,
                      "shell_ops": ops or None, "file_repo_path": path})
        if "test" in ops:
            tests.append({**base, "trace_id": trace, "test_run_id": sid(seq), "status": "pass" if ok else "fail",
                          "run_kind": "local.controller", "trusted": True, "exit_code": s["exit_code"],
                          "time_ns": s["end_ns"], **totals(s["stdout"] + "\n" + s["stderr"])})
        # a commit in a step that also tested goes after the test unless the command committed first
        early = "git.commit" in ops and "test" in ops and ops.index("git.commit") < ops.index("test")
        for h in [h for h in s.get("commits") or [] if h in real and h not in placed]:
            placed.add(h)
            seq += 1
            events.append({**base, "trace_id": trace, "span_id": sid(0), "span_kind": "job", "name": "git.commit",
                           "time_ns": (s["start_ns"] if early else s["end_ns"]) + seq, "seq": seq,
                           "attrs": json.dumps({"vcs.ref.head.revision": h})})
    for h in [h for h in real if h not in placed]:  # seen only by the observer
        seq += 1
        events.append({**base, "trace_id": trace, "span_id": sid(0), "span_kind": "job", "name": "git.commit",
                       "time_ns": end + seq, "seq": seq, "attrs": json.dumps({"vcs.ref.head.revision": h})})
    outcome, cls = OUTCOMES.get(a["outcome"], ("failed", None))
    run = {**base, "job_id": rid, "turn": 1, "experiment_id": run_set, "trial_key": key, "task_id": task,
           "variant": variant, "trial": n, "environment": "local", "harness": "deterministic", "outcome": outcome,
           "reason": a.get("limit") or a.get("detail"), "outcome_class": cls,
           "infra_reason": f"{a.get('stage')}: {a.get('detail')}" if cls else None,
           "environment_digest": load("inputs.json").get("planned", {}).get("image"),
           "started_at": datetime.fromtimestamp(t0 / 1e9, UTC), "finished_at": datetime.fromtimestamp(end / 1e9, UTC),
           "diff_files": sorted({p for c in commits for p in c["paths"]} | set(git.get("dirty_paths") or [])),
           "truncated": a["outcome"] != "completed" or git.get("status") != "available"}
    grades = [{**base, "experiment_id": run_set, "trial_key": key, "command": graded.get("command"),
               "exit_code": graded.get("exit_code"), "applied": True, "seconds": graded.get("seconds"),
               "error": graded.get("error"), "data": json.dumps(graded["reward"]) if graded.get("reward") else None,
               "grader_digest": graded.get("digest")}] if graded else []
    return {"runs": [run], "grades": grades, "spans": spans, "events": events, "test_cases": tests}
