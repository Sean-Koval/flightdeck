"""`flightdeck holdout`: sealed holdout custody (docs/holdouts.md, ADR 0006).

Tower's practice, ported: a manifest lists every sealed file with its sha256 and scoring refuses a
file whose hash changed (its `aw.rules_report.check_manifest`); independent writers work from a brief without reading
the repository (`server/evals/briefs/blind_v*_writer_*.txt`); a sealed set is scored once, on an approver's go-ahead.
Everything lives under one holdouts directory of the private data repository: `manifest.json`, `briefs/` and
`results/` are committed; `incoming/` and `sealed/` hold task directories that are encrypted at rest in the team
bucket and never committed (ADR 0002).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import typer

from flightdeck.tasks.format import TaskError, load_task, write_digest

CANARY = re.compile(r"FLIGHTDECK-CANARY-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class CustodyError(Exception):
    """A custody rule refuses the operation; the message names the rule."""


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(root: Path) -> dict[str, Any]:
    m = root / "manifest.json"
    return json.loads(m.read_text()) if m.is_file() else {"files": {}, "sets": {}}


def save(root: Path, doc: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


def check_manifest(root: Path, doc: dict[str, Any], prefix: str = "") -> None:
    """Refuse when a listed file (under `prefix`) is missing or its sha256 differs from the manifest's."""
    for key, want in sorted(doc["files"].items()):
        if key.startswith(prefix):
            p = root / key
            got = sha256(p) if p.is_file() else "missing"
            if got != want:
                raise CustodyError(f"{key} has changed since it was sealed (manifest {want}, now {got}); refusing")


def seal(root: Path, doc: dict[str, Any], name: str, writers: dict[str, str], fresh_after: str) -> list[str]:
    """Move each writer's `incoming/<writer>/<task>/` into `sealed/<name>/` unread: check it loads, is marked sealed
    and was mined after `fresh_after`; append a canary to instruction.md and tests/test.sh; hash every file."""
    if name in doc["sets"]:
        raise CustodyError(f"set {name} exists ({doc['sets'][name]['status']}): sets are spent once, write a new one")
    todo = []
    for w in writers:
        dirs = sorted(p.parent for p in (root / "incoming" / w).glob("*/task.toml"))
        if not dirs:
            raise CustodyError(f"no tasks under {root / 'incoming' / w}")
        for d in dirs:
            t = load_task(d)
            if not t.sealed:
                raise CustodyError(f"{d}: task.toml needs [flightdeck] sealed = true")
            if str(t.flightdeck.get("mined_after") or "") <= fresh_after:
                raise CustodyError(f"{d}: [flightdeck] mined_after must be after {fresh_after} (the knowledge "
                                   "snapshot and the model's training cutoff)")
            todo.append((w, d))
    if len({d.name for _, d in todo}) < len(todo):
        raise CustodyError("two writers used the same task id; rename one")
    canaries, tasks = {}, {}
    for w, d in todo:
        c = f"FLIGHTDECK-CANARY-{uuid.uuid4()}"
        with (d / "instruction.md").open("a") as f:
            f.write(f"\n<!-- {c} -->\n")
        with (d / "tests" / "test.sh").open("a") as f:
            f.write(f"\n# {c}\n")
        write_digest(d)
        dest = root / "sealed" / name / d.name
        shutil.move(d, dest)
        canaries[d.name], tasks[d.name] = c, w
        for p in sorted(dest.rglob("*")):
            if p.is_file():
                doc["files"][p.relative_to(root).as_posix()] = sha256(p)
    doc["sets"][name] = {"tasks": tasks, "writers": writers, "canaries": canaries, "status": "sealed",
                         "sealed_at": _now(), "fresh_after": fresh_after, "scored_at": None, "scored_by": None,
                         "scored_against": None}
    return sorted(tasks)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def score(root: Path, doc: dict[str, Any], name: str, against: str, approver: str, author: str, by: str,
          trials: list[dict[str, Any]], min_hangar: str) -> dict[str, Any]:
    """Check every rule, then record the set's one scoring. `trials` are the run set's `load_trials` rows, each with
    its `hangar_version` from the trial's manifest."""
    from flightdeck.stats.compare import exclusion, resolved
    from flightdeck.stats.core import wilson

    s = doc["sets"].get(name)
    if not s:
        raise CustodyError(f"no set {name} in the manifest")
    if s["status"] != "sealed":
        raise CustodyError(f"set {name} is {s['status']}" + (f" (scored {s['scored_at']} by {s['scored_by']} against "
                           f"{s['scored_against']})" if s["status"] == "scored" else "") + ": a set is scored once")
    if approver in (author, by) or author in s["writers"].values():
        raise CustodyError("the approver must differ from the candidate's author and from whoever runs the scoring, "
                           "and no writer of the set may be the candidate's author")
    check_manifest(root, doc, f"sealed/{name}/")
    mine = [t for t in trials if t["task_id"] in s["tasks"]]
    wrong = sorted({t.get("harness_digest") or t.get("config_digest") or "none" for t in mine} - {against})
    old = sorted({t.get("hangar_version") or "unknown" for t in mine
                  if _version(t.get("hangar_version") or "") < _version(min_hangar)})
    missing = sorted(set(s["tasks"]) - {t["task_id"] for t in mine})
    if not mine or wrong or old or missing:
        raise CustodyError(f"the run set must cover every task of {name}, pinned to {against} (found "
                           f"{wrong or 'no other digest'}), on hangar >= {min_hangar} with grader isolation (found "
                           f"{old or 'none older'}); tasks missing: {missing or 'none'}")
    kept = [t for t in mine if not exclusion(t, "resolved")]
    k = sum(1 for t in kept if resolved(t)[0])
    low, high = wilson(k, len(kept))
    s.update(status="scored", scored_at=_now(), scored_by=by, scored_against=against, approved_by=approver)
    return {"set": name, "against": against, "approved_by": approver, "scored_by": by, "trials": len(mine),
            "excluded": len(mine) - len(kept), "resolved": k, "n": len(kept), "rate": k / len(kept) if kept else None,
            "wilson95": [low, high], "per_task": {t: [bool(resolved(x)[0]) for x in kept if x["task_id"] == t]
                                                  for t in sorted(s["tasks"])}}


