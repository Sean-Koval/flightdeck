"""Synthetic `hangar.trace/v1` exports for spec tests, built from short step lists in hangar's documented shape."""

from __future__ import annotations

import hashlib
import random
from typing import Any

T0 = 1_760_700_000


def _v(x: Any) -> dict:
    if isinstance(x, bool):
        return {"boolValue": x}
    if isinstance(x, int):
        return {"intValue": str(x)}
    if isinstance(x, list):
        return {"arrayValue": {"values": [_v(y) for y in x]}}
    return {"stringValue": x}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _v(v)} for k, v in d.items() if v is not None]


def _id(*parts: Any, n: int = 16) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:n]


def trace(steps: list[tuple], job: str | None = "job-s1", session: str = "ses-s1", diff: list[str] | None = None,
          truncated: bool = False, repo: str = "https://github.com/example/app.git", runs: str = "run") -> dict:
    """Steps, in order (each one second later, unless a step gives `t`):

    ("turn",) starts the next turn; ("tool", kind, input, ops); ("approval", ops, status); ("file", repo_path, op);
    ("event", name, attrs) on the job span (or the turn when there is no job); ("test", trusted, total) a test.run;
    ("steer",) an event without hangar.seq. A trailing {"t": n, "noseq": True} dict overrides time or drops seq.
    """
    key = job or session
    tid = _id("hangar", key, n=32)
    root = {"traceId": tid, "spanId": _id(key, "root"), "name": "invoke_workflow hangar.job", "kind": 1,
            "startTimeUnixNano": str(T0 * 10**9), "endTimeUnixNano": str((T0 + 10_000) * 10**9), "events": [],
            "attributes": _attrs({"hangar.kind": "job", "hangar.repo": repo, "hangar.diff.files": diff})}
    spans, turns, seq = [root] if job else [], [], 0
    steps = steps if steps and steps[0] == ("turn",) else [("turn",), *steps]
    for n, step in enumerate(steps):
        last = step[-1]
        opts = last if isinstance(last, dict) and set(last) <= {"t", "noseq"} else {}
        t = (T0 + opts.get("t", n)) * 10**9
        kind = step[0]
        if kind == "turn":
            rid = f"{runs}-{len(turns) + 1}"
            turns.append({"traceId": tid, "spanId": _id(key, rid), "parentSpanId": root["spanId"] if job else None,
                          "name": "invoke_agent claude-code", "kind": 1, "startTimeUnixNano": str(t),
                          "endTimeUnixNano": str(t + 10**9), "events": [], "attributes": _attrs({
                              "hangar.kind": "turn", "hangar.run.id": rid, "hangar.turn.number": len(turns) + 1,
                              "hangar.session.id": session, "hangar.harness": "claude-code",
                              "hangar.turn.outcome": "exited"})})
            spans.append(turns[-1])
            continue
        cur = turns[-1]
        seq += 1
        s = None if opts.get("noseq") or kind == "steer" else seq
        if kind == "tool":
            spans.append({"traceId": tid, "spanId": _id(key, "tool", n), "parentSpanId": cur["spanId"],
                          "name": "execute_tool x", "kind": 1, "startTimeUnixNano": str(t), "endTimeUnixNano": str(t),
                          "attributes": _attrs({"hangar.kind": "tool.call", "hangar.tool.kind": step[1],
                                                "hangar.tool.input": step[2], "hangar.shell.ops": step[3] or None,
                                                "hangar.seq": s})})
        elif kind == "approval":
            spans.append({"traceId": tid, "spanId": _id(key, "ap", n), "parentSpanId": cur["spanId"],
                          "name": "approval Bash", "kind": 1, "startTimeUnixNano": str(t), "endTimeUnixNano": str(t),
                          "attributes": _attrs({"hangar.kind": "approval", "hangar.shell.ops": step[1],
                                                "hangar.approval.status": step[2], "hangar.seq": s})})
        elif kind in ("file", "steer"):
            a = {"hangar.kind": "file.change", "hangar.file.repo_path": step[1], "hangar.file.op": step[2],
                 "hangar.seq": s} if kind == "file" else {"hangar.kind": "steer", "hangar.text": "stop"}
            cur["events"].append({"timeUnixNano": str(t), "name": a["hangar.kind"], "attributes": _attrs(a)})
        else:
            on = root if job else cur
            if kind == "test":
                name, a = "test.run", {"hangar.test.run.trusted": step[1], "hangar.test.total": step[2],
                                       "hangar.test.complete": True, "hangar.test.run.kind": "verify"}
            else:
                name, a = step[1], step[2] if len(step) > 2 and step[2] is not opts else {}
            ev = {"timeUnixNano": str(t), "name": name, "attributes": _attrs({"hangar.kind": name, **a})}
            on["events"].append(ev)
    res = {"hangar.trace.schema": "hangar.trace/v1", "hangar.job.id": job, "hangar.session.id": session,
           "hangar.export.truncated": truncated or None}
    return {"resourceSpans": [{"resource": {"attributes": _attrs(res)},
                               "scopeSpans": [{"scope": {"name": "hangar.trace", "version": "1"}, "spans": spans}]}]}


