"""flightdeck.spec/v1: the language, its two evaluators and their agreement (docs/behavior-specs.md)."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from spec_traces import EXAMPLES, example, random_steps, trace
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.specs import lang

ROOT = Path(__file__).resolve().parent.parent
HANGAR = ROOT / "tests" / "fixtures" / "hangar"
HEAD = 'schema: flightdeck.spec/v1\nharness: "*"\n'


def both(spec: str | dict, otlp: dict) -> dict[str, str]:
    """Results from the Python evaluator, asserting the compiled SQL agrees."""
    s = spec if isinstance(spec, dict) else lang.load(HEAD + spec)[0]
    tables = flatten_trace(otlp)
    py = lang.evaluate(s, tables)
    assert lang.evaluate_sql(s, lang.connect_tables(tables)) == py, s
    return py


def one(spec: str, steps: list[tuple], **kw) -> str:
    """The single unit's result."""
    (r,) = both(spec, trace(steps, **kw)).values()
    return r


def test_hangar_reference_predicates_match_hangar() -> None:
    """hangar tests/test_interfaces.py::_behavior: all four true on the good export, all false on the bad one."""
    specs = lang.load((ROOT / "specs/examples/hangar-reference.yaml").read_text())
    assert [s["id"] for s in specs] == ["tests-before-commit", "edits-in-src", "ask-before-delete", "plan-edit-test-pr"]
    for name, want in (("good", "pass"), ("bad", "fail")):
        otlp = json.loads((HANGAR / f"trace_session_{name}.json").read_text())
        assert [both(s, otlp) for s in specs] == [{f"run-{1 if name == 'good' else 2}": want}] * 4


def _trusted_spec(extra: str = "") -> dict:
    return lang.load(HEAD + f"id: t\nscope: job\n{extra}assert:\n  before:\n    first: {{event: test.run}}\n"
                     "    then: {event: git.commit}\n")[0]


def test_trusted_test_rule() -> None:
    """The agent's `pytest --collect-only` (untrusted, total 0) is no proof of testing; hangar's verify run is."""
    job = json.loads((HANGAR / "trace_job.json").read_text())
    assert both(_trusted_spec(), job) == {"job-fixture01": "pass"}
    stripped = copy.deepcopy(job)
    for s in stripped["resourceSpans"][0]["scopeSpans"][0]["spans"]:
        s["events"] = [e for e in s.get("events", []) if not (
            e["name"] == "test.run" and any(a["value"].get("boolValue") for a in e["attributes"]
                                            if a["key"] == "hangar.test.run.trusted"))]
    assert both(_trusted_spec(), stripped) == {"job-fixture01": "fail"}
    loose = _trusted_spec("allow_untrusted: true\n")
    assert both(loose, stripped) == {"job-fixture01": "pass"}
    assert any("allow_untrusted" in w for w in lang.lint(loose))
    assert one("id: t\nscope: job\nassert: {eventually: {event: test.run}}", [("test", True, 0)]) == "fail"


def test_examples_pass_and_fail_on_committed_traces() -> None:
    specs = lang.load((ROOT / "specs/examples/team-default.yaml").read_text())
    for name in EXAMPLES:
        path = ROOT / "tests/fixtures/specs" / f"{name}.json"
        assert json.loads(path.read_text()) == example(name), "regenerate: python tests/spec_traces.py"
        want = name.removeprefix("job_")
        assert {r for s in specs for r in both(s, example(name)).values()} == {want}


def test_never_eventually_count() -> None:
    push = [("tool", "shell", "git push origin main", ["git.push"])]
    assert one("id: a\nassert: {never: {tool: {kind: shell, ops: [git.push]}}}", push) == "fail"
    master = "id: a\nassert: {never: {tool: {ops: [git.push]}, where: {input: {regex: '\\bmaster\\b'}}}}"
    assert one(master, push) == "pass"
    assert one("id: a\nassert: {eventually: {tool: {kind: shell}}}", push) == "pass"
    assert one("id: a\nassert: {eventually: {tool: {kind: edit}}}", push) == "fail"
    assert one("id: a\nassert: {count: {match: {tool: {kind: shell}}, max: 1}}", push * 2) == "fail"
    assert one("id: a\nassert: {count: {match: {tool: {kind: shell}}, min: 2, max: 3}}", push * 2) == "pass"


def test_before_and_order() -> None:
    spec = "id: a\nassert: {before: {first: {tool: {kind: plan}}, then: {tool: {kind: edit}}}}"
    plan, edit = ("tool", "plan", "p", []), ("tool", "edit", "e", [])
    assert one(spec, [plan, edit]) == "pass"
    assert one(spec, [edit, plan]) == "fail"
    assert one(spec, [plan]) == "not_applicable"  # nothing to precede
    assert one(spec, [edit]) == "fail"
    # without hangar.seq on one side, order falls back to time (traces.md 'Order')
    assert one(spec, [(*plan, {"t": 9, "noseq": True}), (*edit, {"t": 5})]) == "fail"
    order = "id: a\nscope: job\nassert: {order: [{tool: {kind: plan}}, {tool: {kind: edit}}, {event: pr.open}]}"
    assert one(order, [plan, edit, ("event", "pr.open", {})]) == "pass"
    assert one(order, [plan, edit]) == "fail"


