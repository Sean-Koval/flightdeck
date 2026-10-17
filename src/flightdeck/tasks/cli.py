"""`flightdeck task new|check|digest`: write, validate and hash task directories (docs/tasks.md)."""

from __future__ import annotations

import shutil
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated

import typer

from flightdeck.tasks.format import NAME, TaskError, load_task, write_digest

app = typer.Typer(help="Harbor-compatible task directories: write, check, digest.", no_args_is_help=True)


def _try(fn, *args):
    try:
        return fn(*args)
    except TaskError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


def _load(path: Path):
    return _try(load_task, path)


@app.command()
def new(path: Path, task_id: str = typer.Option(None, "--id", help="Task id (default: the directory's name).")):
    """Write a new task from the template: safe test.sh, hidden tests, Harbor task.toml."""
    task_id = task_id or path.name
    if not NAME.match(task_id):
        raise typer.BadParameter(f"task id '{task_id}': letters, digits, '.', '_', '-', at most 40 (hangar's rule)")
    if path.exists() and any(path.iterdir()):
        raise typer.BadParameter(f"{path} exists and isn't empty")
    with as_file(files("flightdeck.tasks") / "template") as src:
        shutil.copytree(src, path, dirs_exist_ok=True)
    for p in path.rglob("*.tmpl"):
        p.rename(p.with_suffix(""))
    toml = path / "task.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("{id}", task_id), encoding="utf-8")
    _try(write_digest, path)
    typer.echo(f"wrote {path}: edit instruction.md and tests/, then `flightdeck task digest --write {path}`")


@app.command()
def check(paths: list[Path]):
    """Validate task directories: layout, symlinks, files_digest, hangar's limits."""
    from flightdeck.tasks.format import to_hangar_task

    failed = 0
    for path in paths:
        try:
            task = load_task(path)
            to_hangar_task(task)
            typer.echo(f"ok  {task.id}  {task.digest}" + ("  (sealed)" if task.sealed else ""))
        except TaskError as e:
            failed += 1
            typer.secho(f"error: {e}", fg="red", err=True)
    raise typer.Exit(1 if failed else 0)


@app.command()
def digest(path: Path, write: bool = typer.Option(False, "--write", help="Update files_digest in task.toml.")):
    """Print the task digest and the tests' digest (files_digest)."""
    if write:
        _try(write_digest, path)
    task = _load(path)
    typer.echo(f"task_digest  {task.digest}\nfiles_digest {task.files_digest}")


@app.command("import-aidlc")
def import_aidlc(suite: Path, out: Annotated[Path, typer.Option(help="An empty directory to write into.")]):
    """Convert an ai-dlc evaluation suite (JSON) into task dirs, specs and a suite file; print the assertion mapping."""
    from flightdeck.tasks.aidlc import import_suite

    try:
        rows = import_suite(suite, out)
    except ValueError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None
    typer.echo("| scenario | assertion | kind | maps to |\n| --- | --- | --- | --- |")
    for r in rows:
        typer.echo("| " + " | ".join(r) + " |")
    typer.echo(f"wrote {out}: fill suite.yaml's variants, then `flightdeck task check {out}/*/`")
