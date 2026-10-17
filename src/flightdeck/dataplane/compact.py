"""The nightly compactor: hangar's outbox (`hangar.run/v1`, hangar `docs/api/outbox.md`) into `flightdeck.parquet/v1`.

Reads `<input>/v1/runs/{date}/{session_id}.{run_id}/` (a run is complete once its `run.json` exists: hangar uploads it
last) and `<input>/v1/jobs/{date}/{job_id}/events/*.json`, and rewrites each table's `dt={date}/part-0.parquet` from
scratch (written as `.tmp`, then renamed). `<out>/_compactor/{date}.json` records the input objects; a date whose
listing is unchanged is skipped, so a re-run is a no-op and a late or deleted object recompacts its date. Needs read
access to the outbox and write access to the data plane only: no hangar endpoint, no HTTP client (docs/data-plane.md).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import fsspec
import pyarrow.parquet as pq
import typer

from flightdeck.dataplane import flatten, schema

PART = "part-0.parquet"
ROW_GROUP_BYTES = 64 << 20
RUN_KEYS = ("person", "repo", "environment", "harness", "harness_version", "outcome", "config_digest", "harness_digest",
            "environment_digest", "manifest_digest", "base_sha", "diff_files", "truncated", "outcome_class",
            "infra_reason", "job_source", "job_turn", "job_state", "questions", "untrusted", "tainted", "attempt")


def _read(fs: Any, path: str) -> tuple[Any, str]:
    raw = fs.cat_file(path)
    raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw  # GCS objects are stored gzipped
    return flatten.scrub(json.loads(raw)), hashlib.sha256(raw).hexdigest()


def _listing(fs: Any, path: str) -> dict[str, dict]:
    """`{path: {size, generation}}` under a prefix, from one prefix listing (no per-object calls)."""
    return {p: {"size": i.get("size"), "generation": str(i.get("generation") or i.get("mtime") or "")}
            for p, i in fs.find(path, detail=True).items()}


def _run_row(r: dict) -> flatten.Row:
    """A `run.json` as `runs` columns."""
    u, x, pr = r.get("usage") or {}, r.get("experiment") or {}, r.get("pr") or {}
    return {**{k: r.get(k) for k in RUN_KEYS}, "job_id": r.get("job_id"), "session_id": r.get("session_id"),
            "turn": r.get("turn"), "experiment_id": x.get("id"), "trial_key": x.get("trial_key"),
            "task_id": x.get("task"), "variant": x.get("variant"), "trial": x.get("trial"), "model_id": r.get("model"),
            "reason": r.get("outcome_reason"), "cost_usd": u.get("cost_usd"), "cost_source": u.get("cost_source"),
            "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
            "cache_read_tokens": u.get("cache_read_tokens"), "started_at": flatten._ts(r.get("started_at")),
            "finished_at": flatten._ts(r.get("finished_at")), "verify_passed": (r.get("verify") or {}).get("passed"),
            "pr_url": pr.get("url"), "pr_number": pr.get("number"), "steers": (r.get("steers") or {}).get("n")}


def _event_row(e: dict) -> flatten.Row:
    d, pr = e.get("data") or {}, e.get("pr") or {}
    return {**{k: e.get(k) for k in ("job_id", "kind", "job_source", "repo", "person", "environment", "session_id",
                                     "untrusted")},
            "run_id": e["job_id"], "source": e["source"], "ts": flatten._ts(e["ts"]), "run_ids": e.get("run_ids") or [],
            "pr_url": pr.get("url"), "pr_number": pr.get("number"), "reason": d.get("reason"), "by": d.get("by"),
            "green_to_merge_seconds": d.get("green_to_merge_seconds"), "data": flatten._json(d)}


def write_partition(fs: Any, root: str, name: str, day: str, rows: list[flatten.Row]) -> None:
    """Replace `<root>/<name>/dt=<day>/part-0.parquet` with rows (sorted by run_id, seq), or remove it if none."""
    path = f"{root}/{name}/dt={day}/{PART}"
    if not rows:
        if fs.exists(path):
            fs.rm(path)
        return
    rows = sorted(rows, key=lambda r: (r.get("run_id") or "", r.get("seq") or -1, json.dumps(r, sort_keys=True,
                                                                                           default=str)))
    table = schema.to_table(name, [{**r, "dt": day} for r in rows]).drop_columns(["dt"])
    fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(path + ".tmp", "wb") as f:
        pq.write_table(table, f, compression="zstd",
                       row_group_size=max(1, ROW_GROUP_BYTES * table.num_rows // max(table.nbytes, 1)))
    fs.mv(path + ".tmp", path)


def compact_date(src: str, out: str, day: str, rebuild: bool = False) -> dict[str, int] | None:
    """Compact one outbox date; None when its inputs are unchanged since the last compaction (and not `rebuild`)."""
    ifs, iroot = fsspec.core.url_to_fs(src)
    ofs, oroot = fsspec.core.url_to_fs(out)
    iroot, oroot = iroot.rstrip("/"), oroot.rstrip("/")
    objs = _listing(ifs, f"{iroot}/v1/runs/{day}")
    dels = {p: i for p, i in _listing(ifs, f"{iroot}/v1/_deletions").items() if p.endswith(".json")}
    events = {p: i for p, i in _listing(ifs, f"{iroot}/v1/jobs/{day}").items() if p.endswith(".json")}
    deleted = {k for p in sorted(dels) for k in _read(ifs, p)[0].get("runs", [])}
    dirs = sorted(p.rsplit("/", 1)[0] for p in objs if p.endswith("/run.json"))
    dirs = [d for d in dirs if not {d.rsplit("/", 1)[1], d.rsplit(".", 1)[1]} & deleted]
    inputs = {p: i for p, i in objs.items() if p.rsplit("/", 1)[0] in dirs} | events | dels
    record = f"{oroot}/_compactor/{day}.json"
    listing = {p.removeprefix(iroot + "/"): i for p, i in sorted(inputs.items())}
    if not rebuild and ofs.exists(record) and json.loads(ofs.cat_file(record))["listing"] == listing:
        return None
    sha: dict[str, str] = {}

    def load(path: str) -> Any:
        doc, sha[path.removeprefix(iroot + "/")] = _read(ifs, path)
        return doc

    tables: dict[str, list[flatten.Row]] = {n: [] for n in (*schema.TABLES, "job_events")}
    for d in dirs:
        run, have = load(f"{d}/run.json"), {p.rsplit("/", 1)[1] for p in inputs if p.rsplit("/", 1)[0] == d}
        rid, src_ = run["run_id"], run["source"]
        rows = flatten.flatten_trace(load(f"{d}/trace.otlp.json"), src_, rid) if "trace.otlp.json" in have else {}
        if "tests.json" in have:
            trace_id = str((rows.get("spans") or [{"trace_id": ""}])[0]["trace_id"])
            rows["test_cases"] = [flatten._test_row(e, flatten.otlp_attrs(e.get("attributes", [])), rid, src_, trace_id)
                                  for e in load(f"{d}/tests.json").get("events", [])]
        turn = (rows.get("runs") or [{}])[0]
        rows["runs"] = [{**turn, **{k: v for k, v in _run_row(run).items() if v is not None}}]
        if "manifest.json" in have:
            rows["manifests"] = [flatten.flatten_manifest(load(f"{d}/manifest.json"), src_)]
        if "grade.json" in have:
            g = load(f"{d}/grade.json")
            rows["grades"] = [{"experiment_id": g.get("experiment_id"), "trial_key": g.get("trial_key"),
                               **{k: g.get(k) for k in ("command", "exit_code", "applied", "seconds", "error")},
                               "data": None if g.get("data") is None else json.dumps(g["data"], sort_keys=True),
                               "grader_digest": g.get("digest")}]
        for name, rs in rows.items():
            tables[name] += [{**r, "run_id": rid, "source": src_} for r in rs]
    tables["manifests"] = list({r["digest"]: r for r in tables["manifests"]}.values())
    tables["job_events"] = [_event_row(load(p)) for p in sorted(events)]
    for name, rows in tables.items():
        write_partition(ofs, oroot, name, day, rows)
    objects = {p: {**i, "sha256": sha.get(p)} for p, i in listing.items()}
    ofs.makedirs(f"{oroot}/_compactor", exist_ok=True)
    ofs.pipe_file(record, json.dumps({"date": day, "listing": listing, "objects": objects, "schema": schema.VERSION},
                                     indent=1, sort_keys=True).encode())
    return {name: len(rows) for name, rows in tables.items()}


def compact(
    day: str = typer.Option(None, "--date", help="UTC outbox date, YYYY-MM-DD (default: today)."),
    lookback: int = typer.Option(3, help="Also recompact this many days before --date whose inputs changed."),
    rebuild: bool = typer.Option(False, help="Rewrite the dates even if their inputs are unchanged."),
    src: str = typer.Option(..., "--input", envvar="FLIGHTDECK_RUNS_URI", help="Outbox root: gs://, file:// or path."),
    out: str = typer.Option(..., "--out", envvar="FLIGHTDECK_DATA_URI", help="Data plane root."),
) -> None:
    """Compact hangar's outbox into the data plane (nightly on Cloud Run: deploy/compactor/)."""
    end = date.fromisoformat(day) if day else datetime.now(UTC).date()
    for i in range(lookback, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        counts = compact_date(os.path.expanduser(src), os.path.expanduser(out), d, rebuild)
        typer.echo(f"{d}: " + ("unchanged" if counts is None else ", ".join(f"{n} {t}" for t, n in counts.items())))
