"""The `flightdeck` command line. Subcommands arrive with the issues that build them (docs/decisions/0001)."""

import typer

from flightdeck import __version__

app = typer.Typer(
    help="Judge coding-agent runs from hangar: paired statistics, behavior specs, task sets.", no_args_is_help=True
)


@app.callback()
def main() -> None:
    """flightdeck: reads hangar runs, owns sampling and analysis."""


@app.command()
def version() -> None:
    """Print flightdeck's version."""
    typer.echo(__version__)
