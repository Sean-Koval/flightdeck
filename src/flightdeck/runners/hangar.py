"""Trials on hangar through its batch experiment API (docs/runners.md): plans, specs, the cost gate, the backend.

Flightdeck owns sampling; hangar executes `hangar.experiment/v1` (tasks x variants x trials as jobs, pinned, graded in
a clean sandbox). `Backend` is the interface suites and the CLI use, so pin-set trials (`POST /api/trials`, #25) can
replace `HangarBatchBackend` without touching them.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from flightdeck.tasks.format import Task, hangar_id, load_task, to_hangar

MAX_TASKS, MAX_VARIANTS, MAX_TRIALS, MAX_TOTAL = 100, 8, 20, 200  # hangar ExperimentSpec; HANGAR_EXPERIMENT_MAX_TRIALS
VARIANT_KEYS = {"environment", "harness", "model", "approvals", "skills", "skills_remove", "instructions",
                "instructions_append"}  # hangar experiments.Variant
TERMINAL = {"succeeded", "failed", "cancelled"}
# Model pins (hangar #167's rule): policies and aliases float; a concrete id names a version (or a date)
POLICIES = {"frontier", "balanced", "latest", "default", "auto", "best", "fast", "cheap"}
CONCRETE = re.compile(
    r"^(claude-(fable|mythos|opus|sonnet|haiku)-\d+[-.]\d+(-\d{8})?|claude-\d+(-\d+)?-(opus|sonnet|haiku)-\d{8}"
    r"|gpt-\d+(\.\d+)?-(astra|sol|terra|luna)(-\d{4}-\d{2}-\d{2})?|(gpt|o)[\w.-]*-\d{4}-\d{2}-\d{2}"
    r"|gemini-\d+(\.\d+)?-(pro|flash|flash-lite)(-[a-z0-9]+)*)$")


class RunnerError(Exception):
    """A plan flightdeck or hangar refuses; the message says why."""


def model_problem(model: str | None, allowed: frozenset[str] = frozenset()) -> str | None:
    """Why `model` isn't a concrete id a trial can be pinned to, or None when it is."""
    if not model:
        return "no model: the environment's default can change between trials"
    if model in allowed:
        return None
    base = model.split("/")[-1]  # openrouter/<vendor>/<id>
    if model.split("@")[0] in POLICIES:
        return f"'{model}' is a policy, resolved anew as providers ship models"
    if base.startswith("~") or re.search(r"(^|[-:.])latest$", base):
        return f"'{model}' is a floating alias"
    if not CONCRETE.match(base):
        return f"'{model}' names no version or date (a family alias such as opus or gpt-5?)"
    return None


@dataclass
class TrialPlan:
    suite: str
    tasks: list[Task]
    variants: dict[str, dict[str, Any]]
    n: int = 1
    environment: str = ""
    budget_usd: float | None = None
    trial_budget_usd: float | None = None
    parallel: int | None = None
    suite_run: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))


