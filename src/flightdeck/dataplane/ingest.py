"""Ingest from hangar without the GCS outbox: an experiment over REST or from `hangar experiment export -o DIR`, or a
job's or session's trace over REST, into the local `flightdeck.parquet/v1` layout (docs/data-plane.md#ingest).

REST ingest first writes the same files `hangar experiment export` writes, streamed to `<out>/raw/<id>/`, then reads
them like an export, so both paths produce identical rows and nothing large is held in memory. Each ingest unit (an
experiment, a job, a session) owns one Parquet part per table and day; re-ingesting replaces its rows by `run_id`, so
it adds no duplicates.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import typer

from flightdeck.dataplane import flatten, schema
from flightdeck.runners.hangar import pin_problems

DEFAULT_OUT = "~/.flightdeck/data"
Tables = dict[str, list[flatten.Row]]


class NotFound(ValueError):
    """Hangar answered 404: the record is missing, or the token's owner may not see it (owner scoping, 0014 §1).
    Reported as one line by the entry point (`cli.run`), like any other wrong id or path."""


def _get(base: str, path: str, token: str | None, dest: Path | None = None) -> Any:
    """GET a hangar REST path as JSON, or stream it to `dest` (returns None then)."""
    req = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if dest is None:
                return json.load(resp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                shutil.copyfileobj(resp, f)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(f"{path}: not found, or not visible to this token (a member token sees only its "
                           "owner's records)") from None
        raise


def fetch_experiment(exp_id: str, base: str, token: str | None, dest: Path) -> Path:
    """Write an experiment's index and its trials' manifest/trace files to `dest`, in `hangar experiment export`'s
    layout (`index.json`, `trials/<task>__<variant>__<n>[~<attempt>]/{manifest,trace}.json`)."""
    q = urllib.parse.quote
    index = _get(base, f"/api/experiments/{q(exp_id, safe='')}", token)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    for t in index.get("trials") or []:
        for name, link in (t.get("links") or {}).items():
            if name in ("manifest", "trace") and link:
                _get(base, link, token, dest / "trials" / flatten.trial_ref(t).replace("/", "__") / f"{name}.json")
    return dest


def _vendored(name: str) -> Any:
    return json.loads(files(__package__).joinpath(f"hangar_schemas/{name}").read_text(encoding="utf-8"))


@cache
def _validator(name: str) -> Any:
    import jsonschema

    return jsonschema.Draft202012Validator(_vendored(name))


def validate(doc: dict, name: str, what: str) -> None:
    """Warn (never fail) when a document doesn't match the vendored hangar schema; the flatteners keep what they can."""
    errors = sorted(_validator(name).iter_errors(doc), key=str)
    if errors:
        pin = _vendored("SOURCE.json")["commit"][:12]
        typer.secho(f"warning: {what} does not match hangar {name} (vendored at {pin}): {errors[0].message} "
                    f"(+{len(errors) - 1} more)", fg="yellow", err=True)


def read_export(d: Path) -> Tables:
    """Rows for every table from a `hangar experiment export` directory. A trial's spans, events and test results take
    the trial's `run_id`; its run row is the index's (one per trial key), marked truncated when its trace was."""
    index = json.loads((d / "index.json").read_text(encoding="utf-8"))
    validate(index, "experiment.schema.json", f"{d}/index.json")
    for problem in pin_problems(index):  # hangar's model rule, as `experiment run` and `status` apply it
        typer.secho(f"warning: {index.get('id')}: {problem}", fg="yellow", err=True)
    out: Tables = {name: [] for name in schema.TABLES}
    exp = flatten.flatten_experiment(index)
    out["grades"] = exp["grades"]
    seen: set[str] = set()
    for run in exp["runs"]:
        tdir = d / "trials" / run["run_id"].removeprefix(f"{index['id']}/").replace("/", "__")
        if (tdir / "manifest.json").is_file():
            m = json.loads((tdir / "manifest.json").read_text(encoding="utf-8"))
            if m.get("digest") not in seen:
                seen.add(m.get("digest"))
                validate(m, "manifest.schema.json", f"{tdir}/manifest.json")
                out["manifests"].append({**flatten.flatten_manifest(m, "experiment"), "run_id": run["run_id"]})
        if (tdir / "trace.json").is_file():
            rows = flatten.flatten_trace(json.loads((tdir / "trace.json").read_text(encoding="utf-8")))
            run["truncated"] = any(r["truncated"] for r in rows["runs"])
            for table in ("spans", "events", "test_cases"):
                out[table] += [{**r, "run_id": run["run_id"], "source": "experiment"} for r in rows[table]]
        out["runs"].append(run)
    return out


