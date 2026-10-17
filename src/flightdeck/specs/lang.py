"""`flightdeck.spec/v1`: behavior specs, small YAML predicates over `hangar.trace/v1` (docs/behavior-specs.md).

A spec judges one *unit* (a turn, job or session) over its *items*: the tool calls, approvals, events and test runs of
`flightdeck.parquet/v1` in one shape. One grammar, two evaluators: `evaluate` in Python over one flattened export
(`spec test`, unit tests) and `sql` for DuckDB over the data plane (nightly). Each matcher is compiled to a Python
predicate and a SQL expression side by side, and a property test keeps the two evaluators equal.
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import Callable
from fnmatch import fnmatchcase
from typing import Any

import duckdb
import yaml

from flightdeck.dataplane.schema import TABLES, to_table

SCHEMA = "flightdeck.spec/v1"
KINDS = {"shell", "edit", "read", "search", "web", "mcp", "skill", "plan", "other"}
OPS = {"test", "git.commit", "git.push", "pr.open", "delete"}
SCOPES = {"turn": "run_id", "job": "job_id", "session": "session_id"}
UNIT_KEYS = ("source", "repo", "task_id", "variant")  # applies_when keys: runs columns, globs
CMP = {"gt": (operator.gt, ">"), "gte": (operator.ge, ">="), "lt": (operator.lt, "<"), "lte": (operator.le, "<=")}
PASS, FAIL, NA, UNKNOWN = "pass", "fail", "not_applicable", "unknown"
# Item columns, from each data-plane table's columns. Items also carry k (tool|approval|event), ids, turn and attrs.
SPAN_MAP = {"name": "tool_name", "tool_kind": "tool_kind", "ops": "shell_ops", "seq": "seq", "t": "start_ns",
            "path": "file_repo_path", "input": "tool_input", "output": "tool_output", "status": "approval_status",
            "mcp_server": "mcp_server", "mcp_tool": "mcp_tool", "skill": "skill_name"}
EVENT_MAP = {"name": "name", "seq": "seq", "t": "time_ns", "path": "file_repo_path", "op": "file_op"}
TEST_MAP = {"t": "time_ns", "status": "status", "trusted": "trusted", "total": "total", "complete": "complete"}
COLS = (set(SPAN_MAP) | set(EVENT_MAP) | set(TEST_MAP) | {"turn"}) - {"ops", "t"}
Spec = dict[str, Any]
Item = dict[str, Any]
Matcher = tuple[Callable[[Item], bool], Callable[[str], str]]  # (Python predicate, SQL over an alias)


class SpecError(ValueError):
    """A spec that does not parse, or uses an unknown operator, matcher, kind or op."""


def load(text: str) -> list[Spec]:
    """Specs from one YAML stream; later documents inherit the first one's keys except `id` and `assert`."""
    docs = [d for d in yaml.safe_load_all(text) if d]
    if not all(isinstance(d, dict) and d.get("id") for d in docs):
        raise SpecError("every spec document is a mapping with an `id`")
    base = {k: v for k, v in (docs[0] if docs else {}).items() if k not in ("id", "assert")}
    specs = [{**base, **d} for d in docs]
    for s in specs:
        plan(s)
    return specs


def _q(v: Any) -> str:
    """A SQL literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _render(v: Any) -> Any:
    """An attribute value as DuckDB's json_extract_string gives it."""
    return v if v is None or isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _field(f: str) -> tuple[Callable[[Item], Any], Callable[[str], str], Callable[[Any], Any]]:
    """(Python getter, SQL getter, literal renderer) for a `where` field: an item column or a full attribute name."""
    if f in COLS:
        return (lambda i: i[f]), (lambda q: f"{q}.{f}"), (lambda v: v)
    if not re.fullmatch(r"[\w.]+", f):
        raise SpecError(f"bad attribute name {f!r}")
    return (lambda i: _render(i["attrs"].get(f))), (lambda q: f"json_extract_string({q}.attrs, '$.\"{f}\"')"), _render


