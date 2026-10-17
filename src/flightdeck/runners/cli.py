"""`flightdeck experiment run|status|collect`: submit a suite's trials to hangar, follow them, collect them."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from flightdeck.runners import hangar as h
from flightdeck.runners.hangar import RunnerError
from flightdeck.tasks.format import TaskError

app = typer.Typer(help="Trials on hangar: submit a suite, follow it, collect it.", no_args_is_help=True)
DATA = typer.Option(None, "--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane: cost history, collect target.")
LOCAL = "local-"  # local run sets' prefix


def backend(data: str | None = None, kind: str = "hangar") -> h.Backend:
    """The backend the commands use (tests swap it). Hangar's URL from HANGAR_URL, its token from HANGAR_TOKEN."""
    if kind == "local":
        from flightdeck.runners.local import LocalDockerBackend

        return LocalDockerBackend(data and os.path.expanduser(data))
    url = os.environ.get("HANGAR_URL")
    if not url:
        raise RunnerError("set HANGAR_URL (and HANGAR_TOKEN) to reach hangar")
    return h.HangarBatchBackend(url, os.environ.get("HANGAR_TOKEN"), data and os.path.expanduser(data))


def _fail(e: Exception) -> typer.Exit:
    typer.secho(f"error: {e}", fg="red", err=True)
    return typer.Exit(1)


@app.command()
def run(
    suite: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Suite file (YAML).")],
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the spec and the projection; submit nothing."),
    max_usd: float = typer.Option(None, "--max-usd", help="Refuse a plan projected above this."),
    assume: float = typer.Option(3.0, "--assume", help="$ per trial for a task without cost history."),
    budgets: Annotated[Path | None, typer.Option("--budgets", envvar="FLIGHTDECK_BUDGETS", help="Caps.")] = None,
    author: str = typer.Option(None, "--author", envvar="FLIGHTDECK_AUTHOR", help="Whose sub-cap the plan spends."),
    allow_model: Annotated[list[str] | None, typer.Option("--allow-model", help="Accept this id as concrete.")] = None,
    data: str = DATA,
    kind: str = typer.Option("hangar", "--backend", help="hangar, or local: Docker on this machine (fixtures, CI)."),
) -> None:
    """Gate a suite's plan on model pins and projected cost, then submit it (or print it with --dry-run)."""
    if kind == "local":  # runs now, spends no hangar budget; docs/runners.md#local
        try:
            run_set = backend(data, kind).submit(h.load_plan(suite))
        except (RunnerError, TaskError) as e:
            raise _fail(e) from None
        typer.echo(f"ran {run_set} into {data}: flightdeck stats compare {run_set} --data {data}")
        return
    try:
        plan = h.load_plan(suite)
        h.check_models(plan, frozenset(allow_model or ()))
        specs = h.build_specs(plan)
        p50, team, mine = h.history(data and os.path.expanduser(data), author)
        total, per = h.project(plan, p50, assume)
        if budgets is None and Path("budgets.yaml").is_file():
            budgets = Path("budgets.yaml")
        if budgets is not None and not budgets.is_file():
            raise RunnerError(f"{budgets}: no such budgets file")
        refusals = h.gate(total, max_usd, budgets, author, team, mine)
    except (RunnerError, TaskError) as e:
        raise _fail(e) from None
    typer.echo(f"projection: ${total:,.2f} = {len(plan.tasks)} task(s) x {len(plan.variants)} variant(s) x "
               f"{plan.n} trial(s); per trial: " + ", ".join(f"{k} ${v:,.2f}" + ("" if k in p50 else " (assumed)")
                                                            for k, v in per.items()))
    if budgets is None:
        typer.echo("no budgets file: only --max-usd applies (hangar's budgets still enforce)")
    if refusals:
        raise _fail(RunnerError("refused:\n  " + "\n  ".join(refusals)))
    if dry_run:
        typer.echo(json.dumps(specs[0] if len(specs) == 1 else specs, indent=1))
        return
    try:
        run_set = backend(data).submit(plan)
    except (RunnerError, TaskError) as e:
        raise _fail(e) from None
    typer.echo(f"submitted {run_set} (suite run {plan.suite_run}): flightdeck experiment status {run_set}")


@app.command()
def status(run_set: str, as_json: bool = typer.Option(False, "--json"), data: str = DATA) -> None:
    """A run set's state, trial counts, and pins that break pairing (exit 1 when there are any)."""
    try:
        st = (backend(data, "local") if run_set.startswith(LOCAL) else backend()).status(run_set)
    except RunnerError as e:
        raise _fail(e) from None
    if as_json:
        typer.echo(json.dumps(asdict(st), indent=1))
    else:
        typer.echo(f"{st.run_set}: {st.state}  " + "  ".join(f"{k}={v}" for k, v in sorted(st.counts.items())))
        for line in [f"note: {n}" for n in st.notes] + [f"pin problem: {p}" for p in st.problems]:
            typer.echo(f"  {line}")
    raise typer.Exit(1 if st.problems else 0)


@app.command()
def collect(run_set: str, data: str = DATA) -> None:
    """Write a run set's trials and grades into the data plane."""
    try:
        out = (backend(data, "local") if run_set.startswith(LOCAL) else backend(data)).collect(run_set)
    except RunnerError as e:
        raise _fail(e) from None
    typer.echo(f"collected {run_set} into {out}")