def canary_hits(texts: list[tuple[str, str]], doc: dict[str, Any]) -> list[dict[str, str]]:
    """Canary strings found in (where, text) pairs, with the set and task each belongs to (`?` when unknown)."""
    owner = {c: (n, t) for n, s in doc["sets"].items() for t, c in s.get("canaries", {}).items()}
    return [{"canary": c, "where": where, "set": owner.get(c, ("?", "?"))[0], "task": owner.get(c, ("?", "?"))[1]}
            for where, text in texts for c in sorted(set(CANARY.findall(text or "")))]


# --- CLI ---------------------------------------------------------------------------------------------------------

app = typer.Typer(help="Sealed holdouts: briefs, seal, canary scan, score once.", no_args_is_help=True)
ROOT = Annotated[Path, typer.Option("--holdouts", help="The holdouts directory of the private data repo.")]


def _run(fn, *a):
    try:
        return fn(*a)
    except (CustodyError, TaskError) as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


@app.command()
def brief(name: str, writers: int = 2, family: str = "regression", count: int = 20, mined_after: str = "",
          holdouts: ROOT = Path("holdouts")) -> None:
    """Write one brief per blind writer to briefs/<set>_writer_<x>.txt."""
    template = (files("flightdeck.tasks") / "holdout_brief.txt").read_text()
    (holdouts / "briefs").mkdir(parents=True, exist_ok=True)
    for w in "abcdefgh"[:writers]:
        out = holdouts / "briefs" / f"{name}_writer_{w}.txt"
        out.write_text(template.format(set=name, writer=w, family=family, count=count, mined_after=mined_after))
        typer.echo(f"wrote {out}")


@app.command("seal")
def seal_cmd(name: str, writer: Annotated[list[str], typer.Option(help="<id>=<harness or person>, once per writer")],
             fresh_after: Annotated[str, typer.Option(help="YYYY-MM-DD: the later of snapshot and model cutoff")],
             holdouts: ROOT = Path("holdouts")) -> None:
    """Seal the writers' incoming tasks as one set and record it in the manifest (commit manifest.json alone)."""
    doc = load(holdouts)
    tasks = _run(seal, holdouts, doc, name, dict(w.split("=", 1) for w in writer), fresh_after)
    save(holdouts, doc)
    typer.echo(f"sealed {len(tasks)} tasks as {name}: commit manifest.json on its own, encrypt and upload sealed/")


