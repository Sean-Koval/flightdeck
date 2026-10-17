"""The `flightdeck` command line. Subcommands arrive with the issues that build them (docs/decisions/0001)."""

import os

import typer

from flightdeck import __version__
from flightdeck.runners.cli import app as experiment_app
from flightdeck.specs.cli import check_app, spec_app
from flightdeck.tasks.cli import app as task_app

app = typer.Typer(
    help="Judge coding-agent runs from hangar: paired statistics, behavior specs, task sets.", no_args_is_help=True
)

app.add_typer(spec_app, name="spec")
app.add_typer(check_app, name="check")
app.add_typer(task_app, name="task")
app.add_typer(experiment_app, name="experiment")


@app.callback()
def main() -> None:
    """flightdeck: reads hangar runs, owns sampling and analysis."""


@app.command()
def version() -> None:
    """Print flightdeck's version."""
    typer.echo(__version__)


@app.command()
def query(
    sql: str,
    data: str = typer.Option(None, envvar="FLIGHTDECK_DATA_URI", help="Data plane root: a directory or gs:// URI."),
) -> None:
    """Run SQL over the data plane's tables (runs, spans, events, manifests, grades, test_cases)."""
    from flightdeck.dataplane.duck import connect

    if not data:
        raise typer.BadParameter("no data plane: pass --data or set FLIGHTDECK_DATA_URI")
    con = connect(os.path.expanduser(data))  # kept: the relation reads through it
    rel = con.sql(sql)
    if rel is None:
        return
    cols = rel.columns
    typer.echo("\t".join(cols))
    for row in rel.fetchall():
        typer.echo("\t".join("" if v is None else str(v) for v in row))
