"""Process metrics and step labels (src/flightdeck/metrics/process.sql) against hangar evals/semver's metrics.py and
classify.rule() (tests/legacy_semver.py), on one synthetic semver trial in both shapes. Regenerate the trace fixture
with `python tests/test_process_metrics.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from legacy_semver import metrics, rule

from flightdeck.dataplane.duck import connect
from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.dataplane.schema import write_partitioned
from flightdeck.ported.hangar_traces import shell_ops, tool_kind

FIXTURE = Path(__file__).parent / "fixtures" / "hangar" / "trace_semver.json"
KEY = "/opt/hangar/harness/pi/node_modules/semver/classes/range.js"
# A pi trial of tasks/smoke/semver: (tool name as pi gives it, input, output, ok).
STEPS = [
    ("todo_write", "plan: parse, compare, ranges, cli", "ok", True),
    ("bash", "ls -la", "total 0", True),
    ("bash", "git status", "On branch main", True),
    ("read", KEY, "class Range {", True),
    ("write", "/workspace/semver/semver.py", "ok", True),
    ("write", "/workspace/semver/test_semver.py", "ok", True),
    ("bash", "python3 -m unittest", "FAILED (failures=2)", False),
    ("edit", "/workspace/semver/semver.py", "ok", True),
    ("bash", "python3 -m unittest", "OK", True),
    ("bash", "python3 semver.py sort 1.10.0 1.2.0", "1.2.0\n1.10.0", True),
    ("bash", "python3 -m unittest -v", "Traceback (most recent call last)", True),
    ("bash", "python3 -m unittest", "OK", True),
    ("edit", "/workspace/semver/semver.py", "ok", True),
    ("bash", "cd /workspace/semver && python3 -m unittest", "OK", True),
    ("grep", "def satisfies", "semver.py:88", True),
    ("bash", "cat nope.txt", "No such file", False),
    ("bash", "git add -A && git commit -qm 'semver'", "", True),
]
# Documented differences (docs/process-metrics.md#differences-from-hangars-kit): plan tools have their own label.
RELABEL = {"plan": "other"}


def _v(x: object) -> dict:
    if isinstance(x, bool):
        return {"boolValue": x}
    if isinstance(x, int):
        return {"intValue": str(x)}
    if isinstance(x, list):
        return {"arrayValue": {"values": [_v(y) for y in x]}}
    return {"stringValue": x}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _v(v)} for k, v in d.items() if v is not None]


def build(steps: list[tuple] = STEPS, run: str = "run-semver1") -> dict:
    """A one-turn `hangar.trace/v1` session export in hangar's documented shape (docs/api/traces.md)."""
    t0, tid = 1_760_300_000 * 10**9, "5e" * 16
    turn = {"traceId": tid, "spanId": "0000000000000001", "name": "invoke_agent pi", "kind": 1,
            "startTimeUnixNano": str(t0), "endTimeUnixNano": str(t0 + 412 * 10**9), "attributes": _attrs({
                "hangar.kind": "turn", "hangar.run.id": run, "hangar.turn.number": 1, "hangar.session.id": "ses-semver",
                "hangar.harness": "pi", "hangar.turn.outcome": "exited", "gen_ai.response.model": "gemini-3.8-flash",
                "gen_ai.usage.input_tokens": 182_000, "gen_ai.usage.output_tokens": 14_000,
                "gen_ai.usage.cache_read.input_tokens": 120_000, "hangar.cost_source": "prices"}) + [
                    {"key": "hangar.cost_usd", "value": {"doubleValue": 0.19}}],
            "events": [{"timeUnixNano": str(t0 + 410 * 10**9), "name": "test.run", "attributes": _attrs({
                "test.suite.name": "bash tests/test.sh", "test.suite.run.status": "success",
                "hangar.test.run.kind": "grader", "hangar.test.run.trusted": True, "hangar.test.total": 116,
                "hangar.test.passed": 116, "hangar.test.failed": 0, "hangar.test.errors": 0,
                "hangar.test.complete": True})}]}
    spans = [turn]
    for n, (name, inp, out, ok) in enumerate(steps):
        kind = tool_kind(name)
        t = t0 + (n + 1) * 20 * 10**9
        spans.append({"traceId": tid, "spanId": f"{n + 2:016x}", "parentSpanId": turn["spanId"],
                      "name": f"execute_tool {name}", "kind": 1, "startTimeUnixNano": str(t),
                      "endTimeUnixNano": str(t + 10**9), "attributes": _attrs({
                          "hangar.kind": "tool.call", "gen_ai.tool.name": name, "hangar.tool.kind": kind,
                          "hangar.tool.input": inp, "hangar.tool.output": out, "hangar.tool.ok": ok,
                          "hangar.seq": 2 * n + 1, "hangar.seq.end": 2 * n + 2,
                          "hangar.shell.ops": (shell_ops(inp) or None) if kind == "shell" else None})})
    res = {"service.name": "hangar", "hangar.trace.schema": "hangar.trace/v1", "hangar.export.scope": "session",
           "hangar.session.id": "ses-semver", "hangar.environment": "bare", "hangar.person": "dev-a"}
    return {"resourceSpans": [{"resource": {"attributes": _attrs(res)},
                               "scopeSpans": [{"scope": {"name": "hangar.trace", "version": "1"}, "spans": spans}]}]}


