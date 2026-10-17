"""The trial-result cache and the drift sentinel (docs/runners.md#cache).

Tokens cost far more than compute, so a trial whose inputs haven't changed is reused, not re-run. A stored trial
stands in for a planned one when its key matches: the task (`task_digest`, which covers the grader's tests and
command), the variant as planned (`variant_digest`: its hangar overlay and environment), the model and the base
commit, and the identity hangar recorded (`harness_digest` + `environment_digest`, else `config_digest` + the
environment's build id) equals the latest identity that variant recorded. Only completed trials count: never an
infra_error, cancelled, tainted, drifted or invalid one, and never past the TTL or a `cache drop`. Because a silent
provider change keeps every key the same, a nightly sentinel runs a few fixed tasks with the cache off and alerts
when their rate, cost or latency leaves its trailing range.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Annotated, Any

import typer

from flightdeck.runners.hangar import TrialPlan
from flightdeck.tasks.format import hangar_id

TTL_DAYS = 30
IDENTITY = ("coalesce(r.harness_digest || '+' || r.environment_digest, r.config_digest || coalesce('+' || "
            "json_extract_string(m.json, '$.environment.build.id'), ''))")


def variant_digest(v: dict[str, Any], environment: str) -> str:
    canon = json.dumps({"environment": environment, **v}, sort_keys=True)
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()


def digests(plan: TrialPlan) -> dict[str, dict[str, str]]:
    """What a run set's rows are stamped with: each task's digest by hangar id, each variant's planned digest."""
    return {"task_digests": {hangar_id(t): t.digest for t in plan.tasks},
            "variant_digests": {k: variant_digest(v, plan.environment) for k, v in plan.variants.items()}}


def stamp(runs: list[dict[str, Any]], d: dict[str, dict[str, str]]) -> None:
    for r in runs:
        r["task_digest"] = d["task_digests"].get(str(r.get("task_id")))
        r["variant_digest"] = d["variant_digests"].get(str(r.get("variant")))


def _drops(data: str) -> dict[str, dict[str, float]]:
    p = Path(data) / "cache-drops.json"
    return json.loads(p.read_text()) if p.is_file() else {"tasks": {}, "identities": {}}


def lookup(con: Any, plan: TrialPlan, data: str, ttl_days: float = TTL_DAYS) -> dict[tuple[str, str], list[tuple]]:
    """Cached trials per planned (task id, variant): the n most recent matching ones, as (run_id, age in days);
    pairs with fewer than n are left out."""
    if "runs" not in {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}:
        return {}
    rows = con.execute(f"""with t as (select r.run_id, r.task_id, r.task_digest, r.variant_digest, r.model_id,
            r.base_sha, epoch(r.finished_at) as fin, {IDENTITY} as identity from runs r left join manifests m
            on r.manifest_digest = m.digest where r.outcome in ('succeeded', 'failed') and r.task_digest is not null
            and coalesce(r.outcome_class, '') not in ('infra_error', 'cancelled', 'human')
            and not (coalesce(r.excluded, false) or coalesce(r.tainted, false) or coalesce(r.task_invalid, false)
            or coalesce(r.contaminated, false) or coalesce(len(r.drift), 0) > 0)),
          cur as (select variant_digest, arg_max(identity, fin) as identity from t group by 1)
        select t.* from t join cur using (variant_digest) where t.identity = cur.identity and
            t.fin >= epoch(now()) - ? order by t.fin desc""", [ttl_days * 86400]).fetchall()
    drops, now, d, out = _drops(data), time.time(), digests(plan), {}
    for task in plan.tasks:
        tid, base = hangar_id(task), (task.flightdeck.get("source") or {}).get("base_sha")
        for name, v in plan.variants.items():
            hits = [(rid, (now - fin) / 86400) for rid, rtask, td, vd, model, sha, fin, ident in rows
                    if td == d["task_digests"][tid] and vd == d["variant_digests"][name]
                    and (not v.get("model") or model == v["model"]) and (not base or sha == base)
                    and fin > max(drops["tasks"].get(rtask, 0), drops["identities"].get(ident, 0))][:plan.n]
            if len(hits) == plan.n:
                out[(tid, name)] = hits
    return out


def reduce(plan: TrialPlan, hits: dict[tuple[str, str], list[tuple]]) -> list[TrialPlan]:
    """The plan cut to what the cache lacks: one plan per variant with its missing tasks (none when all hit)."""
    out = []
    for name, v in plan.variants.items():
        missing = [t for t in plan.tasks if (hangar_id(t), name) not in hits]
        if missing:
            out.append(replace(plan, tasks=missing, variants={name: v}))
    return out


