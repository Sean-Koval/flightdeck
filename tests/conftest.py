"""Shared pytest settings and fixtures."""

import contextlib
import io
import re
from collections.abc import Callable

import pytest

# Vendored tasks under fixtures/ carry their own hidden tests (Harbor runs them in a container), not flightdeck's.
collect_ignore = ["fixtures"]
ANSI = re.compile(r"\x1b\[[0-9;]*m")  # CI forces color on; the tests read words


@pytest.fixture
def entry() -> Callable[[list[str]], tuple[int, str]]:
    """Run the console entry point (`flightdeck.cli.run`), which prints a wrong path, id or query as one line;
    `CliRunner` invokes the Typer app underneath it. Returns (exit code, stdout and stderr without ANSI colors)."""
    from flightdeck import cli

    def invoke(args: list[str]) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.run(args)
            except SystemExit as e:
                return int(e.code or 0), ANSI.sub("", out.getvalue() + err.getvalue())
        return 0, ANSI.sub("", out.getvalue() + err.getvalue())

    return invoke
