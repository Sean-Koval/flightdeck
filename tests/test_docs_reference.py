"""The generated reference pages (docs/cli.md, the Parquet columns in docs/contracts.md) match the code."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "docs_reference.py"
spec = importlib.util.spec_from_file_location("docs_reference", SCRIPT)
assert spec and spec.loader
docs_reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_reference)


def test_generated_reference_is_current() -> None:
    assert not docs_reference.stale(), "run `uv run python scripts/docs_reference.py` and commit the result"


def test_cli_reference_covers_every_command_and_option() -> None:
    import typer.main

    from flightdeck.cli import app

    page = docs_reference.cli_reference()
    for path, cmd in docs_reference.walk(typer.main.get_command(app), ()):
        assert f"### `flightdeck {' '.join(path)}`" in page
        for p in cmd.params:
            assert (f"`{p.name.upper()}`" if p.param_type_name == "argument" else f"`{p.opts[0]}`") in page
