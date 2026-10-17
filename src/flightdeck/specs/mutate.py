"""`flightdeck mutate plan|run|score`: mutation scoring of behavior suites (docs/behavior-specs.md#mutation-scoring).

A suite that still passes when part of the harness is removed is decoration. `plan` derives mutants from a base
variant's hangar overlay (drop a skill, drop an instructions block, auto approvals, plus a no-op control), `run`
submits them through the experiment client's cost gate, and `score` counts a mutant killed when the grader's resolved
rate differs significantly from the base (paired by task) or a spec that held on the base (pass^k at or above the
bound) falls below it. Mutant variants are named `mutant-*` and are never promoted.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from flightdeck.runners.hangar import load_plan
from flightdeck.specs import lang

OPS = ("drop-skill", "drop-instruction-line", "approvals", "noop")
REPORTED = {"drop-hook": "needs harness.lock hooks in the variant (hangar#133)",
            "widen-egress": "hangar fixes egress per experiment: run it as a separate experiment"}


def _blocks(text: str) -> list[str]:
    """Instructions split into blocks at markdown headings, or into non-empty lines when there are none."""
    parts = re.split(r"(?m)^(?=#{1,6} )", text)
    parts = parts if len(parts) > 1 else text.splitlines(keepends=True)
    return [p for p in parts if p.strip()]


def plan(base: dict[str, Any], ops: list[str], seen_skills: set[str] | None = None, cap: int = 12) -> dict[str, dict]:
    """Mutants of a base variant: {name: {op, component, variant, equivalent}}. `equivalent` says why no observable
    difference is expected (a no-op; a skill no trace of the base ever used), else None."""
    out: dict[str, dict] = {}

    def add(op: str, component: str, variant: dict[str, Any], why: str | None = None) -> None:
        name = re.sub(r"[^a-z0-9-]+", "-", f"mutant-{op}-{component}".lower())[:60].strip("-")
        out[name] = {"op": op, "component": component, "variant": variant, "equivalent": why}

    for op in ops:
        if op not in OPS:
            raise ValueError(f"unknown operator {op!r}: {', '.join(OPS)} (" + "; ".join(
                f"{k}: {v}" for k, v in REPORTED.items()) + ")")
        if op == "noop":
            add(op, "none", dict(base), "the variant is unchanged (a control)")
        elif op == "approvals" and base.get("approvals") == "deny-risky":
            add(op, "approvals:auto", {**base, "approvals": "auto"})
        elif op == "drop-skill":
            names = [s.get("name") or s.get("path") for s in base.get("skills") or []] or sorted(seen_skills or ())
            for n in names:
                v = ({**base, "skills": [s for s in base["skills"] if (s.get("name") or s.get("path")) != n]}
                     if base.get("skills") else {**base, "skills_remove": [*(base.get("skills_remove") or []), n]})
                unused = seen_skills is not None and n not in seen_skills
                add(op, f"skill:{n}", v, "no trace of the base used this skill" if unused else None)
        elif op == "drop-instruction-line":
            for key in ("instructions", "instructions_append"):
                blocks = _blocks(base.get(key) or "")
                for i in range(len(blocks)):
                    add(op, f"{key}:{i + 1}", {**base, key: "".join(blocks[:i] + blocks[i + 1:])})
    return dict(list(out.items())[:cap])


def suggestion(m: dict[str, Any]) -> str:
    """A spec worth adding for a surviving mutant."""
    if m["op"] == "drop-skill":
        return f"`eventually: {{tool: {{skill: {m['component'].split(':', 1)[1]}}}}}` where the skill should fire"
    if m["op"] == "approvals":
        return "`each: {tool: {ops: [delete]}}, requires_prior: {approval: {ops: [delete], status: allowed}}`"
    return "a spec (or grader test) for the behaviour the removed block asks for"


def score(trials: list[dict], units: dict[str, tuple[str, str]], results: dict[str, dict[str, str]], base: str,
          mutants: dict[str, dict], bound: float = 0.9, seed: int = 0) -> dict[str, Any]:
    """Each mutant's verdict (killed, survived, equivalent) and why. `units` maps a spec unit to (variant, task);
    `results` maps spec id to {unit: result}."""
    from flightdeck.stats.compare import compare
    from flightdeck.stats.core import pass_hat_k_suite, wilson

    def passk(sid: str, variant: str) -> float | None:
        per: dict[str, list[bool]] = {}
        for unit, r in results[sid].items():
            if units.get(unit, ("", ""))[0] == variant and r in (lang.PASS, lang.FAIL):
                per.setdefault(units[unit][1], []).append(r == lang.PASS)
        if not per:
            return None
        k = min(len(v) for v in per.values())
        return pass_hat_k_suite([(sum(v), len(v)) for v in per.values()], k)

    held = {sid: p for sid in results if (p := passk(sid, base)) is not None and p >= bound}
    verdicts = {}
    for name, m in mutants.items():
        if m.get("equivalent") or not any(t["variant"] == name for t in trials):
            verdicts[name] = {**m, "verdict": "equivalent" if m.get("equivalent") else "not run",
                              "why": m.get("equivalent") or "no trials in the run set"}
            continue
        why = [f"spec {sid}: pass^k {p:.2f} -> {q:.2f}" for sid, p in held.items()
               if (q := passk(sid, name)) is not None and q < bound]
        d = compare(trials, "resolved", base, name, seed).diff
        if d and (d.low > 0 or d.high < 0):
            why.append(f"resolved {d.estimate * 100:+.0f} pp [{d.low * 100:+.0f}, {d.high * 100:+.0f}]")
        verdicts[name] = {**m, "verdict": "killed" if why else "survived", "why": "; ".join(why) or "no difference"}
    n = {v: sum(x["verdict"] == v for x in verdicts.values()) for v in ("killed", "survived", "equivalent", "not run")}
    return {"mutants": verdicts, **n, "kill_rate": n["killed"] / max(1, n["killed"] + n["survived"]),
            "wilson95": wilson(n["killed"], n["killed"] + n["survived"]), "held": held}


def render(suite: str, s: dict[str, Any]) -> str:
    lo, hi = s["wilson95"]
    out = [f"### Mutation score: {suite}", "",
           f"**{s['killed']}/{s['killed'] + s['survived']} killed ({s['kill_rate']:.0%}, 95% Wilson "
           f"{lo:.0%}-{hi:.0%})**, {s['survived']} survived, {s['equivalent']} equivalent and {s['not run']} not run "
           "(not counted). "
           "Specs that held on the base: "
           + (", ".join(f"`{k}`" for k in s["held"]) or "none") + ".", "",
           "| mutant | component | verdict | why |", "| --- | --- | --- | --- |"]
    out += [f"| {k} | `{m['component']}` | {m['verdict']} | {m['why']} |" for k, m in s["mutants"].items()]
    survivors = [m for m in s["mutants"].values() if m["verdict"] == "survived"]
    if survivors:
        out += ["", "Surviving mutants, with a spec to add:", ""]
        out += [f"- `{m['component']}`: {suggestion(m)}" for m in survivors]
    return "\n".join(out)


# --- CLI ---------------------------------------------------------------------------------------------------------

app = typer.Typer(help="Mutation scoring: mutate the harness, check the suite catches each mutant.",
                  no_args_is_help=True)
DATA = Annotated[str | None, typer.Option("--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane root.")]


@app.command("plan")
def plan_cmd(suite: Path, harness: Annotated[str, typer.Option(help="The base variant in the suite.")],
             out: Annotated[Path, typer.Option(help="The mutants' suite file to write.")],
             ops: str = ",".join(OPS), max_mutants: Annotated[int, typer.Option("--max")] = 12,
             n: int = 2, data: DATA = None) -> None:
    """Write a suite with the base variant and its mutants, n trials each. Equivalent mutants (the no-op control;
    skills no trace in --data used) are listed but not run."""
    doc = yaml.safe_load(suite.read_text()) or {}
    base = (doc.get("variants") or {}).get(harness)
    if base is None:
        raise typer.BadParameter(f"no variant {harness!r} in {suite}")
    seen = None
    if data:
        from flightdeck.dataplane.duck import connect

        seen = {r[0] for r in connect(os.path.expanduser(data)).sql(
            "select distinct skill_name from spans where skill_name is not null").fetchall()}
    mutants = plan(base, [o for o in ops.split(",") if o], seen, max_mutants)
    tasks = [str((suite.parent / t).resolve()) for t in doc.get("tasks") or []]
    doc.update(suite=f"{doc.get('suite') or suite.stem}-mutants", tasks=tasks, n=n, base=harness,
               variants={harness: base, **{k: m["variant"] for k, m in mutants.items() if not m["equivalent"]}},
               mutants={k: {x: m[x] for x in ("op", "component", "equivalent")} for k, m in mutants.items()})
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    for k, m in mutants.items():
        typer.echo(f"{k}\t{m['component']}" + (f"\tequivalent: {m['equivalent']}" if m["equivalent"] else ""))
    for op, why in REPORTED.items():
        typer.echo(f"not generated\t{op}\t{why}")
    load_plan(out)  # the file must load as a suite
    typer.echo(f"wrote {out}: flightdeck mutate run {out}")


@app.command("run")
def run_cmd(plan_file: Path, max_usd: float = 40.0, dry_run: bool = False, data: DATA = None) -> None:
    """Submit the mutants through `experiment run`'s cost gate (projection first; refused above --max-usd)."""
    from flightdeck.runners.cli import run

    run(plan_file, dry_run=dry_run, max_usd=max_usd, assume=3.0, budgets=None, author=os.environ.get(
        "FLIGHTDECK_AUTHOR", ""), allow_model=None, data=data or "", kind="hangar", cache=False)