def _cond(f: str, test: Any) -> list[Matcher]:
    """`where: {f: test}`: a scalar (equality, null = absent), or {not, in, regex, glob, gt, gte, lt, lte}."""
    get, col, lit = _field(f)
    if not isinstance(test, dict):
        if test is None:
            return [(lambda i: get(i) is None, lambda q: f"{col(q)} is null")]
        return [(lambda i: get(i) == lit(test), lambda q: f"{col(q)} = {_q(lit(test))}")]
    out: list[Matcher] = []
    for op, v in test.items():
        if op == "not":
            out.append((lambda i, v=v: get(i) is not None and get(i) != lit(v),
                        lambda q, v=v: f"{col(q)} <> {_q(lit(v))}"))
        elif op == "in":
            out.append((lambda i, v=v: get(i) in [lit(x) for x in v],
                        lambda q, v=v: f"{col(q)} in ({', '.join(_q(lit(x)) for x in v)})"))
        elif op == "regex":
            out.append((lambda i, v=v: isinstance(get(i), str) and re.search(v, get(i)) is not None,
                        lambda q, v=v: f"regexp_matches({col(q)}, {_q(v)})"))
        elif op == "glob":
            out.append((lambda i, v=v: isinstance(get(i), str) and fnmatchcase(get(i), v),
                        lambda q, v=v: f"{col(q)} glob {_q(v)}"))
        elif op in CMP:
            fn, sym = CMP[op]
            out.append((lambda i, v=v, fn=fn: (n := _num(get(i))) is not None and fn(n, float(v)),
                        lambda q, v=v, sym=sym: f"try_cast({col(q)} as double) {sym} {float(v)!r}"))
        else:
            raise SpecError(f"unknown test {op!r} on {f!r}")
    return out


def _ops(ops: Any) -> Matcher:
    if not isinstance(ops, list) or not set(ops) <= OPS:
        raise SpecError(f"ops must be a list of {sorted(OPS)}: {ops!r}")
    return (lambda i: bool(set(i["ops"] or ()) & set(ops)),
            lambda q: f"list_has_any({q}.ops, [{', '.join(map(_q, ops))}]::varchar[])")


def matcher(m: Any, spec: Spec) -> Matcher:
    """One matcher: `tool`, `approval`, `event`, `path`, `input`, `output` and `where`, all of which must hold."""
    if not isinstance(m, dict) or not m:
        raise SpecError(f"{spec.get('id')}: a matcher is a non-empty mapping: {m!r}")
    c: list[Matcher] = []
    for key, v in m.items():
        if key in ("tool", "approval"):
            c.append((lambda i, key=key: i["k"] == key, lambda q, key=key: f"{q}.k = '{key}'"))
            v = v or {}
            allowed = {"kind", "ops", "mcp", "skill"} if key == "tool" else {"ops", "status"}
            if not isinstance(v, dict) or set(v) - allowed:
                raise SpecError(f"{key}: keys are {sorted(allowed)}: {v!r}")
            if "kind" in v and v["kind"] not in KINDS:
                raise SpecError(f"unknown tool kind {v['kind']!r}")
            c += [_ops(v["ops"])] if "ops" in v else []
            mcp = v.get("mcp") or {}
            for f, x in [("tool_kind", v.get("kind")), ("status", v.get("status")), ("skill", v.get("skill")),
                         ("mcp_server", mcp.get("server")), ("mcp_tool", mcp.get("tool"))]:
                c += _cond(f, x) if x is not None else []
        elif key == "event":
            c += [(lambda i: i["k"] == "event", lambda q: f"{q}.k = 'event'"), *_cond("name", v)]
            if v == "test.run" and not spec.get("allow_untrusted"):  # the trusted-test rule
                c += [*_cond("trusted", True), *_cond("total", {"gt": 0})]
                c.append((lambda i: i["complete"] is not False, lambda q: f"{q}.complete is distinct from false"))
        elif key == "path":
            c += _cond("path", {"glob": v})
        elif key in ("input", "output"):
            c += _cond(key, {"regex": v} if isinstance(v, str) else v)
        elif key == "where":
            if not isinstance(v, dict):
                raise SpecError(f"where must be a mapping: {v!r}")
            for f, test in v.items():
                c += _cond(f, test)
        else:
            raise SpecError(f"unknown matcher key {key!r}")
    return (lambda i: all(p(i) for p, _ in c), lambda q: " and ".join(f"coalesce(({s(q)}), false)" for _, s in c))