def random_steps(rng: random.Random) -> list[tuple]:
    """A random step list: a mix of every item shape, with time ties and missing seqs."""
    out: list[tuple] = []
    for _ in range(rng.randint(0, 14)):
        opts = {"t": rng.randint(0, 6)} if rng.random() < 0.3 else {}
        if rng.random() < 0.1:
            opts["noseq"] = True
        r = rng.random()
        ops = rng.sample(["test", "git.commit", "git.push", "pr.open", "delete"], rng.randint(0, 2))
        if r < 0.08:
            out.append(("turn",))
        elif r < 0.45:
            kind = rng.choice(["shell", "shell", "edit", "plan", "read"])
            cmd = rng.choice(["pytest -q", "git push origin main", "rm -rf /tmp/x", "git commit -m x", "ls"])
            out.append(("tool", kind, cmd, ops if kind == "shell" else [], opts))
        elif r < 0.55:
            out.append(("approval", ops, rng.choice(["allowed", "denied"]), opts))
        elif r < 0.7:
            out.append(("file", rng.choice(["src/a.py", "docs/b.md", None]), rng.choice(["write", "delete"]), opts))
        elif r < 0.8:
            out.append(("test", rng.random() < 0.6, rng.choice([0, 3]), opts))
        elif r < 0.9:
            out.append(("event", rng.choice(["git.commit", "pr.open", "pr.merge"]),
                        {"hangar.pr.merged_by": rng.choice(["bot", "dev-a"])}))
        else:
            out.append(("steer", opts))
    return out


# The committed example traces (tests/fixtures/specs/), regenerated by `python tests/spec_traces.py`.
EXAMPLES: dict[str, dict] = {
    "job_pass": {"steps": [
        ("tool", "plan", "plan", []), ("tool", "edit", "src/app.py", []), ("file", "src/app.py", "update"),
        ("tool", "shell", "uv run pytest --collect-only -q", ["test"]), ("test", False, 0),
        ("approval", ["delete"], "allowed"), ("tool", "shell", "rm -rf build/old", ["delete"]),
        ("tool", "shell", "git commit -qam fix", ["git.commit"]),
        ("tool", "shell", "git push origin fix", ["git.push"]),
        ("event", "verify", {"hangar.verify.phase": "after_turn", "hangar.verify.passed": True}), ("test", True, 42),
        ("event", "git.commit", {}), ("event", "pr.open", {"hangar.pr.number": 7})], "diff": ["src/app.py"]},
    "job_fail": {"steps": [
        ("tool", "edit", "/etc/hosts", []), ("file", None, "write"),
        ("tool", "shell", "uv run pytest --collect-only -q", ["test"]), ("test", False, 0),
        ("tool", "shell", "rm -rf /var/lib/app", ["delete"]),
        ("tool", "shell", "git commit -qam wip && git push origin main", ["git.commit", "git.push"]),
        ("event", "git.commit", {}), ("event", "pr.open", {"hangar.pr.number": 8})], "diff": ["src/app.py"]},
}


def example(name: str) -> dict:
    e = EXAMPLES[name]
    return trace(e["steps"], job=f"job-{name}", session=f"ses-{name}", diff=e["diff"])


if __name__ == "__main__":
    import json
    from pathlib import Path

    for name in EXAMPLES:
        path = Path(__file__).parent / "fixtures" / "specs" / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(example(name), indent=1) + "\n")
