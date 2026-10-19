#!/usr/bin/env python3
"""Write a synthetic `hangar experiment export` directory: the fixture experiment for tests and the README's end-to-end.

Built from the synthetic trace and manifest in `tests/fixtures/hangar/` (ADR-0002: no team data). 12 tasks x 2 variants
(control, candidate; described in the index's pins) x 3 trials, seeded, with the candidate a little better and
cheaper, plus one of each case a report must handle: an infrastructure failure hangar retried (hangar#166), a
cancelled trial, a drifted trial, a trial still running, a truncated trace and a task that failed hangar's base check.
Also writes a `decision.yaml`, committed (in a git repo in DIR) before the first trial finished: pre-registered.

    python scripts/fixture_export.py DIR
"""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hangar"
EXP = "job-expdemo"
CREATED = 1760600000.0
TASKS = [f"t{i:02d}" for i in range(1, 13)]
DIGEST = {"control": "sha256:" + "1" * 64, "candidate": "sha256:" + "4" * 64}
CONFIG = {"control": "sha256:" + "2" * 64, "candidate": "sha256:" + "5" * 64}


def _attr(span: dict, key: str, value: dict) -> None:
    span["attributes"] = [a for a in span["attributes"] if a["key"] != key] + [{"key": key, "value": value}]


def _trace(job: str, run_id: str, cost: float, tool_calls: int, truncated: bool) -> dict:
    otlp = copy.deepcopy(json.loads((FIX / "trace_job.json").read_text()))
    rs = otlp["resourceSpans"][0]
    _attr(rs["resource"], "hangar.job.id", {"stringValue": job})
    _attr(rs["resource"], "hangar.session.id", {"stringValue": "ses-" + job})
    if truncated:
        _attr(rs["resource"], "hangar.export.truncated", {"boolValue": True})
    spans, kept = rs["scopeSpans"][0]["spans"], []
    for s in spans:
        kind = next((a["value"]["stringValue"] for a in s["attributes"] if a["key"] == "hangar.kind"), None)
        if kind == "turn":
            _attr(s, "hangar.run.id", {"stringValue": run_id})
            _attr(s, "hangar.cost_usd", {"doubleValue": cost})
        if kind == "tool.call":
            if tool_calls <= 0:
                continue
            tool_calls -= 1
        kept.append(s)
    rs["scopeSpans"][0]["spans"] = kept
    return otlp


def _manifest(variant: str, job: str, run_id: str) -> dict:
    m = json.loads((FIX / "manifest_turn.json").read_text())
    m["digest"], m["config_digest"] = DIGEST[variant], CONFIG[variant]
    m["subject"].update(session=job, session_id="ses-" + job, run_id=run_id, job=job)
    return m


