"""`flightdeck stats compare`: one experiment's variants, paired by task, from the data plane (docs/statistics.md).

Every comparison prints its exclusions with counts and the resolved definition it used; saturated tasks are listed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import duckdb
import typer

from flightdeck.stats.core import Interval, dollars_per_resolved, paired_bootstrap, simulate_power, wilson

METRICS = ("resolved", "cost_usd", "tool_calls", "wall_s")


def load_trials(con: duckdb.DuckDBPyConnection, exp_id: str) -> list[dict[str, Any]]:
    """One dict per trial of the experiment: its `runs` row, its grade and its tool-call count."""
    rel = con.execute("select r.* exclude (started_at, finished_at), epoch(r.finished_at) as finished_epoch, "
                      "epoch(r.finished_at) - epoch(r.started_at) as wall_s, g.exit_code as grade_exit, "
                      "g.applied as grade_applied, g.command as grade_command, (select case when count(*) > 0 then "
                      "count(*) filter (s.kind = 'tool.call') end from spans s where s.run_id = r.run_id) as "
                      "tool_calls from runs r left join grades g "
                      "using (run_id) where r.experiment_id = ? order by task_id, variant, trial", [exp_id])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]


def resolved(t: dict[str, Any]) -> tuple[bool | None, str]:
    """Resolved and the column it came from: the grader when it ran, else hangar's after-turn verify."""
    if t.get("grade_exit") is not None:
        return t["grade_exit"] == 0 and bool(t["grade_applied"]), "grader"
    return t.get("verify_passed"), "verify"


def exclusion(t: dict[str, Any], metric: str, include_drift: bool = False) -> str | None:
    """Why a trial is left out of this metric, or None."""
    if t["outcome"] is None:
        return "not finished"
    if t.get("outcome_class") == "infra_error" or t.get("excluded"):  # hangar's class (#166): retried, not counted
        return "infra_error"
    if t["outcome"] == "cancelled" or t.get("outcome_class") in ("cancelled", "human"):
        return "human" if t.get("outcome_class") == "human" else "cancelled"
    if t.get("task_invalid"):
        return "task_invalid"
    if t.get("contaminated"):
        return "contaminated"
    if t.get("drift") and not include_drift:
        return "drift"
    if metric != "resolved" and t.get("truncated"):
        return "truncated trace"
    if metric == "resolved" and resolved(t)[0] is None:
        return "no grade or verify"
    if metric != "resolved" and value(t, metric) is None:
        return f"unknown {metric}"
    return None


def value(t: dict[str, Any], metric: str) -> float | None:
    if metric == "resolved":
        return float(bool(resolved(t)[0]))
    v = t.get(metric)
    return None if v is None else float(v)


@cache
def mde(tasks: int, trials: int, power: float = 0.8) -> float | None:
    """The smallest lift (5 pp steps) the r1 simulation detects at `power` with this many paired tasks and trials."""
    for pp in range(5, 55, 5):
        if simulate_power(tasks, trials, pp / 100, sims=400) >= power:
            return pp / 100
    return None


@dataclass
class Comparison:
    experiment: str
    metric: str
    a: str
    b: str
    seed: int
    diff: Interval | None = None
    arms: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_task: dict[str, tuple[list[float], list[float]]] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)
    resolved_from: dict[str, int] = field(default_factory=dict)
    saturated: list[str] = field(default_factory=list)
    concordant: int = 0
    discordant: int = 0
    power: str = ""


