"""`flightdeck report`: an experiment's markdown report from the data plane alone, and posting it as one GitHub PR or
issue comment that is updated in place (docs/reports.md).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

import typer

from flightdeck.dataplane.flatten import SECRET
from flightdeck.stats.compare import Comparison, compare, load_trials, render

LIMIT = 65_536  # GitHub's comment size limit
PROCESS = ("tool_calls", "wall_s")


def marker(exp_id: str) -> str:
    return f"<!-- flightdeck:report:{exp_id} -->"


def read_decision(path: Path) -> dict[str, Any]:
    """A pre-registered `decision.yaml`: flat `key: value` lines (metric, direction, margin, min_tasks)."""
    out: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, val = line.split("#", 1)[0].partition(":")
        if sep and val.strip():
            out[key.strip()] = val.strip()
    return out


def verdict(decision: dict[str, Any], c: Comparison) -> str:
    """The plain-words verdict from the pre-registered rule: better, non-inferior, worse, or no decision."""
    d, name = c.diff, c.metric
    if d is None:
        return "No decision: no task has trials in both arms."
    if d.n_tasks < int(decision.get("min_tasks", 10)) or d.note:
        return f"No decision: underpowered ({d.n_tasks} paired tasks, pre-registered minimum " \
               f"{decision.get('min_tasks', 10)})."
    sign = -1 if decision.get("direction", "higher") == "lower" else 1
    est, (lo, hi) = sign * d.estimate, sorted((sign * d.low, sign * d.high))
    margin = -abs(float(decision.get("margin", 0)))
    scale, unit = (100, " pp") if name == "resolved" else (1, "")
    nums = f"({est * scale:+.1f}{unit}, CI {lo * scale:+.1f}…{hi * scale:+.1f}, margin {margin * scale:+.1f})"
    if lo > 0:
        return f"{c.b} is better than {c.a} on {name} {nums}."
    if lo > margin:
        return f"{c.b} is non-inferior to {c.a} on {name} {nums}."
    if hi < margin:
        return f"{c.b} is worse than {c.a} on {name} {nums}."
    return f"No decision: the interval on {name} spans the margin {nums}."


def _short(values: set[Any]) -> str:
    vals = sorted(str(v) for v in values if v is not None)
    return ", ".join(f"`{v[:19]}…`" if v.startswith("sha256:") else v for v in vals) or "-"


def render_report(con: Any, exp_id: str, a: str = "control", b: str = "treat", decision: Path | None = None,
                  details: bool = False, hangar: str | None = None, seed: int = 0) -> str:
    """The report, from Parquet alone. Per-task rows and trial links only with `details` (public PRs: counts only)."""
    trials = load_trials(con, exp_id)
    if not trials:
        raise ValueError(f"no trials of experiment {exp_id!r} in the data plane")
    out = [marker(exp_id), f"## flightdeck report: `{exp_id}` ({b} vs {a})", ""]
    rule = read_decision(decision) if decision and decision.is_file() else None
    first = min((t["finished_epoch"] for t in trials if t["finished_epoch"]), default=None)
    if rule is None:
        out.append("**No verdict**: no pre-registered `decision.yaml`.")
    elif first is not None and decision and decision.stat().st_mtime > first:
        out.append("**No verdict**: `decision.yaml` was written after the first trial finished.")
    else:
        metric = rule.get("metric", "resolved")
        out.append(f"**Verdict**: {verdict(rule, compare(trials, metric, a, b, seed))}")
    digests = {t["manifest_digest"] for t in trials if t["manifest_digest"]}
    hangar_v = {d: json.loads(j).get("hangar", {}).get("version")
                for d, j in con.execute("select digest, json from manifests").fetchall() if d in digests}
    out += ["", "### Pins", "", f"| | {a} | {b} |", "| --- | --- | --- |"]
    for label, cols in (("harness", ("harness", "harness_version")), ("model", ("model_id",)),
                        ("environment", ("environment",)), ("config_digest", ("config_digest",)),
                        ("harness_digest", ("harness_digest",)), ("environment_digest", ("environment_digest",)),
                        ("grader", ("grade_command",)), ("hangar version", ("manifest_digest",))):
        cells = []
        for arm in (a, b):
            ts = [t for t in trials if t["variant"] == arm]
            if label == "hangar version":
                cells.append(_short({hangar_v.get(t["manifest_digest"]) for t in ts}))
            else:
                cells.append(_short({" ".join(str(t[k]) for k in cols if t[k] is not None) or None for t in ts}))
        out.append(f"| {label} | {cells[0]} | {cells[1]} |")
    out.append(f"\nBase SHAs: {len({t['base_sha'] for t in trials})} across {len({t['task_id'] for t in trials})} "
               "tasks (per task below).")
    outcome = compare(trials, "resolved", a, b, seed)
    out += ["", "### Outcome", "", render(outcome), "", "### Process", ""]
    out += [render(compare(trials, m, a, b, seed)) + "\n" for m in PROCESS]
    out += ["### Cost", "", render(compare(trials, "cost_usd", a, b, seed)), "", "### Exclusions and drift", ""]
    drift = [t for t in trials if t["drift"] and t["variant"] in (a, b)]
    out.append(f"{len(drift)} drifted trial(s) excluded from paired analysis (`--include-drift` keeps them).")
    out += [f"- `{t['trial_key']}`: {'; '.join(t['drift'])}" for t in drift] if details else []
    if details:
        out += ["", "<details><summary>Per task (discordant first)</summary>", "",
                f"| task | base | {a} resolved | {b} resolved | {b} - {a} |" + (" trials |" if hangar else ""),
                "| --- | --- | --- | --- | --- |" + (" --- |" if hangar else "")]
        rows = []
        for task, (x, y) in outcome.per_task.items():
            diff = (sum(y) / len(y) - sum(x) / len(x)) if x and y else None
            base = next(t["base_sha"] for t in trials if t["task_id"] == task) or "-"
            links = " ".join(f"[{t['variant'][0]}{t['trial']}]({hangar.rstrip('/')}/api/experiments/{exp_id}/trials/"
                             f"{t['trial_key']}/trace)" for t in trials if t["task_id"] == task) if hangar else None
            rows.append((diff in (0, None), task, f"| {task} | `{base[:8]}` | {int(sum(x))}/{len(x)} | "
                         f"{int(sum(y))}/{len(y)} | " + (f"{diff * 100:+.0f} pp" if diff is not None else "-")
                         + (f" | {links} |" if links is not None else " |")))
        out += [r for _, _, r in sorted(rows)] + ["", "</details>"]
    return "\n".join(out) + "\n"


def _gh(method: str, url: str, token: str, body: dict | None = None) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def post(text: str, target: str, token: str, full: str | None = None, gh: Any = _gh) -> str:
    """Create or update (by the report's marker) one comment on `owner/repo#n`, a PR or an issue. Returns its URL."""
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", target)
    if not m:
        raise ValueError(f"target must be owner/repo#number, got {target!r}")
    if SECRET.search(text):
        raise ValueError("the report contains a secret-looking string; refusing to post it")
    mark = text.split("\n", 1)[0]
    if not mark.startswith("<!-- flightdeck:report:"):
        raise ValueError("not a flightdeck report (no marker on its first line)")
    if len(text) > LIMIT:
        note = f"\n\n*Clipped at GitHub's {LIMIT:,}-character limit; full report: {full or 'not saved'}.*\n"
        text = text[: LIMIT - len(note)] + note
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com") + f"/repos/{m[1]}/issues"
    page, existing = 1, None
    while existing is None:
        batch = gh("GET", f"{api}/{m[2]}/comments?per_page=100&page={page}", token)
        existing = next((c for c in batch if (c.get("body") or "").startswith(mark)), None)
        if len(batch) < 100:
            break
        page += 1
    if existing:
        return gh("PATCH", f"{api}/comments/{existing['id']}", token, {"body": text})["html_url"]
    return gh("POST", f"{api}/{m[2]}/comments", token, {"body": text})["html_url"]


app = typer.Typer(help="Markdown reports, posted where the change is reviewed.", no_args_is_help=True)
POST = typer.Option(None, "--post", help="owner/repo#n: post as a PR or issue comment (token: GITHUB_TOKEN).")
DECISION = typer.Option(None, help="Pre-registered decision.yaml; the verdict needs it.")
DETAILS = typer.Option(False, help="Per-task rows and trial links (keep off for public repos).")
HANGAR = typer.Option(None, envvar="HANGAR_URL", help="Hangar base URL for trial links.")
OUT = typer.Option(None, help="Also write the report here.")
DATA = typer.Option("~/.flightdeck/data", "--data", envvar="FLIGHTDECK_DATA_URI")


def _post(text: str, target: str, full: str | None) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise typer.BadParameter("set GITHUB_TOKEN (issues:write / pull_requests:write on the target repo)")
    try:
        typer.echo(post(text, target, token, full))
    except ValueError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


@app.command("experiment")
def report_experiment(experiment: str, a: str = typer.Option("control", "--a", "--baseline"),
                      b: str = typer.Option("treat", "--b"), decision: Path = DECISION, details: bool = DETAILS,
                      hangar: str = HANGAR, out: Path = OUT, post_to: str = POST, seed: int = 0,
                      data: str = DATA) -> None:
    """Render an experiment's report from the data plane; print it, write it, post it."""
    from flightdeck.dataplane.duck import connect

    text = render_report(connect(os.path.expanduser(data)), experiment, a, b, decision, details, hangar, seed)
    if out:
        out.write_text(text, encoding="utf-8")
    if post_to:
        _post(text, post_to, str(out) if out else None)
    elif not out:
        typer.echo(text)


@app.command("post")
def report_post(report: Path, to: str = typer.Option(..., "--to", help="owner/repo#n")) -> None:
    """Post (or update in place) a rendered report as a PR or issue comment."""
    _post(report.read_text(encoding="utf-8"), to, str(report))