def reuse_rows(run_set: str, hits: dict[tuple[str, str], list[tuple]]) -> list[dict[str, Any]]:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return [{"run_id": rid, "source": "experiment", "dt": day, "experiment_id": run_set, "task_id": t, "variant": v,
             "age_days": round(age, 2)} for (t, v), rs in hits.items() for rid, age in rs]


def drift(days: Sequence[tuple[str, int, int, float | None, float | None]], window: int = 14) -> list[str]:
    """Alerts for the sentinel's latest day against its trailing window: (day, resolved, trials, median cost,
    median wall seconds) per day, oldest first. A rate whose Wilson interval misses the window's, or a median cost or
    latency outside 0.67-1.5x of the window's, is a change nobody made on purpose."""
    from flightdeck.stats.core import wilson

    if len(days) < 2:
        return []
    (day, k, n, *_), prev = days[-1], days[-1 - window:-1]
    pk, pn = sum(x[1] for x in prev), sum(x[2] for x in prev)
    (lo, hi), (plo, phi) = wilson(k, n), wilson(pk, pn)
    out = [f"{day}: resolved {k}/{n} [{lo:.0%}, {hi:.0%}] vs the trailing {len(prev)} days' {pk}/{pn} "
           f"[{plo:.0%}, {phi:.0%}]"] if hi < plo or lo > phi else []
    for i, what in ((3, "cost"), (4, "wall time")):
        now, ref = days[-1][i], median([float(x[i] or 0) for x in prev if x[i]] or [0.0])
        if ref and isinstance(now, float | int) and not 0.67 <= now / ref <= 1.5:
            out.append(f"{day}: median {what} {now:.2f} vs the trailing median {ref:.2f}")
    return out


app = typer.Typer(help="The trial-result cache: drop entries, check the drift sentinel.", no_args_is_help=True)
DATA = Annotated[str, typer.Option("--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane root (local).")]


@app.command()
def drop(data: DATA, task: Annotated[list[str] | None, typer.Option(help="A task id.")] = None,
         identity: Annotated[list[str] | None, typer.Option(help="An identity (harness+environment digest).")] = None):
    """Stop reusing trials of these tasks or identities finished before now."""
    doc, now = _drops(data), time.time()
    for k, vals in (("tasks", task), ("identities", identity)):
        doc[k].update(dict.fromkeys(vals or [], now))
    (Path(data) / "cache-drops.json").write_text(json.dumps(doc, indent=1, sort_keys=True))
    typer.echo(f"dropped {len(task or [])} task(s), {len(identity or [])} identity(ies) from the cache")


@app.command()
def sentinel(suite: Path, variant: str, data: DATA, window: int = 14,
             alerts_repo: Annotated[str, typer.Option(help="owner/repo for an issue (gh).")] = "") -> None:
    """Check the nightly sentinel (`experiment run <suite>` without --cache) for a step change; exit 1 on alerts."""
    import subprocess

    from flightdeck.dataplane.duck import connect
    from flightdeck.runners.hangar import load_plan
    from flightdeck.stats.compare import exclusion, load_trials, resolved

    plan = load_plan(suite)
    vd = variant_digest(plan.variants[variant], plan.environment)
    con = connect(os.path.expanduser(data))
    q = "select distinct experiment_id from runs where variant_digest = ?"
    exps = [r[0] for r in con.execute(q, [vd]).fetchall()]
    trials = [t for t in load_trials(con, "+".join(exps)) if t.get("variant_digest") == vd
              and not exclusion(t, "resolved")] if exps else []
    days: dict[str, list[dict]] = {}
    for t in trials:
        days.setdefault(str(t["dt"]), []).append(t)
    series = [(d, sum(bool(resolved(t)[0]) for t in ts), len(ts),
               median([t["cost_usd"] for t in ts if t.get("cost_usd") is not None] or [0]) or None,
               median([t["wall_s"] for t in ts if t.get("wall_s") is not None] or [0]) or None)
              for d, ts in sorted(days.items())]
    found = drift(series, window)
    for a in found:
        typer.echo(f"ALERT\t{a}")
    if found and alerts_repo:
        subprocess.run(["gh", "api", f"repos/{alerts_repo}/issues", "-f", "title=flightdeck: the drift sentinel moved "
                        "(did the provider change something?)", "-f", "body=" + "\n".join(found)], check=True)
    typer.echo(f"sentinel {variant}: {len(series)} day(s), {len(found)} alert(s)")
    raise typer.Exit(1 if found else 0)