@app.command("score")
def score_cmd(plan_file: Path, run_set: str, specs: Annotated[list[Path], typer.Option(help="Spec files.")],
              data: DATA = None, bound: float = 0.9, out: Path | None = None) -> None:
    """Kill rate with its interval, every mutant's verdict, and the survivors with a spec to add (markdown)."""
    from flightdeck.dataplane.duck import connect
    from flightdeck.stats.compare import load_trials

    if not data:
        raise typer.BadParameter("no data plane: pass --data or set FLIGHTDECK_DATA_URI")
    doc = yaml.safe_load(plan_file.read_text())
    con = connect(os.path.expanduser(data))
    exps = run_set.split("+")
    trials = load_trials(con, run_set)
    lang.prepare(con)
    todo = [s for p in specs for s in lang.load(p.read_text())]
    units: dict[str, tuple[str, str]] = {}
    for s in todo:
        col = lang.SCOPES[s.get("scope", "turn")]
        units |= {r[0]: (r[1], r[2]) for r in con.execute(
            f"select {col}, any_value(variant), any_value(task_id) from _runs where experiment_id in "
            f"({', '.join('?' * len(exps))}) and {col} is not null group by 1", exps).fetchall()}
    results = {s["id"]: {u: r for u, r in lang.evaluate_sql(s, con).items() if u in units} for s in todo}
    md = render(doc["suite"], score(trials, units, results, doc["base"], doc["mutants"], bound))
    typer.echo(md)
    if out:
        out.write_text(md + "\n")
