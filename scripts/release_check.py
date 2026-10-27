"""Check a release tag against the version source and print its changelog section (KAN-145).

usage: python scripts/release_check.py vX.Y.Z > notes.md

Fails when the tag isn't vX.Y.Z[-pre], when pyproject.toml and src/flightdeck/__init__.py disagree with it, or when
CHANGELOG.md has no `## vX.Y.Z` section. The section's body is what the GitHub release carries as notes.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def versions(root: Path = ROOT) -> dict[str, str]:
    """Each place the version is written, by file."""
    init = (root / "src" / "flightdeck" / "__init__.py").read_text()
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    return {
        "pyproject.toml": tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
        "src/flightdeck/__init__.py": m.group(1) if m else "",
    }


def section(version: str, root: Path = ROOT) -> str | None:
    """The body of CHANGELOG.md's `## v<version>` section, or None."""
    text = (root / "CHANGELOG.md").read_text()
    m = re.search(rf"^## v{re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def check(tag: str, root: Path = ROOT) -> tuple[list[str], str]:
    """(problems, notes) for a tag."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", tag):
        return [f"{tag!r} is not vX.Y.Z[-pre]"], ""
    want = tag[1:]
    problems = [f"{f} says {v!r}, the tag says {want!r}" for f, v in versions(root).items() if v != want]
    notes = section(want, root)
    if notes is None:
        problems.append(f"CHANGELOG.md has no '## v{want}' section")
    return problems, notes or ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    problems, notes = check(argv[0])
    for p in problems:
        print(f"release_check: {p}", file=sys.stderr)
    if problems:
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
