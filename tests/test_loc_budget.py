import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "loc_budget.py"
spec = importlib.util.spec_from_file_location("loc_budget", SCRIPT)
assert spec and spec.loader
loc_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loc_budget)


def _tree(root: Path, stats_lines: int, ported_lines: int) -> Path:
    pkg = root / "flightdeck"
    (pkg / "stats").mkdir(parents=True)
    (pkg / "ported").mkdir()
    (pkg / "__init__.py").write_text('"""doc"""\n\n# a comment\n')
    (pkg / "stats" / "core.py").write_text("x = 1\n\n" * stats_lines)
    (pkg / "ported" / "old.py").write_text("y = 2\n" * ported_lines)
    return pkg


def test_under_budget_passes_and_lists_areas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pkg = _tree(tmp_path, stats_lines=9, ported_lines=500)
    assert loc_budget.main(["--root", str(pkg), "--limit", "10"]) == 0
    out = capsys.readouterr().out
    assert "stats/" in out and "(top level)" in out
    assert "ported/" in out and "(excluded)" in out
    assert "10 / 10" in out  # 9 + the docstring line; comments and blanks don't count


def test_over_budget_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pkg = _tree(tmp_path, stats_lines=11, ported_lines=0)
    assert loc_budget.main(["--root", str(pkg), "--limit", "10"]) == 1
    assert "over the v0 budget" in capsys.readouterr().err


def test_repository_is_within_budget() -> None:
    assert loc_budget.main([]) == 0
