"""`flightdeck stats compare`: one experiment's variants, paired by task, from the data plane (docs/statistics.md).

Every comparison prints its exclusions with counts and the resolved definition it used; saturated tasks are listed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import duckdb
import typer

from flightdeck.stats.core import Interval, dollars_per_resolved, paired_bootstrap, simulate_power, wilson

METRICS = ("resolved", "cost_usd", "tool_calls", "wall_s")


def load_trials(con: duckdb.DuckDBPyConnection, exp_id: str) -> list[dict[str, Any]]:
    """One dict per trial of an experiment or run set (ids joined by '+'), with the trials the cache reused for it
    (`trial_reuse`; `reused_age_days` set): its `runs` row, its grade and its tool-call count, each run_id once."""
    ids = exp_id.split("+")
    have = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    reuse = ("select run_id, min(age_days) as age from trial_reuse where experiment_id = ? group by 1"
             if "trial_reuse" in have else "select null::varchar as run_id, null::double as age where ? is null")
    rel = con.execute(f"with u as ({reuse}) select r.* exclude (started_at, finished_at), epoch(r.finished_at) as "
                      "finished_epoch, epoch(r.finished_at) - epoch(r.started_at) as wall_s, g.exit_code as "
                      "grade_exit, g.applied as grade_applied, g.command as grade_command, (select case when count(*) "
                      "> 0 then count(*) filter (s.kind = 'tool.call') end from spans s where s.run_id = r.run_id) as "
                      "tool_calls, u.age as reused_age_days from runs r left join grades g using (run_id) left join u "
                      f"using (run_id) where r.experiment_id in ({', '.join('?' * len(ids))}) or u.run_id is not null "
                      "qualify row_number() over (partition by r.run_id) = 1 order by task_id, variant, trial",
                      [exp_id, *ids])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]


def resolved(t: dict[str, Any]) -> tuple[bool | None, str]:
    """Resolved and the column it came from: the grader when it ran, else hangar's after-turn verify."""
    if t.get("grade_exit") is not None:
        return t["grade_exit"] == 0 and bool(t["grade_applied"]), "grader"
    return t.get("verify_passed"), "verify"


def exclusion(t: dict[str, Any], metric: str, include_drift: bool = False) -> str | None:
    """Why a trial is left out of this metric (the first reason that applies), or None."""
    cls, outcome = t.get("outcome_class"), t["outcome"]
    reasons = (("not finished", outcome is None),
               ("infra_error", cls == "infra_error" or t.get("excluded")),  # hangar's class (#166): retried, uncounted
               ("human", cls == "human"), ("cancelled", outcome == "cancelled" or cls == "cancelled"),
               ("task_invalid", t.get("task_invalid")), ("contaminated", t.get("contaminated")),
               ("drift", t.get("drift") and not include_drift),
               ("truncated trace", metric != "resolved" and t.get("truncated")),
               ("no grade or verify", metric == "resolved" and resolved(t)[0] is None),
               (f"unknown {metric}", metric != "resolved" and value(t, metric) is None))
    return next((why for why, hit in reasons if hit), None)


def value(t: dict[str, Any], metric: str) -> float | None:
    return float(bool(resolved(t)[0])) if metric == "resolved" else None if t.get(metric) is None else float(t[metric])


@cache
def mde(tasks: int, trials: int, power: float = 0.8) -> float | None:
    """The smallest lift (5 pp steps) simulate_power detects at `power` with this many paired tasks and trials."""
    return next((pp / 100 for pp in range(5, 55, 5) if simulate_power(tasks, trials, pp / 100, 400) >= power), None)


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
    reused: list[float] = field(default_factory=list)  # ages in days of the trials the cache reused
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
        c.reused += [t["reused_age_days"]] if t.get("reused_age_days") is not None else []
        c.resolved_from[resolved(t)[1]] = c.resolved_from.get(resolved(t)[1], 0) + 1
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
                       "per_resolved": dollars_per_resolved(cost, b_resamples, seed) if any(
                           c is not None for v in cost.values() for c, _ in v) else None}  # none known: no ratio
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
            c.power = (f"At {len(paired)} paired tasks × {n_trials} trials the minimum detectable lift at 80% power "
                       f"is about {m * 100:.0f} pp (simulated)." if m else
                       f"At {len(paired)} paired tasks × {n_trials} trials no lift up to 50 pp reaches 80% power.")
    return c


def fmt(metric: str, v: float | None, signed: bool = False) -> str:
    """One number the brand book's way: `31%` or `+21.2 pp`, `$0.42` or `−$0.09`, `174.9 s`, `3.0 calls`; a minus
    sign, never a hyphen; an em dash for none."""
    if v is None:
        return "—"
    sign = "+" if signed else ""
    return {"resolved": f"{v * 100:+.1f} pp" if signed else f"{v:.0%}", "wall_s": f"{v:{sign}.1f} s",
            "cost_usd": f"{'+-'[v < 0] if signed else ''}${abs(v):.2f}", "tool_calls": f"{v:{sign}.1f} calls"
            }[metric].replace("-", "−")


def ratio(k: int, n: int) -> str:
    """`10 of 32 (31%)`: never a slash."""
    return f"{k} of {n} ({k / n:.0%})" if n else "—"


