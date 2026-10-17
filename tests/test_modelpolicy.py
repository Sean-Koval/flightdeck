"""flightdeck's model rule is hangar's (#167): hangar's own test table, run against the port and the runner's gate."""

import json
from pathlib import Path

import pytest

from flightdeck.ported import modelpolicy
from flightdeck.runners.hangar import model_problem

TABLE = json.loads((Path(__file__).resolve().parent / "fixtures" / "hangar" / "model_concreteness.json").read_text())


@pytest.mark.parametrize(("harness", "model", "want"), [tuple(c) for c in TABLE["cases"]])
def test_hangars_concreteness_table(harness: str, model: str | None, want: bool) -> None:
    assert modelpolicy.is_concrete(harness, model) is want
    assert (model_problem(model, harness=harness) is None) is want  # suites, status and ingest share the rule


def test_a_listed_id_is_concrete_but_a_listed_alias_never_is() -> None:
    assert modelpolicy.concreteness("claude-code", "claude-opus-5", [{"id": "claude-opus-5"}]) == (True, "list")
    assert modelpolicy.concreteness("codex", "gpt-5", [{"id": "gpt-5"}]) == (False, "alias")
    assert modelpolicy.concreteness("antigravity", "gemini-3.1-pro-high", [{"id": "gemini-3.1-pro-preview"}])[0]
