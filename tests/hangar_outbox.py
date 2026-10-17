"""A synthetic hangar outbox (`hangar.run/v1`, hangar docs/api/outbox.md) for the compactor and metrics tests.

Objects follow hangar's documented layout and schemas (run.json is checked against the vendored run.schema.json);
names, repos and people are made up.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

FIX = Path(__file__).resolve().parent / "fixtures" / "hangar"


def kv(attrs: dict[str, Any]) -> list[dict]:
    def val(v: Any) -> dict:
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        return {"stringValue": v}

    return [{"key": k, "value": val(v)} for k, v in attrs.items()]


def ts(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()


def trace(session: str, run_id: str, start: float, steer: bool = False) -> dict:
    ns = int(start * 1e9)
    turn = {"traceId": "a" * 32, "spanId": "1" * 16, "name": "invoke_agent", "startTimeUnixNano": str(ns),
            "endTimeUnixNano": str(ns + 600 * 10**9),
            "attributes": kv({"hangar.kind": "turn", "hangar.run.id": run_id, "hangar.turn.number": 1,
                              "hangar.turn.outcome": "succeeded", "hangar.seq": 0}),
            "events": [{"name": "steer", "timeUnixNano": str(ns + 60 * 10**9), "attributes": kv({"hangar.text": "x"})}]
            if steer else []}
    tool = {"traceId": "a" * 32, "spanId": "2" * 16, "parentSpanId": "1" * 16, "name": "execute_tool Bash",
            "startTimeUnixNano": str(ns + 10**9), "endTimeUnixNano": str(ns + 2 * 10**9),
            "attributes": kv({"hangar.kind": "tool", "hangar.seq": 1, "gen_ai.tool.name": "Bash",
                              "hangar.tool.kind": "shell", "hangar.tool.output": "token ghp_" + "x" * 36})}
    res = kv({"hangar.trace.schema": "hangar.trace/v1", "hangar.session.id": session, "hangar.person": "ana",
              "hangar.environment": "py"})
    return {"resourceSpans": [{"resource": {"attributes": res}, "scopeSpans": [{"spans": [turn, tool]}]}]}


def run_doc(session: str, run_id: str, day: str, **kw: Any) -> dict:
    doc = {"schema": "hangar.run/v1", "source": "job", "run_id": run_id, "session_id": session, "turn": 1,
           "job_id": kw.pop("job", None), "job_source": "github", "job_turn": 1, "person": "ana", "repo": "acme/app",
           "environment": "py", "harness": "claude-code", "model": "claude-x-1", "pinned": False,
           "outcome": "succeeded", "outcome_class": None, "job_state": "delivering", "started_at": ts(day, 11),
           "finished_at": ts(day), "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 1.5},
           "verify": {"passed": True, "trusted": True}, "tests": [], "steers": {"n": 0, "by_class": {}},
           "approvals": 0, "questions": 0, "untrusted": False, "tainted": False, "truncated": False,
           "objects": ["manifest.json", "trace.otlp.json", "tests.json"], "withheld": [], "expects": [],
           "captured_at": ts(day, 13)}
    return doc | kw


def write_run(root: Path, day: str, session: str, run_id: str, complete: bool = True, grade: bool = False,
              **kw: Any) -> Path:
    """One run directory; without `complete` its run.json (the completion marker) is left out."""
    d = root / "v1" / "runs" / day / f"{session}.{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((FIX / "manifest_turn.json").read_text(encoding="utf-8"))
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "trace.otlp.json").write_text(json.dumps(trace(session, run_id, ts(day, 11), kw.get("steers") is not None)))
    test_run = {"name": "test.run", "timeUnixNano": str(int(ts(day, 11) * 1e9) + 5),
                "attributes": kv({"hangar.test.run.id": "tr1", "test.suite.name": "pytest", "hangar.test.total": 3,
                                  "hangar.test.passed": 3, "hangar.test.run.trusted": True})}
    tests = {"schema": "hangar.tests/v1", "run_id": run_id, "session_id": session, "runs": [], "events": [test_run]}
    (d / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
    (d / "patch.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
    if grade:
        g = {"schema": "hangar.grade/v1", "experiment_id": "exp1", "trial_key": "t/a/1", "run_id": run_id,
             "command": "pytest", "exit_code": 0, "applied": True, "seconds": 2.0, "data": {"reward": 1}}
        (d / "grade.json").write_text(json.dumps(g), encoding="utf-8")
    if complete:
        (d / "run.json").write_text(json.dumps(run_doc(session, run_id, day, **kw)), encoding="utf-8")
    return d


def write_event(root: Path, day: str, job: str, kind: str, hour: int = 12, **data: Any) -> None:
    n = int(job.removeprefix("job-"))
    pr = {"url": f"https://github.com/acme/app/pull/{n}", "number": n}
    e = {"schema": "hangar.job_event/v1", "kind": kind, "ts": ts(day, hour), "job_id": job, "job_source": "github",
         "source": "job", "repo": "acme/app", "person": data.pop("person", "ana"), "environment": "py",
         "session_id": f"ses-{job}", "run_ids": data.pop("run_ids", ["run-00000001"]), "pr": pr, "untrusted": False,
         "data": data}
    d = root / "v1" / "jobs" / day / job / "events"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{int(ts(day, hour) * 1000)}-{kind}.json").write_text(json.dumps(e), encoding="utf-8")
