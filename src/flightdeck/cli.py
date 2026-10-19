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

app = typer.Typer(no_args_is_help=True, help="Did that harness change help? Judge coding-agent runs from hangar: "
                  "ingest an experiment, compare its arms paired by task, post the verdict on the pull request.")
plumbing = typer.Typer()  # merged into `app` last (no name), so `--help` ends with the data plane and version
PANELS = {  # `--help` in the order a newcomer needs them: the three core commands first
    "Judge a change": (("ingest", ingest.app), ("stats", compare.app), ("report", markdown.app)),
    "Run experiments": (("experiment", experiment_app), ("task", task_app), ("cache", cache_app)),
    "Behavior": (("spec", spec_app), ("check", check_app), ("mutate", mutate_app)),
    "Sealed sets": (("holdout", holdout_app), ("knowledge", knowledge_app), ("judge", judge_app)),
    "Data plane": (("metrics", metrics_app),)}
for _panel, _subs in PANELS.items():
    for _name, _sub in _subs:
        app.add_typer(_sub, name=_name, rich_help_panel=_panel)
plumbing.command("compact", rich_help_panel="Data plane")(compact.compact)
ingest.app.command("github")(github.prs)


@plumbing.command(rich_help_panel="About")
def version() -> None:
    """Print flightdeck's version."""
    typer.echo(__version__)


@plumbing.command(rich_help_panel="Data plane")
def query(
    sql: str,
    data: str = typer.Option(None, envvar="FLIGHTDECK_DATA_URI", help="Data plane root: a directory or gs:// URI."),
) -> None:
    """Run SQL over the data plane's tables (runs, spans, events, manifests, grades, test_cases); tab-separated."""
    from flightdeck.dataplane.duck import connect

    if not data:
        raise typer.BadParameter("no data plane: pass --data or set FLIGHTDECK_DATA_URI")
    con = connect(os.path.expanduser(data))  # kept: the relation reads through it
    if (rel := con.sql(sql)) is not None:
        rows = ["\t".join("" if v is None else str(v) for v in row) for row in rel.fetchall()]
        typer.echo("\n".join(["\t".join(rel.columns), *rows]))


app.add_typer(plumbing)


def run(args: list[str] | None = None) -> None:
    """The console entry point. A wrong path, id or query is one line on stderr, not a traceback."""
    try:
        app(args)
    except (OSError, ValueError, duckdb.Error) as e:
        why = f"{str(e.strerror).lower()}: {e.filename}" if isinstance(e, OSError) and e.filename else str(e)
        typer.secho(f"error: {why}", fg="red", err=True)
        raise SystemExit(1) from None