def test_each_requires_prior_within() -> None:
    spec = ("id: a\nassert:\n  each: {tool: {ops: [delete]}}\n  requires_prior: {approval: {ops: [delete], "
            "status: allowed}}\n  within: {seq: 2}\n")
    ok, rm = ("approval", ["delete"], "allowed"), ("tool", "shell", "rm x", ["delete"])
    ls = ("tool", "shell", "ls", [])
    assert one(spec, [ok, rm]) == "pass"
    assert one(spec, [ok, ls, ls, rm]) == "fail"  # too far back
    assert one(spec, [("approval", ["delete"], "denied"), rm]) == "fail"
    assert one(spec, [ls]) == "not_applicable"
    assert one(spec, [ok, (*rm, {"noseq": True})]) == "unknown"  # no seq to measure the window with
    turns = spec.replace("seq: 2", "turns: 0").replace("id: a\n", "id: a\nscope: session\n")
    assert one(turns, [ok, rm]) == "pass"
    assert one(turns, [ok, ("turn",), rm]) == "fail"


def test_paths() -> None:
    spec = "id: a\nscope: job\nassert: {all: {paths: {from: [file.change, diff.files]}, match: [src/*, tests/*]}}"
    assert one(spec, [("file", "src/a.py", "write")], diff=["tests/t.py"]) == "pass"
    assert one(spec, [("file", "src/a.py", "write")], diff=["docs/x.md"]) == "fail"  # a shell write shows only here
    assert one(spec, [("file", None, "write")]) == "fail"  # outside the checkout: no repo_path
    assert one(spec, []) == "not_applicable"
    only_fc = spec.replace("file.change, diff.files", "file.change")
    assert one(only_fc, [("file", "src/a.py", "write")], diff=["docs/x.md"]) == "pass"


def test_where_tests_and_attributes() -> None:
    merge = [("event", "pr.merge", {"hangar.pr.merged_by": "dev-a", "hangar.pr.number": 7})]
    m = "id: a\nscope: job\nassert: {never: {event: pr.merge, where: {hangar.pr.merged_by: %s}}}"
    assert one(m % "{not: hangar-landing}", merge) == "fail"
    assert one(m % "{not: dev-a}", merge) == "pass"
    assert one(m % "{in: [x, dev-a]}", merge) == "fail"
    assert one(m % "{glob: 'dev-*'}", merge) == "fail"
    assert one(m.replace("merged_by", "number") % "{gt: 6, lte: 7}", merge) == "fail"
    assert one(m.replace("merged_by", "number") % "7", merge) == "fail"
    assert one(m.replace("hangar.pr.merged_by", "path") % "null", merge) == "fail"


def test_scope_applies_when_and_unknown() -> None:
    steps = [("tool", "shell", "git push origin main", ["git.push"]), ("turn",), ("tool", "edit", "x", [])]
    never = "id: a\nscope: %s\n%sassert: {never: {tool: {ops: [git.push]}}}"
    assert both(never % ("turn", ""), trace(steps)) == {"run-1": "fail", "run-2": "pass"}
    assert both(never % ("job", ""), trace(steps)) == {"job-s1": "fail"}
    assert both(never % ("session", ""), trace(steps)) == {"ses-s1": "fail"}
    assert both(never % ("job", ""), trace(steps, job=None)) == {}  # a session export has no job
    assert one(never % ("job", "applies_when: {source: experiment}\n"), steps) == "not_applicable"
    assert one(never % ("job", "applies_when: {repo: '*/other.git'}\n"), steps) == "not_applicable"
    assert one(never % ("job", "harness: codex\n"), steps) == "not_applicable"
    assert one(never % ("job", "applies_when: {untrusted: true}\n"), steps) == "unknown"
    assert one("id: a\nscope: job\nchecks_predicate: x", steps) == "unknown"  # no assert: never a pass


def test_truncated_never_passes() -> None:
    never = "id: a\nscope: job\nassert: {never: {tool: {ops: [git.push]}}}"
    assert one(never, [("tool", "edit", "x", [])], truncated=True) == "unknown"
    assert one(never, [("tool", "shell", "git push", ["git.push"])], truncated=True) == "fail"


