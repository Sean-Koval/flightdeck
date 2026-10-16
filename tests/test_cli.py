from typer.testing import CliRunner

from flightdeck import __version__
from flightdeck.cli import app


def test_help_and_version() -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and __version__ in result.output
