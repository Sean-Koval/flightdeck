"""`flightdeck report`: an experiment's markdown report from the data plane alone, and posting it as one GitHub PR or
issue comment that is updated in place (docs/reports.md).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import typer

from flightdeck import judges
from flightdeck.dataplane.flatten import SECRET
from flightdeck.stats.compare import Comparison, compare, exclusion, load_trials, render

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


def committed_at(path: Path) -> float | None:
    """The commit time of the last commit that changed `path`, or None when it isn't committed as it now is."""
    git = lambda *a: subprocess.run(["git", "-C", str(path.parent), *a], capture_output=True, text=True)  # noqa: E731
    log = git("log", "-1", "--format=%ct", "--", path.name)
    if log.returncode or not log.stdout.strip() or git("diff", "--quiet", "HEAD", "--", path.name).returncode:
        return None
    return float(log.stdout)


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
    rubric = read_decision(decision).get("rubric") if decision and decision.is_file() else None
    if rubric and decision and (st := judges.status(decision.parent / rubric)) != "usable":
        raise ValueError(f"decision.yaml uses rubric {rubric}, which is {st}: only a usable rubric (kappa's "
                         "lower bound >= 0.6, docs/judges.md) may decide")
    trials = load_trials(con, exp_id)
    if not trials:
        raise ValueError(f"no trials of experiment {exp_id!r} in the data plane")
    out = [marker(exp_id), f"## flightdeck report: `{exp_id}` ({b} vs {a})", ""]
    rule = read_decision(decision) if decision and decision.is_file() else None
    first = min((t["finished_epoch"] for t in trials if t["finished_epoch"]), default=None)
    when = committed_at(decision) if rule is not None and decision else None
    if rule is None:
        out.append("**No verdict**: no pre-registered `decision.yaml`.")
    elif when is None:
        out.append("**No verdict**: `decision.yaml` is not committed as it is (its commit time pre-registers it).")
    elif first is not None and when > first:
        out.append("**No verdict**: `decision.yaml` was committed after the first trial finished.")
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
    out += ["### Cost", "", render(compare(trials, "cost_usd", a, b, seed)), "", "### Behavior specs", ""]
    out += spec_rates(con, [t for t in trials if not exclusion(t, "resolved")], a, b)
    out += ["", "### Exclusions and drift", ""]
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


def spec_rates(con: Any, trials: list[dict[str, Any]], a: str, b: str) -> list[str]:
    """Pass rate per behavior spec per variant, from `spec_results` over the trials the Outcome table counts."""
    arm = {t["run_id"]: t["variant"] for t in trials}
    has = con.execute("select count(*) from information_schema.tables where table_name = 'spec_results'").fetchone()
    rows = con.execute("select spec_source, spec_id, run_id, result from spec_results where scope = 'turn' and "
                       "result in ('pass', 'fail')").fetchall() if has and has[0] else []
    rates: dict[tuple[str, str], dict[str, list[int]]] = {}
    for src, sid, rid, result in rows:
        if rid in arm:
            k = rates.setdefault((src, sid), {a: [0, 0], b: [0, 0]})[arm[rid]]
            k[0], k[1] = k[0] + (result == "pass"), k[1] + 1
    if not rates:
        return ["No behavior-spec results for these trials (`flightdeck check run` writes them)."]
    cell = lambda k: f"{k[0]}/{k[1]} = {k[0] / k[1]:.0%}" if k[1] else "-"  # noqa: E731
    return [f"| spec | {a} pass | {b} pass |", "| --- | --- | --- |"] + [
        f"| {sid}" + (f" ({src})" if src != "spec" else "") + f" | {cell(r[a])} | {cell(r[b])} |"
        for (src, sid), r in sorted(rates.items())]


def _gh(method: str, url: str, token: str, body: dict | None = None) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def post(text: str, target: str, token: str, full: str | None = None, gist: bool = False, gh: Any = _gh) -> str:
    """Create or update (by the report's marker) one comment on `owner/repo#n`, a PR or an issue. Returns its URL.
    A report over GitHub's limit is clipped and links `full` (a URL: the report in the private data repo), or with
    `gist` a secret gist of it; never a local path."""
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", target)
    if not m:
        raise ValueError(f"target must be owner/repo#number, got {target!r}")
    if SECRET.search(text):
        raise ValueError("the report contains a secret-looking string; refusing to post it")
    mark = text.split("\n", 1)[0]
    if not mark.startswith("<!-- flightdeck:report:"):
        raise ValueError("not a flightdeck report (no marker on its first line)")
    if full and not full.startswith("https://"):
        raise ValueError(f"--full-url must be an https:// URL others can open, not {full!r}")
    root = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if len(text) > LIMIT:
        if gist and not full:
            full = gh("POST", f"{root}/gists", token, {"public": False, "description": mark[5:-4],
                                                       "files": {"report.md": {"content": text}}})["html_url"]
        where = f"[full report]({full})" if full else "the full report is not linked (`--full-url` or `--gist`)"
        note = f"\n\n*Clipped at GitHub's {LIMIT:,}-character limit; {where}.*\n"
        text = text[: LIMIT - len(note)] + note
    api = f"{root}/repos/{m[1]}/issues"
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
FULL = typer.Option(None, "--full-url", help="Where the full report is (https), linked when a comment is clipped.")
GIST = typer.Option(False, "--gist", help="Link a clipped comment to a secret gist of the full report.")
DATA = typer.Option("~/.flightdeck/data", "--data", envvar="FLIGHTDECK_DATA_URI")


def _post(text: str, target: str, full: str | None, gist: bool) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise typer.BadParameter("set GITHUB_TOKEN (issues:write / pull_requests:write on the target repo)")
    try:
        typer.echo(post(text, target, token, full, gist))
    except ValueError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


@app.command("experiment")
def report_experiment(experiment: str, a: str = typer.Option("control", "--a", "--baseline"),
                      b: str = typer.Option("treat", "--b"), decision: Path = DECISION, details: bool = DETAILS,
                      hangar: str = HANGAR, out: Path = OUT, post_to: str = POST, seed: int = 0,
                      data: str = DATA, full_url: str = FULL, gist: bool = GIST) -> None:
    """Render an experiment's report from the data plane; print it, write it, post it."""
    from flightdeck.dataplane.duck import connect

    text = render_report(connect(os.path.expanduser(data)), experiment, a, b, decision, details, hangar, seed)
    if out:
        out.write_text(text, encoding="utf-8")
    if post_to:
        _post(text, post_to, full_url, gist)
    elif not out:
        typer.echo(text)


@app.command("post")
def report_post(report: Path, to: str = typer.Option(..., "--to", help="owner/repo#n"), full_url: str = FULL,
                gist: bool = GIST) -> None:
    """Post (or update in place) a rendered report as a PR or issue comment."""
    _post(report.read_text(encoding="utf-8"), to, full_url, gist)
