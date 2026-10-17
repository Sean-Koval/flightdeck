"""`flightdeck metrics weekly`: the team's weekly scorecard from the data plane, with a 4-week trailing view.

docs/metrics.md defines every metric; `weekly.sql` is its only implementation. Hangar's standup line and digest read
`<reports>/weekly/latest.json` (`flightdeck.weekly/v1`, `weekly.schema.json`) and never recompute.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from typing import Any

import duckdb
import fsspec
import typer

from flightdeck.dataplane.duck import connect
from flightdeck.stats.core import wilson

SCHEMA = "flightdeck.weekly/v1"
DOCS = "https://sean-koval.github.io/flightdeck/metrics/"
LABELS = {"yield": "Agent PR yield", "agent_share": "Agent share of merged PRs", "review_wait": "Review wait",
          "green_to_merge": "Green to merge", "steer_rate": "Human steers per merged PR", "abandon": "Abandon rate",
          "revert": "14-day revert rate", "cost_per_merged_pr": "Cost per merged PR",
          "active_delegators": "Active delegators", "infra_errors": "Infra-error runs (excluded)"}
TARGETS = {"yield": ">= 60%", "review_wait": "p50 < 4 h, p90 < 24 h", "abandon": "< 25%", "active_delegators": "6 of 6"}


def week_start(week: str) -> date:
    year, _, num = week.partition("-W")
    return date.fromisocalendar(int(year), int(num), 1)


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _lit(v: str | None) -> str:
    return "null" if v is None else "'" + v.replace("'", "''") + "'"


def compute(con: duckdb.DuckDBPyConnection, week: str, person: str | None = None, repo: str | None = None) -> dict:
    """Every metric for one week and scope."""
    ws = week_start(week)
    for name, value in {"ws": f"timestamptz '{ws} 00:00:00+00'", "we": f"timestamptz '{ws + timedelta(7)} 00:00:00+00'",
                        "person": _lit(person), "repo": _lit(repo)}.items():
        con.execute(f"set variable {name} = {value}")
    out: dict[str, Any] = {}
    for m in LABELS:
        rel = con.sql(f"from weekly_{m}")
        d = dict(zip(rel.columns, rel.fetchone() or (), strict=True))
        if "k" in d:
            d |= {"rate": d["k"] / d["n"], "ci95": list(wilson(d["k"], d["n"]))} if d["n"] else {"rate": None,
                                                                                               "ci95": None}
        out[m] = {k: float(v) if isinstance(v, float) else v for k, v in d.items()}
    out["abandon"]["by_reason"] = dict(con.sql("from weekly_abandon_reasons").fetchall())
    return out


def build(data: str, week: str, person: str | None = None, repo: str | None = None) -> dict:
    """A `flightdeck.weekly/v1` document: the week, and the 4 weeks ending with it."""
    con = connect(data)
    con.execute(files(__package__).joinpath("weekly.sql").read_text(encoding="utf-8"))
    weeks = [iso_week(week_start(week) - timedelta(weeks=i)) for i in (3, 2, 1, 0)]
    trailing = [{"week": w, "metrics": compute(con, w, person, repo)} for w in weeks]
    ws = week_start(week)
    return {"schema": SCHEMA, "week": week, "start": ws.isoformat(), "end": (ws + timedelta(7)).isoformat(),
            "scope": {"person": person, "repo": repo}, "metrics": trailing[-1]["metrics"], "trailing": trailing}


def cell(m: str, d: dict) -> str:
    """One metric as text; rates always carry their interval and counts."""
    if "rate" in d:
        return "- (0)" if d["n"] == 0 else f"{d['rate']:.0%} ({d['ci95'][0]:.0%}-{d['ci95'][1]:.0%}, {d['k']}/{d['n']})"
    if "p50_h" in d:
        return "- (0)" if d["n"] == 0 else f"p50 {d['p50_h']:.1f} h, p90 {d['p90_h']:.1f} h (n={d['n']})"
    if m == "active_delegators":
        return f"{d['value']} of {d['n']} active"
    if m == "infra_errors":
        return str(d["value"])
    if d["value"] is None:  # no merged PRs, or none with a recorded cost
        return f"- (n={d['n']})"
    return (f"${d['value']:.2f}" if m.startswith("cost") else f"{d['value']:.1f}") + f" (n={d['n']})"


def markdown(doc: dict) -> str:
    weeks = [t["week"] for t in doc["trailing"]]
    scope = ", ".join(f"{k} {v}" for k, v in doc["scope"].items() if v) or "team"
    lines = [f"## Weekly agent metrics, {doc['week']} ({scope})", "",
             "| Metric | Target | " + " | ".join(weeks) + " |", "|---|---|" + "---|" * len(weeks)]
    for m, label in LABELS.items():
        row = " | ".join(cell(m, t["metrics"][m]) for t in doc["trailing"])
        lines.append(f"| [{label}]({DOCS}#{m.replace('_', '-')}) | {TARGETS.get(m, '')} | {row} |")
    reasons = ", ".join(f"{r} {n}" for r, n in doc["metrics"]["abandon"]["by_reason"].items()) or "none"
    return "\n".join([*lines, "", f"Abandoned by reason: {reasons}. Rates: 95% Wilson intervals."]) + "\n"


def slack(doc: dict) -> dict:
    text = "\n".join(f"*{label}*: {cell(m, doc['metrics'][m])}" for m, label in LABELS.items())
    return {"blocks": [{"type": "header", "text": {"type": "plain_text", "text": f"Agent metrics {doc['week']}"}},
                       {"type": "section", "text": {"type": "mrkdwn", "text": text}}]}


app = typer.Typer(help="Team metrics over the data plane (docs/metrics.md).", no_args_is_help=True)


@app.command("weekly")
def weekly(
    week: str = typer.Option(None, help="ISO week, e.g. 2026-W45 (default: last complete week)."),
    fmt: str = typer.Option("md", "--format", help="md, json or slack (Block Kit JSON)."),
    person: str = typer.Option(None, help="Only this person's jobs (share with that person and admins only)."),
    repo: str = typer.Option(None, help="Only this repository (owner/repo)."),
    data: str = typer.Option(..., "--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane root."),
    reports: str = typer.Option(None, envvar="FLIGHTDECK_REPORTS_URI", help="Write reports/weekly/ here (private)."),
) -> None:
    """The weekly scorecard; team-wide runs with --reports also write <week>.json, <week>.md and latest.json."""
    week = week or iso_week(datetime.now(UTC).date() - timedelta(weeks=1))
    doc = build(os.path.expanduser(data), week, person, repo)
    md, body = markdown(doc), json.dumps(doc, indent=1, default=str)
    typer.echo({"md": md, "json": body, "slack": json.dumps(slack(doc), indent=1)}[fmt])
    if reports and not (person or repo):  # per-person views stay out of the shared files
        fs, root = fsspec.core.url_to_fs(os.path.expanduser(reports))
        fs.makedirs(f"{root}/weekly", exist_ok=True)
        for name, text in {f"{week}.json": body, f"{week}.md": md, "latest.json": body}.items():
            fs.pipe_file(f"{root}/weekly/{name}", text.encode())