def build(out: Path, seed: int = 7) -> dict:
    """Write the export under `out` and return its index."""
    rng = random.Random(seed)
    index = json.loads((FIX / "experiment_index.json").read_text())
    template = index["trials"][0]
    index.update(id=EXP, name="skills-ab-demo", created_at=CREATED, spec={"name": "skills-ab-demo", "trials": 3})
    index["pins"]["tasks"] = {t: {"repo": "https://github.com/example/app.git", "base_branch": "main",
                                  "base_sha": f"{i:x}" * 40, "issue": None} for i, t in enumerate(TASKS, 1)}
    base = {t: 1.0 if t == "t01" else 0.0 if t == "t02" else rng.uniform(0.2, 0.7) for t in TASKS}
    trials, n = [], 0
    for task in TASKS:
        for variant in ("control", "candidate"):
            for trial in (1, 2, 3):
                n += 1
                key, job = f"{task}/{variant}/{trial}", f"job-{task}-{variant}-{trial}"
                run_id = f"run-{task}-{variant}-{trial}"
                lift = 0.25 if variant == "candidate" and base[task] not in (0.0, 1.0) else 0.0
                ok = rng.random() < base[task] + lift
                cost = round(rng.uniform(0.3, 0.5) * (0.8 if variant == "candidate" else 1.0), 3)
                t = copy.deepcopy(template)
                t.update(key=key, task=task, variant=variant, trial=trial, job=job, session="ses-" + job,
                         state="done", outcome="succeeded", reason=None, started_at=CREATED + 100 * n,
                         finished_at=CREATED + 100 * n + rng.randint(60, 300), manifests=[DIGEST[variant]],
                         config_digest=CONFIG[variant], drift=[], task_invalid=task == "t08", contaminated=False,
                         trust="isolated", stored=["trace.json", "manifest.json"], outcome_class="agent",
                         infra_reason=None, excluded=False, attempt=1, retry_of=None)
                t["verify"] = {**t["verify"], "exit_code": 0 if ok else 1, "passed": ok}
                t["usage"] = {**t["usage"], "cost_usd": cost}
                t["grade"] = {**t["grade"], "exit_code": 0 if ok else 1, "data": {"reward": int(ok)}}
                retries = []
                if key == "t03/candidate/3":  # infrastructure ended it: hangar excludes it and runs attempt 2
                    retries.append(retry := copy.deepcopy(t))
                    retry.update(attempt=2, retry_of=job, job=job + "-2", finished_at=t["finished_at"] + 400)
                    t.update(outcome="failed", reason="sandbox could not be created", grade=None, stored=[],
                             outcome_class="infra_error", infra_reason="sandbox_create", excluded=True)
                if key == "t04/control/3":
                    t.update(outcome="cancelled", reason="cancelled by dev-a", grade=None, outcome_class="cancelled")
                if key == "t05/candidate/2":
                    t.update(drift=["harness drift: its harness configuration differs"],
                             config_digest=CONFIG["control"])
                if key == "t06/candidate/3":
                    t.update(state="running", outcome=None, finished_at=None, grade=None, usage=None, stored=[])
                for x in [t, *retries]:
                    q = f"?attempt={x['attempt']}" if x["attempt"] > 1 or x["excluded"] else ""
                    link, ref = f"/api/experiments/{EXP}/trials/{key}", key + q.replace("?attempt=", "~")
                    x["links"] = {"job": f"/api/jobs/{x['job']}", "manifest": f"{link}/manifest{q}" if x["stored"]
                                  else None, "trace": f"{link}/trace{q}" if x["stored"] else None}
                    if x["stored"]:
                        d = out / "trials" / ref.replace("/", "__")
                        d.mkdir(parents=True, exist_ok=True)
                        calls = 2 if variant == "candidate" and trial != 3 else 3
                        trace = _trace(x["job"], run_id, cost, calls, truncated=key == "t07/control/1")
                        (d / "trace.json").write_text(json.dumps(trace, indent=1))
                        (d / "manifest.json").write_text(json.dumps(_manifest(variant, x["job"], run_id), indent=1))
                    trials.append(x)
    index["trials"] = trials
    index["finished_at"] = max(t["finished_at"] or 0 for t in trials)
    index["counts"] = {s: sum(1 for t in trials if t["state"] == s) for s in {t["state"] for t in trials}}
    index.update(state="running", task_checks={"t08": {"state": "done", "base_sha": "8" * 40, "invalid": True}})
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.json").write_text(json.dumps(index, indent=1))
    decision = out / "decision.yaml"
    decision.write_text("# pre-registered before the first trial\nmetric: resolved\ndirection: higher\n"
                        "margin: -0.05\nmin_tasks: 10\n")
    os.utime(decision, (CREATED, CREATED))
    when = {"GIT_AUTHOR_DATE": f"@{int(CREATED)} +0000", "GIT_COMMITTER_DATE": f"@{int(CREATED)} +0000"}
    git = ["git", "-C", str(out), "-c", "user.name=fixture", "-c", "user.email=fixture@example.com"]
    for args in (["init", "-q"], ["add", "decision.yaml"], ["commit", "-q", "-m", "pre-register the decision"]):
        subprocess.run(git + args, check=True, env={**os.environ, **when})
    return index


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
    print(f"wrote {sys.argv[1]}/index.json, trials/ and decision.yaml")