@app.command("score")
def score_cmd(name: str, run_set: Annotated[str, typer.Option(help="The run set that ran the set's tasks.")],
              against: Annotated[str, typer.Option(help="The candidate's harness_digest (or config_digest).")],
              approve: Annotated[str, typer.Option(help="GitHub login of the approver.")],
              author: Annotated[str, typer.Option(help="GitHub login of the candidate change's author.")],
              by: Annotated[str, typer.Option(envvar="FLIGHTDECK_AUTHOR", help="Who runs the scoring.")],
              data: Annotated[str, typer.Option(envvar="FLIGHTDECK_DATA_URI", help="Data plane root.")],
              min_hangar: str = "0", holdouts: ROOT = Path("holdouts")) -> None:
    """Score a sealed set once: results/<set>.json and the manifest are committed together."""
    import os

    from flightdeck.dataplane.duck import connect
    from flightdeck.stats.compare import load_trials

    con = connect(os.path.expanduser(data))
    trials = load_trials(con, run_set)
    versions = dict(con.execute("select run_id, any_value(json_extract_string(json, '$.hangar.version')) from "
                                "manifests group by 1").fetchall())
    for t in trials:
        t["hangar_version"] = versions.get(t["run_id"])
    doc = load(holdouts)
    min_hangar = max(min_hangar, doc.get("min_hangar_version", "0"), key=_version)
    result = _run(score, holdouts, doc, name, against, approve, author, by, trials, min_hangar)
    (holdouts / "results").mkdir(exist_ok=True)
    (holdouts / "results" / f"{name}.json").write_text(json.dumps(result, indent=1, default=str) + "\n")
    save(holdouts, doc)
    git = ["git", "-C", str(holdouts)]
    if subprocess.run([*git, "rev-parse"], capture_output=True).returncode == 0:
        subprocess.run([*git, "add", "manifest.json", f"results/{name}.json"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", f"holdout: score {name} against {against}"], check=True)
    typer.echo(f"{name}: {result['resolved']}/{result['n']} resolved, 95% Wilson {result['wilson95'][0]:.1%}-"
               f"{result['wilson95'][1]:.1%}; recorded in manifest.json and results/{name}.json")


@app.command("canary-scan")
def canary_scan(data: Annotated[str, typer.Option(envvar="FLIGHTDECK_DATA_URI", help="Data plane root.")],
                since: Annotated[int, typer.Option(help="Days back to scan.")] = 7,
                logs: Annotated[list[Path] | None, typer.Option(help="Retrieval or tool logs to scan too.")] = None,
                alerts_repo: Annotated[str, typer.Option(help="owner/repo to open an issue in (gh).")] = "",
                holdouts: ROOT = Path("holdouts")) -> None:
    """Find canaries in traces (tool input/output, messages, attributes) and logs; a hit voids its set."""
    import os

    from flightdeck.dataplane.duck import connect

    con = connect(os.path.expanduser(data))
    q = ("select run_id, concat_ws(' ', {}) from {} where cast(dt as varchar) >= cast(current_date - {} as varchar) "
         "and regexp_matches(concat_ws(' ', {}), 'FLIGHTDECK-CANARY-')")
    texts = [(f"{tab} {r}", x) for tab, cols in (("spans", "tool_input, tool_output, attrs"), ("events", "text, attrs"))
             for r, x in con.execute(q.format(cols, tab, int(since), cols)).fetchall()]
    texts += [(str(p), p.read_text(errors="replace")) for p in logs or []]
    doc = load(holdouts)
    hits = canary_hits(texts, doc)
    for h in hits:
        typer.echo(f"CANARY\t{h['set']}\t{h['task']}\t{h['where']}")
        if (s := doc["sets"].get(h["set"])) and s["status"] != "void":
            s.update(status="void", void_reason=f"canary of {h['task']} seen in {h['where']} ({_now()})")
            if alerts_repo:
                subprocess.run(["gh", "api", f"repos/{alerts_repo}/issues", "-f", f"title=flightdeck: holdout set "
                                f"{h['set']} is void (canary seen)", "-f", f"body={s['void_reason']}"], check=True)
    if hits:
        save(holdouts, doc)
    typer.echo(f"{len(hits)} canary hit(s)")
    raise typer.Exit(1 if hits else 0)
