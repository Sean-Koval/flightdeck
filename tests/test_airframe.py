"""Airframe (Sean-Koval/agent-factory) is flightdeck's design source of truth; see CONTRIBUTING.md#design."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "docs" / "stylesheets"
VENDORED = {"airframe.css", "airframe-docs.css"}
LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")


def test_own_stylesheets_use_airframe_tokens_only():
    for css in sorted(STYLES.glob("*.css")):
        if css.name in VENDORED:
            continue
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        assert not LITERAL.search(text), f"{css.name}: use an Airframe token (var(--af-<name>)), not a color literal"


def test_vendored_airframe_is_a_tagged_release():
    head = (STYLES / "airframe.css").read_text(encoding="utf-8")[:300]
    assert re.search(r"Airframe theme-v\d+ tokens", head), "refresh with sh scripts/sync-airframe.sh theme-vN"