def load_plan(path: Path) -> TrialPlan:
    """A suite file (YAML): `suite`, `tasks` (task directories, or directories of them, relative to the file),
    `variants` (hangar's overlay), `n`, `environment`, `budget_usd`, `trial_budget_usd`, `parallel`."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks = []
    for entry in doc.get("tasks") or []:
        d = (path.parent / entry).resolve()
        dirs = [d] if (d / "task.toml").is_file() else sorted(p.parent for p in d.glob("*/task.toml"))
        if not dirs:
            raise RunnerError(f"{path}: no task under {entry}")
        tasks += [load_task(x) for x in dirs]
    if not tasks or not doc.get("variants"):
        raise RunnerError(f"{path}: a suite needs `tasks` and `variants`")
    for name, v in doc["variants"].items():
        if bad := set(v or {}) - VARIANT_KEYS:
            raise RunnerError(f"variant {name}: {', '.join(sorted(bad))} isn't a hangar variant field")
    envs = {t.flightdeck.get("environment") for t in tasks} - {None}
    env = doc.get("environment") or (envs.pop() if len(envs) == 1 else "")
    if not env:
        raise RunnerError(f"{path}: set `environment` (the tasks name {sorted(envs) or 'none'})")
    return TrialPlan(doc.get("suite") or path.stem, tasks, {k: v or {} for k, v in doc["variants"].items()},
                     int(doc.get("n", 1)), env, doc.get("budget_usd"), doc.get("trial_budget_usd"), doc.get("parallel"))


def check_models(plan: TrialPlan, allowed: frozenset[str] = frozenset()) -> None:
    errors = [f"variant {k}: {p}" for k, v in plan.variants.items() if (p := model_problem(v.get("model"), allowed))]
    if errors:
        raise RunnerError("trials need a concrete model id (e.g. claude-opus-5-5, gpt-6.1-sol); `hangar env list` "
                          "shows what a policy resolves to today, --allow-model accepts an id as concrete:\n  "
                          + "\n  ".join(errors))


def build_specs(plan: TrialPlan, max_total: int = MAX_TOTAL) -> list[dict[str, Any]]:
    """The plan as `hangar.experiment/v1` specs: more than one when it is over hangar's per-experiment caps; they
    share the plan's suite_run in their names."""
    v, n = len(plan.variants), plan.n
    if not 1 <= n <= MAX_TRIALS or v > MAX_VARIANTS:
        raise RunnerError(f"hangar takes 1-{MAX_TRIALS} trials and at most {MAX_VARIANTS} variants per experiment")
    per = min(MAX_TASKS, max_total // (v * n))
    if per < 1:
        raise RunnerError(f"{v} variants x {n} trials is over hangar's {max_total} trials per experiment")
    chunks = [plan.tasks[i:i + per] for i in range(0, len(plan.tasks), per)]
    specs = []
    for i, chunk in enumerate(chunks):
        tasks, grader = to_hangar(chunk)
        spec: dict[str, Any] = {"name": f"{plan.suite}-{plan.suite_run}" + (f"-{i + 1}" if len(chunks) > 1 else ""),
                                "environment": plan.environment, "tasks": tasks, "variants": plan.variants,
                                "trials": n, "grader": grader}
        if plan.parallel:
            spec["parallel"] = plan.parallel
        if plan.trial_budget_usd:
            spec["trial_job_budget"] = {"max_cost_usd": plan.trial_budget_usd}
        if plan.budget_usd:
            spec["budget"] = {"max_cost_usd": round(plan.budget_usd * len(chunk) / len(plan.tasks), 2)}
        specs.append({**spec, "name": spec["name"][:100]})
    return specs


# ---------------------------------------------------------------------------------------------------- cost gate
def project(plan: TrialPlan, p50: dict[str, float], assume: float) -> tuple[float, dict[str, float]]:
    """Projected dollars: each task's historical p50 cost per trial (else `assume`) x n x variants."""
    per = {k: p50.get(k, assume) for k in map(hangar_id, plan.tasks)}
    return round(sum(per.values()) * plan.n * len(plan.variants), 2), per


def history(data: str | None, author: str | None) -> tuple[dict[str, float], float, float]:
    """From the data plane: p50 cost per trial by task, and this month's experiment spend (team, author)."""
    if not data:
        return {}, 0.0, 0.0
    from flightdeck.dataplane.duck import connect

    con = connect(data)
    if "runs" not in {r[0] for r in con.sql("select view_name from duckdb_views()").fetchall()}:
        return {}, 0.0, 0.0
    p50 = dict(con.sql("select task_id, median(cost_usd) from runs where cost_usd is not null and task_id is not null"
                       " group by 1").fetchall())
    month = "source = 'experiment' and strftime(started_at, '%Y-%m') = strftime(current_date, '%Y-%m')"
    team = con.sql(f"select coalesce(sum(cost_usd), 0) from runs where {month}").fetchone()
    mine = con.execute(f"select coalesce(sum(cost_usd), 0) from runs where {month} and person = ?", [author]).fetchone()
    return p50, float(team[0] if team else 0), float(mine[0] if mine else 0)


def gate(projected: float, max_usd: float | None, budgets: Path | None, author: str | None, team_spent: float,
         author_spent: float) -> list[str]:
    """Why the plan may not be submitted (empty: it may). Advisory and early: hangar's budgets still enforce."""
    refusals = []
    if max_usd is not None and projected > max_usd:
        refusals.append(f"projected ${projected:,.2f} is over --max-usd ${max_usd:,.2f}")
    if budgets is not None:
        doc = yaml.safe_load(budgets.read_text(encoding="utf-8")) or {}
        if (cap := doc.get("month_usd")) is not None and projected > cap - team_spent:
            refusals.append(f"projected ${projected:,.2f} is over the team's remaining ${cap - team_spent:,.2f} this "
                            f"month (month_usd {cap} in {budgets})")
        caps = doc.get("authors") or {}
        if caps and not author:
            refusals.append(f"{budgets} sets per-author caps: name the author (--author or FLIGHTDECK_AUTHOR)")
        elif author in caps and projected > caps[author] - author_spent:
            refusals.append(f"projected ${projected:,.2f} is over {author}'s remaining "
                            f"${caps[author] - author_spent:,.2f} this month (authors.{author} in {budgets})")
    return refusals


# ---------------------------------------------------------------------------------------------------- backends
@dataclass
class RunSetStatus:
    run_set: str
    state: str
    counts: dict[str, int]
    experiments: dict[str, str]  # experiment id -> its state
    problems: list[str]  # pins that break the comparison
    notes: list[str]


class Backend(Protocol):
    def submit(self, plan: TrialPlan) -> str: ...  # a run-set id

    def status(self, run_set: str) -> RunSetStatus: ...

    def collect(self, run_set: str) -> Path: ...  # the data plane it wrote to


def pin_problems(index: dict[str, Any]) -> list[str]:
    """What breaks pairing in an experiment's pins: an unpinned base commit, a model pinned to an alias, or variants
    that asked for the same model and were pinned to different ids."""
    pins = index.get("pins") or {}
    out = [f"task {k}: no base_sha pinned" for k, t in (pins.get("tasks") or {}).items() if not t.get("base_sha")]
    asked: dict[str, set[str]] = {}
    for name, v in (pins.get("variants") or {}).items():
        if p := model_problem(v.get("model")):
            out.append(f"variant {name}: pinned model {p}")
        req = ((index.get("spec") or {}).get("variants") or {}).get(name, {}).get("model")
        asked.setdefault(req or v.get("model") or "", set()).add(v.get("model") or "")
    out += [f"variants asking for {k} were pinned to different ids: {sorted(s)}" for k, s in asked.items()
            if len(s) > 1]
    return out


class HangarBatchBackend:
    """`POST /api/experiments`, `GET /api/experiments/{id}`. A run set is one or more experiment ids joined by '+'."""

    def __init__(self, url: str, token: str | None, out: str | None = None) -> None:
        self.url, self.token, self.out = url.rstrip("/"), token, out

    def _call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        req = urllib.request.Request(self.url + path, method=method, headers={"Accept": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, list):  # FastAPI's validation errors
                detail = "; ".join(f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg')}" for d in detail)
            raise RunnerError(f"hangar refused {method} {path} ({e.code}): {detail or e.reason}") from None

    def submit(self, plan: TrialPlan) -> str:
        return "+".join(self._call("POST", "/api/experiments", spec)["id"] for spec in build_specs(plan))

    def status(self, run_set: str) -> RunSetStatus:
        counts: dict[str, int] = {}
        exps, problems, notes = {}, [], []
        for exp in run_set.split("+"):
            index = self._call("GET", f"/api/experiments/{exp}")
            exps[exp] = index["state"]
            for k, c in (index.get("counts") or {}).items():
                counts[k] = counts.get(k, 0) + c
            problems += [f"{exp}: {p}" for p in pin_problems(index)] if index.get("pins") else []
            notes += [f"{exp}: {x}" for x in index.get("notes") or []]
        live = {s for s in exps.values() if s not in TERMINAL}
        done = set(exps.values()) - live
        state = (live.pop() if len(live) == 1 else "running") if live else next(
            s for s in ("failed", "cancelled", "succeeded") if s in done)
        return RunSetStatus(run_set, state, counts, exps, problems, notes)

    def collect(self, run_set: str) -> Path:
        """Each experiment's trials (runs) and grades into the data plane, one part per experiment (re-collecting
        replaces it). Traces and manifests: `flightdeck ingest experiment` (#7)."""
        import pyarrow.parquet as pq

        from flightdeck.dataplane import flatten, schema

        if not self.out:
            raise RunnerError("no data plane: pass --out or set FLIGHTDECK_DATA_URI")
        for exp in run_set.split("+"):
            for name, rows in flatten.flatten_experiment(self._call("GET", f"/api/experiments/{exp}")).items():
                for stale in Path(self.out).glob(f"{name}/dt=*/part-experiment-{exp}.parquet"):
                    stale.unlink()  # a trial's day can change between two collects
                for day in sorted({r.get("dt") or "unknown" for r in rows}):
                    part = Path(self.out) / name / f"dt={day}"
                    part.mkdir(parents=True, exist_ok=True)
                    table = schema.to_table(name, [r for r in rows if (r.get("dt") or "unknown") == day])
                    pq.write_table(table.drop_columns(["dt"]), part / f"part-experiment-{exp}.parquet",
                                   compression="zstd")
        return Path(self.out)