def fetch_trace(kind: str, name: str, base: str, token: str | None, turn: int | None = None) -> Tables:
    """Rows from a job's or session's trace over REST, with the manifest of each turn it holds."""
    path = f"/api/{kind}s/{urllib.parse.quote(name, safe='')}"
    rows = flatten.flatten_trace(_get(base, f"{path}/trace" + (f"?turn={turn}" if turn else ""), token))
    out: Tables = {name: [] for name in schema.TABLES} | rows
    for run in rows["runs"]:
        if run.get("turn") is None:
            continue
        try:
            m = _get(base, f"{path}/manifest?turn={run['turn']}", token)
        except NotFound:
            continue
        validate(m, "manifest.schema.json", f"{kind} {name} turn {run['turn']} manifest")
        out["manifests"].append(flatten.flatten_manifest(m, rows["runs"][0]["source"]))
    return out


def write_unit(tables: Tables, out: str, unit: str) -> dict[str, int]:
    """Merge one unit's rows into `out`: rows whose `run_id` is re-ingested are replaced. Returns rows per table."""
    part = "part-" + re.sub(r"[^A-Za-z0-9._-]", "_", unit)
    counts = {}
    for name, rows in tables.items():
        new = {r["run_id"] for r in rows}
        kept = [r for r in schema.read_part(name, out, part) if r["run_id"] not in new]
        if rows or kept:
            schema.write_partitioned(name, kept + rows, out, part)
        counts[name] = len(rows)
    return counts


# --- CLI ---------------------------------------------------------------------------------------------------------

app = typer.Typer(help="Pull hangar runs and experiments into the data plane.", no_args_is_help=True)
OUT = typer.Option(DEFAULT_OUT, "--out", envvar="FLIGHTDECK_DATA_URI", help="Data plane directory.")
HANGAR = typer.Option(None, "--hangar", envvar="HANGAR_URL", help="Hangar base URL; token from HANGAR_TOKEN.")
TURN = typer.Option(None, help="Only this turn.")


def _run(unit: str, out: str, load: Any, hangar: str | None = "") -> None:
    """Load one unit's rows (`load(base_url, token)`) and merge them into `out`."""
    if hangar is None:
        raise typer.BadParameter("pass --hangar or set HANGAR_URL")
    out = os.path.expanduser(out)
    counts = write_unit(load(hangar, os.environ.get("HANGAR_TOKEN")), out, unit)
    typer.echo(f"{unit}: " + ", ".join(f"{n} {t}" for t, n in counts.items()) + f" -> {out}")


@app.command("export")
def ingest_export(directory: Path, out: str = OUT) -> None:
    """Ingest the files `hangar experiment export -o DIR` wrote."""
    exp_id = json.loads((directory / "index.json").read_text(encoding="utf-8"))["id"]
    _run(f"experiment-{exp_id}", out, lambda *_: read_export(directory))


@app.command("experiment")
def ingest_experiment(exp_id: str, hangar: str = HANGAR, out: str = OUT) -> None:
    """Fetch an experiment over REST (raw files kept under <out>/raw/<id>/) and ingest it."""
    raw = Path(os.path.expanduser(out)) / "raw" / exp_id
    _run(f"experiment-{exp_id}", out, lambda url, tok: read_export(fetch_experiment(exp_id, url, tok, raw)), hangar)


@app.command("job")
def ingest_job(job_id: str, hangar: str = HANGAR, out: str = OUT) -> None:
    """Ingest a job's trace and its turns' manifests over REST."""
    _run(f"job-{job_id}", out, lambda url, tok: fetch_trace("job", job_id, url, tok), hangar)


@app.command("session")
def ingest_session(name: str, turn: int = TURN, hangar: str = HANGAR, out: str = OUT) -> None:
    """Ingest a session's trace (or one turn's) and the turns' manifests over REST."""
    _run(f"session-{name}", out, lambda url, tok: fetch_trace("session", name, url, tok, turn), hangar)
