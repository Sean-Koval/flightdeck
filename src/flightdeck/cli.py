"""The `flightdeck` command line. Subcommands arrive with the issues that build them (docs/decisions/0001)."""

import os

import duckdb
import typer

from flightdeck import __version__
from flightdeck.dataplane import compact, github, ingest
from flightdeck.judges import app as judge_app
from flightdeck.metrics.weekly import app as metrics_app
from flightdeck.report import markdown
from flightdeck.runners.cache import app as cache_app
from flightdeck.runners.cli import app as experiment_app
from flightdeck.specs.cli import check_app, spec_app
from flightdeck.specs.mutate import app as mutate_app
from flightdeck.stats import compare
from flightdeck.tasks.cli import app as task_app
from flightdeck.tasks.custody import app as holdout_app
from flightdeck.tasks.knowledge import app as knowledge_app

app = typer.Typer(help="Judge coding-agent runs from hangar: paired statistics, behavior specs, task sets.",
                  no_args_is_help=True)
for _name, _sub in (("ingest", ingest.app), ("stats", compare.app), ("report", markdown.app), ("spec", spec_app),
                    ("check", check_app), ("mutate", mutate_app), ("task", task_app), ("holdout", holdout_app),
                    ("knowledge", knowledge_app), ("experiment", experiment_app), ("cache", cache_app),
                    ("metrics", metrics_app), ("judge", judge_app)):
    app.add_typer(_sub, name=_name)
app.command("compact")(compact.compact)
ingest.app.command("github")(github.prs)


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
    if (rel := con.sql(sql)) is not None:
        typer.echo("\t".join(rel.columns))
        for row in rel.fetchall():
            typer.echo("\t".join("" if v is None else str(v) for v in row))


def run(args: list[str] | None = None) -> None:
    """The console entry point. A wrong path, id or query is one line on stderr, not a traceback."""
    try:
        app(args)
    except (OSError, ValueError, duckdb.Error) as e:
        why = f"{str(e.strerror).lower()}: {e.filename}" if isinstance(e, OSError) and e.filename else str(e)
        typer.secho(f"error: {why}", fg="red", err=True)
        raise SystemExit(1) from None