def plane(tmp_path: Path, otlp: dict) -> Path:
    for name, rows in flatten_trace(otlp).items():
        write_partitioned(name, rows, str(tmp_path))
    return tmp_path


def rows(con, sql: str) -> list[dict]:  # noqa: ANN001
    rel = con.sql(sql)
    return [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]


def test_fixture_is_current() -> None:
    assert json.loads(FIXTURE.read_text()) == build()


def test_process_metrics_match_hangars_kit(tmp_path: Path) -> None:
    con = connect(str(plane(tmp_path, json.loads(FIXTURE.read_text()))))
    (got,) = rows(con, "from process_metrics")
    legacy = metrics([{"kind": "tool", "name": n, "args": i, "result": o, "error": not ok} for n, i, o, ok in STEPS])
    by_label: dict[str, int] = {}
    for label, n in got["by_label"].items():
        key = RELABEL.get(str(label), str(label))
        by_label[key] = by_label.get(key, 0) + n
    assert {**{k: got[k] for k in legacy if k != "by_label"}, "by_label": by_label} == legacy
    assert (got["tool_calls_before_first_edit"], got["fix_loops"], got["test_runs"]) == (4, 2, 5)
    assert (got["failing_test_runs"], got["answer_key_reads"], got["reference_lookups"]) == (2, 1, 1)
    assert (got["trusted_test_runs"], got["failing_trusted_test_runs"]) == (1, 0)
    assert (got["input_tokens"], got["cost_usd"], got["wall_s"]) == (182_000, 0.19, 412)


# classify.rule()'s cases: (tool name, input). Where the labels differ on purpose, the new label is given.
CASES = [
    ("web_search", "node-semver caret"), ("search_web", "semver spec"), ("read_url_content", "https://semver.org"),
    ("bash", f"cat {KEY}"), ("bash", "node -e \"require('semver')\""), ("read", KEY),
    ("bash", "git status"), ("bash", "git log --oneline"), ("bash", "git diff"), ("bash", "git show HEAD"),
    ("bash", "git add -A && git commit -m x"), ("run_command", "git commit -qm wip"),
    ("bash", "python3 -m unittest"), ("bash", "python3 -m pytest -q"), ("bash", "pytest -x"),
    ("run_command", "timeout 60 python3 -m unittest -v"),
    ("write", "/workspace/semver/semver.py"), ("edit", "semver.py"), ("write_to_file", "semver.py"),
    ("replace_file_content", "semver.py"), ("bash", "cat > semver.py <<'EOF'"), ("bash", "echo x | tee out.txt"),
    ("read", "semver.py"), ("view_file", "semver.py"), ("list_dir", "/workspace"), ("find_by_name", "*.py"),
    ("grep_search", "def parse"), ("codebase_search", "Range"), ("bash", "ls"), ("bash", "head -5 semver.py"),
    ("bash", "grep -n parse semver.py"), ("bash", "find . -name '*.py'"), ("bash", "sed -n 1,20p semver.py"),
    ("bash", "python3 semver.py sort 1.0.0 0.9.0"), ("bash", "python3 -c 'import semver'"),
    ("bash", "echo done"), ("bash", "mkdir -p x"),
]
DIFFERENT = {  # (tool name, input): the new label, documented in docs/process-metrics.md
    ("bash", "pip install pytest"): "other",  # not a test run: shell_ops has no `test`
    ("write", "/workspace/semver/test_pytest_cfg.py"): "edit",  # an edit whose path names pytest is an edit
    ("todo_write", "plan"): "plan",  # plan tools have their own label
}


def test_rule_labeller_reproduces_classify_rule(tmp_path: Path) -> None:
    allcases = CASES + list(DIFFERENT)
    con = connect(str(plane(tmp_path, build([(n, i, "", True) for n, i in allcases]))))
    got = [r["label"] for r in rows(con, "select label from step_labels order by idx")]
    want = [DIFFERENT.get((n, i)) or rule({"name": n, "args": i}) for n, i in allcases]
    assert got == want
    assert [rule({"name": n, "args": i}) for n, i in DIFFERENT] == ["test", "test", "other"]


def test_truncated_runs_are_left_out(tmp_path: Path) -> None:
    otlp = build()
    otlp["resourceSpans"][0]["resource"]["attributes"] += _attrs({"hangar.export.truncated": True})
    assert rows(connect(str(plane(tmp_path, otlp))), "from process_metrics") == []


def test_decision_1_is_not_called() -> None:
    """classify.py's model labeller was not ported: no flightdeck code reaches OpenRouter (ADR-0001)."""
    src = Path(__file__).parents[1] / "src" / "flightdeck"
    calls = re.compile(r"openrouter\.ai/api|OPENROUTER_API_KEY|microsoft-decision", re.I)
    assert not [p for p in src.rglob("*") if p.suffix in (".py", ".sql") and calls.search(p.read_text("utf-8"))]


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(build(), indent=1) + "\n")