def compare(trials: list[dict[str, Any]], metric: str, a: str, b: str, seed: int = 0, include_drift: bool = False,
            b_resamples: int = 10_000) -> Comparison:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    c = Comparison(trials[0]["experiment_id"] if trials else "", metric, a, b, seed)
    kept = []
    for t in trials:
        if t["variant"] not in (a, b):
            continue
        if why := exclusion(t, metric, include_drift):
            c.excluded[why] = c.excluded.get(why, 0) + 1
            continue
        kept.append(t)
        src = resolved(t)[1]
        c.resolved_from[src] = c.resolved_from.get(src, 0) + 1
        c.per_task.setdefault(t["task_id"], ([], []))[t["variant"] == b].append(value(t, metric) or 0.0)
    for arm in (a, b):
        ts = [t for t in kept if t["variant"] == arm]
        vals = [value(t, metric) or 0.0 for t in ts]
        k = sum(1 for t in ts if resolved(t)[0])
        cost = {}
        for t in ts:
            cost.setdefault(t["task_id"], []).append((t.get("cost_usd"), bool(resolved(t)[0])))
        c.arms[arm] = {"n": len(ts), "mean": sum(vals) / len(vals) if vals else None, "k": k,
                       "wilson": wilson(k, len(ts)) if metric == "resolved" else None,
                       "per_resolved": dollars_per_resolved(cost, b_resamples, seed) if cost else None}
    paired = {task: v for task, v in c.per_task.items() if v[0] and v[1]}
    if paired:
        c.diff = paired_bootstrap(paired, b_resamples, seed)
        means = [(sum(x) / len(x), sum(y) / len(y)) for x, y in paired.values()]
        c.discordant = sum(1 for x, y in means if x != y)
        c.concordant = len(means) - c.discordant
        if metric == "resolved":
            c.saturated = sorted(t for t, (x, y) in paired.items() if len(set(x + y)) == 1)
            n_trials = max(1, round(c.diff.n_trials / (2 * len(paired))))
            m = mde(len(paired), n_trials)
            c.power = (f"At {len(paired)} paired tasks x {n_trials} trials the minimum detectable lift at 80% power "
                       f"is about {m:.0%} (r1 simulation)." if m else
                       f"At {len(paired)} paired tasks x {n_trials} trials no lift up to 50 pp reaches 80% power.")
    return c


def _num(metric: str, v: float | None, signed: bool = False) -> str:
    if v is None:
        return "-"
    if metric == "resolved":
        return f"{v * 100:+.1f} pp" if signed else f"{v:.1%}"
    return f"{v:+.3f}" if signed else f"{v:.3f}"


def render(c: Comparison) -> str:
    """The comparison as markdown (readable in a terminal too)."""
    head = "resolved (95% Wilson)" if c.metric == "resolved" else "mean"
    out = [f"**{c.metric}**: {c.b} vs {c.a}, experiment `{c.experiment}`, seed {c.seed}", "",
           f"| variant | trials | {head} | $ / resolved (95%) |", "| --- | --- | --- | --- |"]
    for arm, s in c.arms.items():
        w, pr = s["wilson"], s["per_resolved"] if c.metric in ("resolved", "cost_usd") else None
        stat = _num(c.metric, s["mean"])
        if w:
            stat = f"{s['k']}/{s['n']} = {stat} [{w[0]:.1%}, {w[1]:.1%}]"
        dollars = f"{pr.estimate:.3f} [{pr.low:.3f}, {pr.high:.3f}]" + (f" ({pr.note})" if pr.note else "") if pr \
            else "-"
        out.append(f"| {arm} | {s['n']} | {stat} | {dollars} |")
    out.append("")
    if c.diff:
        d = c.diff
        pairs = f"; {c.concordant} concordant, {c.discordant} discordant tasks" if c.metric == "resolved" else ""
        out.append(f"Paired difference {c.b} - {c.a}: **{_num(c.metric, d.estimate, True)}**, 95% CI "
                   f"{_num(c.metric, d.low, True)} to {_num(c.metric, d.high, True)} (task bootstrap; "
                   f"{d.n_tasks} tasks, {d.n_trials} trials{pairs})." + (f" **{d.note}.**" if d.note else ""))
    else:
        out.append("No task has trials in both arms: nothing to compare.")
    if c.power:
        out.append(c.power)
    if c.metric == "resolved":
        out.append("Resolved: " + ", ".join(f"{src} for {n} trials" for src, n in sorted(c.resolved_from.items()))
                   + " (grader = exit 0 and applied; verify = hangar's after-turn verify when no grader ran).")
    out.append("Excluded: " + (", ".join(f"{why} {n}" for why, n in sorted(c.excluded.items())) or "none") + ".")
    if c.saturated:
        out.append(f"Saturated (same outcome in every trial of both arms, no information): {', '.join(c.saturated)}.")
    return "\n".join(out)


app = typer.Typer(help="Paired statistics over the data plane.", no_args_is_help=True)
DATA = typer.Option("~/.flightdeck/data", "--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane: directory or gs://")


@app.command("compare")
def compare_cmd(experiment: str, a: str = typer.Option("control", "--a"), b: str = typer.Option("treat", "--b"),
                metric: str = typer.Option("resolved", help="|".join(METRICS)), seed: int = 0,
                include_drift: bool = typer.Option(False, "--include-drift"), data: str = DATA) -> None:
    """Compare variant B against A on one metric, paired by task, with exclusions printed."""
    from flightdeck.dataplane.duck import connect

    trials = load_trials(connect(os.path.expanduser(data)), experiment)
    if not trials:
        raise typer.BadParameter(f"no trials of experiment {experiment!r} in {data}")
    typer.echo(render(compare(trials, metric, a, b, seed, include_drift)))