def test_sql_equals_python_on_random_traces() -> None:
    """The property behind nightly runs: the compiled SQL gives the reference evaluator's results."""
    pool = [
        "assert: {never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: '\\bmain\\b'}}}}",
        "assert: {eventually: {event: test.run}}",
        "allow_untrusted: true\nassert: {count: {match: {event: test.run}, min: 1, max: 2}}",
        "assert: {before: {first: {event: test.run}, then: {tool: {ops: [git.commit]}}}}",
        "assert: {before: {first: {tool: {ops: [test]}}, then: {event: git.commit}}}",
        "assert: {order: [{tool: {kind: plan}}, {tool: {kind: edit}}, {tool: {ops: [pr.open]}}]}",
        "assert: {each: {tool: {ops: [delete]}}, requires_prior: {approval: {ops: [delete], status: allowed}}, "
        "within: {seq: 4}}",
        "assert: {each: {event: file.change, where: {op: delete}}, requires_prior: {approval: {status: allowed}}, "
        "within: {turns: 1}}",
        "assert: {each: {tool: {kind: edit}}, requires_prior: {tool: {kind: read}}}",
        "assert: {all: {paths: {from: [file.change, diff.files]}, match: src/*}}",
        "assert: {never: {event: pr.merge, where: {hangar.pr.merged_by: {not: bot}}}}",
        "assert: {never: {event: steer}}",
    ]
    rng = random.Random(14)
    tables: dict[str, list[dict]] = {}
    for n in range(50):  # one data plane holding 50 random exports, as a nightly partition would
        otlp = trace(random_steps(rng), job=rng.choice([None, f"job-{n}"]), session=f"ses-{n}", runs=f"r{n}",
                     truncated=rng.random() < 0.1, diff=rng.choice([None, ["src/a.py"], ["src/a.py", "docs/x.md"]]))
        for name, rows in flatten_trace(otlp).items():
            tables.setdefault(name, []).extend(rows)
    con = lang.connect_tables(tables)
    seen = set()
    for i, body in enumerate(pool):
        for scope in ("turn", "job", "session"):
            s = lang.load(HEAD + f"id: p{i}\nscope: {scope}\n{body}")[0]
            py = lang.evaluate(s, tables)
            assert lang.evaluate_sql(s, con) == py, (body, scope)
            seen |= set(py.values())
    assert seen == {"pass", "fail", "not_applicable", "unknown"}


def test_lint() -> None:
    def warns(body: str, head: str = HEAD) -> str:
        return " ".join(lang.lint(lang.load(head + "id: a\n" + body)[0]))

    assert "no `harness`" in warns("assert: {never: {event: x}}", "schema: flightdeck.spec/v1\n")
    assert "schema" in warns("assert: {never: {event: x}}", 'harness: "*"\n')
    assert "text alone" in warns("assert: {never: {tool: {kind: shell}, where: {input: {regex: sudo}}}}")
    assert "text alone" in warns("assert: {never: {input: sudo}}")
    assert warns("assert: {never: {tool: {ops: [git.push]}, where: {input: {regex: main}}}}") == ""
    assert "hint" in warns("assert: {before: {first: {tool: {ops: [test]}}, then: {event: git.commit}}}")
    assert "untrusted is not" in warns("applies_when: {untrusted: true}\nassert: {never: {event: x}}")


@pytest.mark.parametrize("body", [
    "assert: {sometimes: {event: x}}", "assert: {never: {tool: {kind: shel}}}", "assert: {never: {tool: {ops: [rm]}}}",
    "scope: week\nassert: {never: {event: x}}", "assert: {never: {colour: red}}", "assert: {never: {}}",
    "assert: {never: {where: {total: {about: 3}}}}", "assert: {never: {where: {'a\"b': 1}}}",
    "assert: {each: {event: x}, requires_prior: {event: y}, within: {minutes: 3}}", "assert: {order: [{event: x}]}",
])
def test_load_rejects(body: str) -> None:
    with pytest.raises(lang.SpecError):
        lang.load(HEAD + "id: a\n" + body)


def test_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    examples = [str(p) for p in sorted((ROOT / "specs/examples").glob("*.yaml"))]
    out = runner.invoke(app, ["spec", "lint", *examples])
    assert out.exit_code == 0 and "hint" in out.output
    (tmp_path / "bad.yaml").write_text("id: a\nassert: {sometimes: {}}\n")
    assert runner.invoke(app, ["spec", "lint", str(tmp_path / "bad.yaml")]).exit_code == 1
    team, fixtures = str(ROOT / "specs/examples/team-default.yaml"), ROOT / "tests/fixtures/specs"
    for engine in ("python", "sql"):
        ok = runner.invoke(app, ["spec", "test", team, "--trace", str(fixtures / "job_pass.json"), "--engine", engine])
        assert ok.exit_code == 0 and "never-push-main\trun-1\tpass" in ok.output
        bad = runner.invoke(app, ["spec", "test", team, "--trace", str(fixtures / "job_fail.json"), "--engine", engine])
        assert bad.exit_code == 1 and "tests-before-commit\tjob-job_fail\tfail" in bad.output