def plan(s: Spec) -> tuple[str, dict[str, Any]]:
    """Validate a spec; its operator (count, order, each, paths, unknown) and compiled arguments."""
    if s.get("scope", "turn") not in SCOPES:
        raise SpecError(f"{s.get('id')}: scope is one of {sorted(SCOPES)}")
    a = s.get("assert")
    if a is None:
        return "unknown", {}  # e.g. an ADR check written in another grammar: never a pass
    if not isinstance(a, dict):
        raise SpecError(f"{s.get('id')}: assert must be a mapping")
    m = lambda x: matcher(x, s)  # noqa: E731
    if "before" in a:
        return "order", {"ms": [m(a["before"]["first"]), m(a["before"]["then"])], "na": True}
    if "order" in a and isinstance(a["order"], list) and len(a["order"]) > 1:
        return "order", {"ms": [m(x) for x in a["order"]], "na": False}
    if "never" in a or "eventually" in a:
        return "count", {"m": m(a.get("never") or a.get("eventually")), "lo": int("eventually" in a),
                         "hi": 0 if "never" in a else None}
    if "count" in a:
        return "count", {"m": m(a["count"].get("match")), "lo": a["count"].get("min", 0), "hi": a["count"].get("max")}
    if "each" in a:
        w = a.get("within") or {}
        if set(w) - {"seq", "turns"} or not all(isinstance(n, int) for n in w.values()):
            raise SpecError(f"within: {{seq: N}} or {{turns: N}}: {w!r}")
        return "each", {"b": m(a["each"]), "a": m(a["requires_prior"]), "w": w}
    if "all" in a or "any" in a:
        q = a.get("all") or a.get("any") or {}
        src, g = (q.get("paths") or {}).get("from", ["file.change", "diff.files"]), q.get("match")
        if not g or set(src) - {"file.change", "diff.files"}:
            raise SpecError("all|any: {paths: {from: [file.change, diff.files]}, match: <glob or list>}")
        return "paths", {"from": src, "match": [g] if isinstance(g, str) else g, "any": "all" not in a}
    raise SpecError(f"{s.get('id')}: unknown operator in {sorted(a)}")


# --- the Python evaluator ----------------------------------------------------------------------------------------


def items(tables: dict[str, list[dict]]) -> list[Item]:
    """One flattened export's items, as the `items` view builds them."""
    runs = {r["run_id"]: r for r in tables.get("runs", [])}
    traces: dict[str, tuple] = {}
    for s in tables.get("spans", []):
        traces.setdefault(s["trace_id"], (s.get("job_id"), s.get("session_id")))
    out = []

    def add(row: dict, k: str, cols: dict[str, str], **extra: Any) -> None:
        job, ses = traces.get(row["trace_id"], (None, None))
        r = runs.get(row["run_id"], {})
        out.append({**dict.fromkeys(COLS), "ops": None, **{d: row.get(s) for d, s in cols.items()}, **extra, "k": k,
                    "run_id": row["run_id"], "job_id": job, "session_id": r.get("session_id") or ses,
                    "turn": r.get("turn"), "attrs": json.loads(row.get("attrs") or "{}")})

    for s in tables.get("spans", []):
        if s.get("kind") in ("tool.call", "approval"):
            add(s, "tool" if s["kind"] == "tool.call" else "approval", SPAN_MAP)
    for e in tables.get("events", []):
        add(e, "event", EVENT_MAP)
    for t in tables.get("test_cases", []):
        if t.get("case_name") is None:
            add(t, "event", TEST_MAP, name="test.run")
    return out


