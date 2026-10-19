from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from flightdeck import __version__
from flightdeck.cli import app


def test_help_and_version() -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and __version__ in result.output


@pytest.mark.parametrize("args", [
    ["ingest", "export", "{p}", "--out", "{p}/plane"],
    ["stats", "compare", "job-expdemo", "--data", "{p}"],
    ["report", "experiment", "job-expdemo", "--data", "{p}"],
    ["report", "experiment", "job-expdemo", "--data", "{p}", "--decision", "{p}/decision.yaml"],
    ["report", "post", "{p}/report.md", "--to", "o/r#1"],
    ["check", "run", "--data", "{p}", "--date", "2025-10-16", "--specs", "{p}/specs"],
    ["spec", "lint", "{p}/spec.yaml"],
    ["spec", "test", "{p}/spec.yaml", "--trace", "{p}/trace.json"],
    ["mutate", "plan", "{p}/suite.yaml", "--harness", "base", "--out", "{p}/mutants.yaml"],
    ["task", "check", "{p}/task"],
    ["task", "digest", "{p}/task"],
    ["task", "import-aidlc", "{p}/suite.json", "--out", "{p}/out"],
    ["holdout", "seal", "set-1", "--writer", "w=me", "--holdouts", "{p}/holdouts"],
    ["knowledge", "seal", "{p}/gold.json"],
    ["judge", "calibrate", "{p}/rubric.yaml", "{p}/human.json", "{p}/judge.json"],
    ["experiment", "status", "{p}/plan.yaml"],
    ["query", "select_1 from nowhere", "--data", "{p}"],
])
def test_a_wrong_path_or_id_is_one_line_not_a_traceback(entry: Callable, tmp_path: Path, args: list[str]) -> None:
    missing = tmp_path / "nonexistent"
    code, output = entry([a.replace("{p}", str(missing)) for a in args])
    assert code in (1, 2), output
    assert "Traceback" not in output and "File \"" not in output, output
    assert len([ln for ln in output.splitlines() if ln.strip()]) <= 6, output  # one line, or Typer's usage box
    assert output.lstrip().startswith(("error: ", "Usage:")), output
