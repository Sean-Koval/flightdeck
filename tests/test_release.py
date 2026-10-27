"""The version source agrees with itself and the changelog, and a tag is checked against both (KAN-145)."""

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release_check.py"
spec = importlib.util.spec_from_file_location("release_check", SCRIPT)
assert spec and spec.loader
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)

import flightdeck  # noqa: E402


def test_the_version_is_written_the_same_everywhere() -> None:
    assert set(release_check.versions().values()) == {flightdeck.__version__}


def test_the_current_version_has_a_changelog_section() -> None:
    notes = release_check.section(flightdeck.__version__)
    assert notes, f"CHANGELOG.md needs a '## v{flightdeck.__version__}' section"
    assert "## Unreleased" in (ROOT / "CHANGELOG.md").read_text()


def test_the_matching_tag_passes_and_prints_notes() -> None:
    problems, notes = release_check.check(f"v{flightdeck.__version__}")
    assert problems == [] and notes


def _copy(tmp: Path) -> Path:
    for f in ("pyproject.toml", "CHANGELOG.md", "src/flightdeck/__init__.py"):
        (tmp / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, tmp / f)
    return tmp


def test_a_tag_that_disagrees_or_is_malformed_fails(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    problems, _ = release_check.check("v9.9.9", root)
    assert any("pyproject.toml" in p for p in problems) and any("CHANGELOG.md" in p for p in problems)
    assert release_check.check("9.9.9", root)[0] == ["'9.9.9' is not vX.Y.Z[-pre]"]


def test_a_bump_without_a_changelog_section_fails(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    init = root / "src/flightdeck/__init__.py"
    init.write_text(init.read_text().replace(flightdeck.__version__, "0.9.0"))
    py = root / "pyproject.toml"
    py.write_text(py.read_text().replace(f'version = "{flightdeck.__version__}"', 'version = "0.9.0"'))
    assert release_check.check("v0.9.0", root)[0] == ["CHANGELOG.md has no '## v0.9.0' section"]
