"""`flightdeck task new|check|digest`: write, validate and hash task directories (docs/tasks.md)."""

from __future__ import annotations

import re
import shutil
from importlib.resources import as_file, files
from pathlib import Path

import typer

from flightdeck.tasks.format import NAME, TaskError, load_task

app = typer.Typer(help="Harbor-compatible task directories: write, check, digest.", no_args_is_help=True)
_DIGEST_LINE = re.compile(r'^(files_digest\s*=\s*)"[^"]*"', re.M)


def _load(path: Path):
    try:
        return load_task(path)
    except TaskError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


def _write_digest(path: Path, digest: str) -> None:
    toml = path / "task.toml"
    text = toml.read_text(encoding="utf-8")
    if not _DIGEST_LINE.search(text):
        raise typer.BadParameter(f"{toml}: no files_digest line under [flightdeck.grader] to write")
    toml.write_text(_DIGEST_LINE.sub(rf'\g<1>"{digest}"', text, count=1), encoding="utf-8")


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
    _write_digest(path, _load(path).files_digest)
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
        toml = path / "task.toml"
        saved = toml.read_text(encoding="utf-8")
        _write_digest(path, "")  # recompute from the files, whatever the old value was
        try:
            _write_digest(path, _load(path).files_digest)
        except typer.Exit:
            toml.write_text(saved, encoding="utf-8")
            raise
    task = _load(path)
    typer.echo(f"task_digest  {task.digest}\nfiles_digest {task.files_digest}")
