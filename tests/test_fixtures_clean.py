"""ADR-0002: test fixtures are synthetic. Fail when one matches the deny-list."""

import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _patterns() -> list[re.Pattern[str]]:
    lines = (FIXTURES / "deny.txt").read_text(encoding="utf-8").splitlines()
    return [re.compile(x) for x in lines if x.strip() and not x.startswith("#")]


def test_fixtures_match_no_denied_pattern() -> None:
    patterns = _patterns()
    hits = []
    for path in FIXTURES.rglob("*"):
        if path.is_file() and path.name != "deny.txt":
            text = path.read_text(encoding="utf-8", errors="replace")
            hits += [f"{path.name}: {p.pattern}" for p in patterns if p.search(text)]
    assert not hits, hits


def test_deny_list_catches_a_key() -> None:
    assert any(p.search("token sk-ant-" + "a" * 30) for p in _patterns())