def _units(tables: dict[str, list[dict]], scope: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in tables.get("runs", []):
        if (key := r.get(SCOPES[scope])) is None:
            continue
        u = out.setdefault(key, {"truncated": False, "diff": [], **{k: r.get(k) for k in (*UNIT_KEYS, "harness")}})
        u["truncated"] |= bool(r.get("truncated"))
        u["diff"] += r.get("diff_files") or []
    return out


def _ordered(groups: list[list[Item]]) -> bool:
    """First of each group strictly in order: by hangar.seq when all have one, else by time (traces.md 'Order')."""
    if not all(groups):
        return False
    key = "seq" if all(i["seq"] is not None for g in groups for i in g) else "t"
    firsts = [min(i[key] for i in g) for g in groups]
    return all(x < y for x, y in zip(firsts, firsts[1:], strict=False))


def _prior(p: Item, b: Item, w: dict) -> bool:
    before = p["seq"] < b["seq"] if p["seq"] is not None and b["seq"] is not None else p["t"] < b["t"]
    return before and all(p[c] is not None and b[c] is not None and b[c] - p[c] <= n
                          for c, n in (("seq", w.get("seq")), ("turn", w.get("turns"))) if n is not None)


def _eval(op: str, a: dict, its: list[Item], u: dict) -> str:
    if op == "count":
        n = sum(a["m"][0](i) for i in its)
        return PASS if n >= a["lo"] and (a["hi"] is None or n <= a["hi"]) else FAIL
    if op == "order":
        groups = [[i for i in its if m[0](i)] for m in a["ms"]]
        return NA if a["na"] and not groups[-1] else PASS if _ordered(groups) else FAIL
    if op == "each":
        bs, prior = [i for i in its if a["b"][0](i)], [i for i in its if a["a"][0](i)]
        missed = [b for b in bs if not any(_prior(p, b, a["w"]) for p in prior)]
        unk = lambda b: ("seq" in a["w"] and b["seq"] is None) or ("turns" in a["w"] and b["turn"] is None)  # noqa: E731
        return NA if not bs else PASS if not missed else UNKNOWN if all(map(unk, missed)) else FAIL
    if op == "paths":
        ps = [i["path"] for i in its if i["k"] == "event" and i["name"] == "file.change" and "file.change" in a["from"]]
        ps += u["diff"] if "diff.files" in a["from"] else []
        ok = (any if a["any"] else all)(isinstance(p, str) and any(fnmatchcase(p, g) for g in a["match"]) for p in ps)
        return NA if not ps else PASS if ok else FAIL
    return UNKNOWN


def _applies(s: Spec, u: dict) -> bool | None:
    """Whether a unit is in scope: applies_when's UNIT_KEYS and the harness name. None: unknowable from the plane."""
    if set(s.get("applies_when") or {}) - set(UNIT_KEYS):
        return None
    return all(any(fnmatchcase(u[k] or "", g) for g in gs) for k, gs in _scope(s).items())


def _scope(s: Spec) -> dict[str, list[str]]:
    """A spec's unit filters as globs per runs column (a string or a list of strings each)."""
    f = {**{k: v for k, v in (s.get("applies_when") or {}).items() if v}, "harness": s.get("harness", "*")}
    return {k: [v] if isinstance(v, str) else list(v) for k, v in f.items()}


def _finish(applies: bool | None, truncated: bool, result: str) -> str:
    """A truncated export never passes: what it is missing could have been the violation."""
    if applies is None or not applies:
        return UNKNOWN if applies is None else NA
    return UNKNOWN if truncated and result in (PASS, NA) else result


def evaluate(s: Spec, tables: dict[str, list[dict]]) -> dict[str, str]:
    """Results per unit of one flattened export (`flatten_trace` output)."""
    op, a = plan(s)
    col, its = SCOPES[s.get("scope", "turn")], items(tables)
    return {key: _finish(_applies(s, u), u["truncated"], _eval(op, a, [i for i in its if i[col] == key], u))
            for key, u in _units(tables, s.get("scope", "turn")).items()}


# --- the SQL compiler --------------------------------------------------------------------------------------------


def prepare(con: duckdb.DuckDBPyConnection, dt: str | None = None) -> None:
    """Create the `items` view (and `_runs`) over a connection's data-plane views, optionally for one day."""
    have = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    for n in ("runs", "spans", "events", "test_cases", "manifests"):
        if n not in have:
            con.register(n, TABLES[n].empty_table())
        con.execute(f"create or replace temp table _{n} as select * from {n}" + (f" where dt = {_q(dt)}" if dt else ""))
    sel = lambda m: ", ".join(f"{s} as {d}" for d, s in m.items())  # noqa: E731
    con.execute(f"""create or replace temp table items as with x as (
        select trace_id, run_id, case kind when 'tool.call' then 'tool' else 'approval' end as k, {sel(SPAN_MAP)},
            attrs from _spans where kind in ('tool.call', 'approval')
        union all by name select trace_id, run_id, 'event' as k, {sel(EVENT_MAP)}, attrs from _events
        union all by name select trace_id, run_id, 'event' as k, 'test.run' as name, {sel(TEST_MAP)}
            from _test_cases where case_name is null)
      select x.*, tr.job_id, coalesce(r.session_id, tr.session_id) as session_id, r.turn from x
      left join (select trace_id, any_value(job_id) job_id, any_value(session_id) session_id from _spans group by 1)
        tr using (trace_id)
      left join (select run_id, any_value(session_id) session_id, any_value(turn) turn from _runs group by 1)
        r using (run_id)""")


def sql(s: Spec) -> str:
    """One spec as a DuckDB query over `prepare`'s views, returning (unit, result)."""
    op, a = plan(s)
    col = SCOPES[s.get("scope", "turn")]
    mine = f"i.{col} = u.unit"
    agg = lambda f, cond: f"(select {f} from items i where {mine} and ({cond}))"  # noqa: E731
    if op == "count":
        n = agg("count(*)", a["m"][1]("i"))
        body = f"{n} >= {a['lo']}" + (f" and {n} <= {a['hi']}" if a["hi"] is not None else "")
        res = f"case when {body} then '{PASS}' else '{FAIL}' end"
    elif op == "order":
        ms = a["ms"]
        allseq = agg("coalesce(bool_and(i.seq is not null), true)", " or ".join(f"({m[1]('i')})" for m in ms))
        cmp = lambda c: " and ".join(f"{agg(f'min(i.{c})', x[1]('i'))} < {agg(f'min(i.{c})', y[1]('i'))}"  # noqa: E731
                                     for x, y in zip(ms, ms[1:], strict=False))
        ok = f"coalesce(case when coalesce({allseq}, true) then {cmp('seq')} else {cmp('t')} end, false)"
        na = f"when {agg('count(*)', ms[-1][1]('i'))} = 0 then '{NA}' " if a["na"] else ""
        res = f"case {na}when {ok} then '{PASS}' else '{FAIL}' end"
    elif op == "each":
        w = a["w"]
        lim = (("seq", w.get("seq")), ("turn", w.get("turns")))
        win = "".join(f" and b.{c} - p.{c} <= {n}" for c, n in lim if n is not None)
        prior = "case when p.seq is not null and b.seq is not null then p.seq < b.seq else p.t < b.t end"
        missed = (f"from items b where b.{col} = u.unit and ({a['b'][1]('b')}) and not exists (select 1 from items p "
                  f"where p.{col} = b.{col} and ({a['a'][1]('p')}) and {prior}{win})")
        unk = " or ".join(f"b.{c} is null" for c, n in lim if n is not None) or "false"
        res = (f"case when {agg('count(*)', a['b'][1]('i'))} = 0 then '{NA}' when exists (select 1 {missed} and not "
               f"({unk})) then '{FAIL}' when exists (select 1 {missed}) then '{UNKNOWN}' else '{PASS}' end")
    elif op == "paths":
        fc = (agg("coalesce(list(i.path), [])", "i.k = 'event' and i.name = 'file.change'")
              if "file.change" in a["from"] else "[]::varchar[]")
        ps = f"list_concat({fc}, {'u.diff' if 'diff.files' in a['from'] else '[]::varchar[]'})"
        globs = " or ".join(f"x glob {_q(g)}" for g in a["match"])
        hits = f"len(list_filter({ps}, lambda x: {'' if a['any'] else 'not '}coalesce({globs}, false)))"
        res = f"case when len({ps}) = 0 then '{NA}' when {hits} {'>' if a['any'] else '='} 0 then '{PASS}' " \
            f"else '{FAIL}' end"
    else:
        res = f"'{UNKNOWN}'"
    applies = " and ".join("(" + " or ".join(f"coalesce(u.{k}, '') glob {_q(g)}" for g in gs) + ")"
                           for k, gs in _scope(s).items()) if not set(s.get("applies_when") or {}) - set(UNIT_KEYS) \
        else "null"
    return f"""with u as (select {col} as unit, bool_or(coalesce(truncated, false)) as trunc,
        {", ".join(f"any_value({k}) as {k}" for k in (*UNIT_KEYS, "harness"))},
        flatten(list(coalesce(diff_files, []))) as diff
        from _runs where {col} is not null group by 1),
      r as (select unit, trunc, {applies} as applies, {res} as res from u)
      select unit, case when applies is null then '{UNKNOWN}' when not applies then '{NA}'
        when trunc and res in ('{PASS}', '{NA}') then '{UNKNOWN}' else res end from r order by 1"""


def connect_tables(tables: dict[str, list[dict]]) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB holding one flattened export's rows as the data-plane tables, prepared."""
    con = duckdb.connect(config={"threads": 1})
    for name, rows in tables.items():
        con.register(name, to_table(name, rows))
    prepare(con)
    return con


def evaluate_sql(s: Spec, con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Results per unit from the compiled SQL over a prepared connection."""
    return dict(con.execute(sql(s)).fetchall())


# --- lint --------------------------------------------------------------------------------------------------------


def _matchers(a: Any) -> list[dict]:
    if not isinstance(a, dict):
        return []
    found = [a.get(k) for k in ("never", "eventually", "each", "requires_prior")]
    found += list((a.get("before") or {}).values()) + list(a.get("order") or []) + [(a.get("count") or {}).get("match")]
    return [m for m in found if isinstance(m, dict)]


def lint(s: Spec) -> list[str]:
    """Warnings for a spec that loads but is weak, gameable or not judgeable (docs/behavior-specs.md)."""
    sid, w = s.get("id"), []
    if s.get("schema") != SCHEMA:
        w.append(f"{sid}: schema is not {SCHEMA}")
    if "harness" not in s:
        w.append(f"{sid}: no `harness`: contracts are keyed by harness name (\"*\" for any)")
    if s.get("allow_untrusted"):
        w.append(f"{sid}: allow_untrusted counts the agent's own test runs, which `--collect-only` satisfies")
    for k in set(s.get("applies_when") or {}) - set(UNIT_KEYS):
        w.append(f"{sid}: applies_when.{k} is not in flightdeck.parquet/v1 yet, so every result is unknown")
    if s.get("assert") is None:
        w.append(f"{sid}: no `assert` in flightdeck.spec/v1 grammar, so every result is unknown")
    for m in _matchers(s.get("assert")):
        tool, where = m.get("tool") or {}, m.get("where") or {}
        text = {"input", "output"} & (set(m) | set(where))
        if text and not ({"event", "approval", "path"} & set(m) or {"ops", "mcp", "skill"} & set(tool)):
            w.append(f"{sid}: matches on hangar.tool.{min(text)} text alone (a hint that is easy to dodge)")
        if "test" in (tool.get("ops") or []):
            w.append(f"{sid}: the shell `test` op is a hint (`pytest --collect-only` has it); "
                     "proof of testing is `event: test.run`")
    return w