def render(c: Comparison, full: bool = True) -> str:
    """The comparison as markdown; `plain` turns it into the terminal readout. `full` adds the header (metric, arms,
    experiment, seed) and the exclusions, which the report prints once for all its tables."""
    out = [f"**{c.metric}**: {c.b} vs {c.a}, experiment `{c.experiment}`, seed {c.seed}", ""] if full else []
    per = c.metric in ("resolved", "cost_usd")  # $ per resolved task is a ratio of cost to outcome: not for process
    head = ["variant", "trials", *(("resolved", "95% Wilson") if c.metric == "resolved" else ("mean",))]
    head += ["$ per resolved (95%)"] if per else []
    out += ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for arm, s in c.arms.items():
        w, pr = s["wilson"], s["per_resolved"] if per else None
        row = [arm, str(s["n"])] + ([ratio(s["k"], s["n"]), f"{w[0]:.0%} to {w[1]:.0%}"] if w else
                                    [fmt(c.metric, s["mean"])])
        row += [f"{fmt('cost_usd', pr.estimate)} ({fmt('cost_usd', pr.low)} to {fmt('cost_usd', pr.high)})"
                + (f" ({pr.note})" if pr.note else "") if pr else "—"] if per else []
        out.append("| " + " | ".join(row) + " |")
    if d := c.diff:  # the notes below the table are paragraphs of their own, so GitHub does not run them together
        pairs = f"; {c.concordant} concordant, {c.discordant} discordant tasks" if c.metric == "resolved" else ""
        notes = [f"Paired difference {c.b} − {c.a}: **{fmt(c.metric, d.estimate, True)}** (95% CI "
                 f"{fmt(c.metric, d.low, True)} to {fmt(c.metric, d.high, True)}; task bootstrap, "
                 f"{d.n_tasks} tasks, {d.n_trials} trials{pairs})." + (f" **{d.note}.**" if d.note else "")]
    else:
        notes = ["No task has trials in both arms: nothing to compare."]
    notes += [c.power] if c.power else []
    notes += ["Resolved: " + ", ".join(f"{src} for {n} trials" for src, n in sorted(c.resolved_from.items()))
              + " (grader = exit 0 and applied; verify = hangar's after-turn verify when no grader ran)."
              ] if c.metric == "resolved" else []
    notes += [f"Reused from the trial cache: {len(c.reused)} of {sum(s['n'] for s in c.arms.values())} trials, "
              f"{min(c.reused):.0f} to {max(c.reused):.0f} days old."] if c.reused else []
    notes += [exclusions(c)] if full else []
    notes += [f"Saturated (same outcome in every trial of both arms, no information): {', '.join(c.saturated)}."
              ] if c.saturated else []
    return "\n".join([*out, "", "\n\n".join(notes)])


def exclusions(c: Comparison, also: Comparison | None = None) -> str:
    """`Excluded: cancelled 1, drift 1.`, and with `also` (a process metric) the extra reasons it adds."""
    extra = {k: v for k, v in also.excluded.items() if k not in c.excluded} if also else {}
    return ("Excluded: " + (", ".join(f"{why} {n}" for why, n in sorted(c.excluded.items())) or "none")
            + (f"; from the process and cost tables also {', '.join(f'{w} {n}' for w, n in sorted(extra.items()))}"
               if extra else "") + ".")


def plain(md: str) -> str:
    """Markdown as a terminal readout: no emphasis, code ticks, headings marks or HTML comments; pipe tables as
    aligned columns, headers in capitals, numbers right-aligned."""
    out, rows = [], []
    for line in [*md.splitlines(), ""]:
        line = re.sub(r"\*\*|`", "", line)
        if line.startswith("|") and not line.startswith("| ---"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cells if rows else [c.upper() for c in cells])
        elif not line.startswith(("|", "<!--")):
            if rows:
                cols = list(zip(*rows, strict=True))
                num = [all(re.match(r"[-+−—$\d]|$", x) for x in c[1:]) for c in cols]
                out += ["  ".join((x.rjust if num[i] else x.ljust)(max(map(len, cols[i]))) for i, x in enumerate(r))
                        .rstrip() for r in rows]
                rows = []
            out.append(line.lstrip("#").lstrip() if line.startswith("#") else line)
    return "\n".join(out[:-1])


app = typer.Typer(help="Compare the arms of an experiment, paired by task.", no_args_is_help=True)
DATA = typer.Option("~/.flightdeck/data", "--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane: directory or gs://")
MD = typer.Option(False, "--md", help="Print markdown (for an issue or a file) instead of the terminal readout.")
BASELINE = typer.Option("control", "--baseline", "--a", help="The arm that runs today; the verdict is against it.")
CANDIDATE = typer.Option("candidate", "--candidate", "--b", help="The arm with the change under judgement.")


@app.command("compare")
def compare_cmd(experiment: str, a: str = BASELINE, b: str = CANDIDATE,
                metric: str = typer.Option("resolved", help="|".join(METRICS)), seed: int = 0,
                include_drift: bool = typer.Option(False, "--include-drift"), data: str = DATA, md: bool = MD) -> None:
    """Compare the candidate arm against the baseline on one metric, paired by task, with exclusions printed."""
    from flightdeck.dataplane.duck import connect

    trials = load_trials(connect(os.path.expanduser(data)), experiment)
    if not trials:
        raise typer.BadParameter(f"no trials of experiment {experiment!r} in {data}")
    text = render(compare(trials, metric, a, b, seed, include_drift))
    typer.echo(text if md else plain(text))
