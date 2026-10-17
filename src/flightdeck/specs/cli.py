"""`flightdeck spec lint|test`: behavior specs against one trace export (docs/behavior-specs.md)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from flightdeck.specs import lang

spec_app = typer.Typer(help="Behavior specs over hangar.trace/v1: lint them, test them on an export.",
                       no_args_is_help=True)


@spec_app.command("lint")
def lint(paths: list[Path]) -> None:
    """Load specs and print warnings; exit 1 when one does not load."""
    bad = 0
    for p in paths:
        try:
            specs = lang.load(p.read_text())
        except (lang.SpecError, ValueError) as e:
            typer.echo(f"{p}: error: {e}")
            bad = 1
            continue
        for s in specs:
            for w in lang.lint(s):
                typer.echo(f"{p}: warning: {w}")
    raise typer.Exit(bad)


@spec_app.command("test")
def test(
    spec: Path,
    trace: Annotated[Path, typer.Option(help="A hangar.trace/v1 OTLP/JSON export.")],
    engine: Annotated[str, typer.Option(help="python (the reference evaluator) or sql (the nightly one).")] = "python",
) -> None:
    """Evaluate specs on one export: `spec<TAB>unit<TAB>result` lines; exit 1 on any fail or unknown."""
    from flightdeck.dataplane.flatten import flatten_trace

    tables = flatten_trace(json.loads(trace.read_text()))
    con = lang.connect_tables(tables) if engine == "sql" else None
    worst = False
    for s in lang.load(spec.read_text()):
        res = lang.evaluate_sql(s, con) if con else lang.evaluate(s, tables)
        for unit, r in sorted(res.items()):
            typer.echo(f"{s['id']}\t{unit}\t{r}")
            worst |= r in (lang.FAIL, lang.UNKNOWN)
    raise typer.Exit(int(worst))
