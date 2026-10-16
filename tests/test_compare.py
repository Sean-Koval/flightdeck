import pytest
from hangar_export import EXP, export_dir, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.stats.compare import compare, exclusion, load_trials, render, resolved


@pytest.fixture(scope="module")
def trials(plane: str) -> list[dict]:
    return load_trials(connect(plane), EXP)


def test_resolved_comparison_lists_exclusions_definition_and_saturated_tasks(trials: list[dict]) -> None:
    c = compare(trials, "resolved", "control", "treat")
    assert c.excluded == {"cancelled": 1, "drift": 1, "infra_error": 1, "not finished": 1, "task_invalid": 6}
    assert c.resolved_from == {"grader": 62} and c.saturated == ["t01", "t02"]
    assert c.diff is not None and c.diff.n_tasks == 11 and c.diff.seed == 0
    assert c.concordant + c.discordant == 11 and c.concordant >= 2
    out = render(c)
    for text in ("95% Wilson", "Paired difference treat - control", "95% CI", "11 tasks, 62 trials",
                 "Resolved: grader for 62 trials", "Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, "
                 "task_invalid 6", "Saturated", "minimum detectable lift", "seed 0"):
        assert text in out, text
    assert "p=" not in out and "p-value" not in out  # no p-value without its interval


def test_truncated_traces_are_excluded_from_process_metrics_only(trials: list[dict]) -> None:
    t07 = next(t for t in trials if t["trial_key"] == "t07/control/1")
    assert t07["truncated"] and exclusion(t07, "resolved") is None
    assert exclusion(t07, "tool_calls") == "truncated trace"
    c = compare(trials, "tool_calls", "control", "treat")
    assert c.excluded["truncated trace"] == 1 and c.diff is not None and c.diff.estimate < 0
    assert compare(trials, "cost_usd", "control", "treat").arms["treat"]["per_resolved"] is not None


def test_include_drift_keeps_drifted_trials(trials: list[dict]) -> None:
    c = compare(trials, "resolved", "control", "treat", include_drift=True)
    assert "drift" not in c.excluded and c.diff is not None and c.diff.n_trials == 63


def test_verify_fallback_infra_outcome_and_unknown_values() -> None:
    base = {"experiment_id": "e", "variant": "a", "task_id": "x", "trial_key": "x/a/1", "outcome": "succeeded",
            "reason": None, "drift": [], "truncated": False, "task_invalid": None, "contaminated": None,
            "grade_exit": None, "grade_applied": None, "verify_passed": True, "cost_usd": None, "tool_calls": 3}
    assert resolved(base) == (True, "verify")
    assert resolved({**base, "grade_exit": 0, "grade_applied": False}) == (False, "grader")
    assert exclusion({**base, "outcome": "infra_error"}, "resolved") == "infra_error"
    assert exclusion({**base, "outcome": "failed", "reason": "capacity exhausted"}, "resolved") == "infra_error"
    assert exclusion({**base, "outcome": "failed", "reason": "tests failed"}, "resolved") is None
    assert exclusion({**base, "contaminated": True}, "resolved") == "contaminated"
    assert exclusion({**base, "verify_passed": None}, "resolved") == "no grade or verify"
    assert exclusion(base, "cost_usd") == "unknown cost_usd"


def test_few_tasks_are_labelled_underpowered(trials: list[dict]) -> None:
    few = [t for t in trials if t["task_id"] in ("t03", "t04", "t05")]
    assert "underpowered: fewer than 10 paired tasks, do not decide on this" in render(
        compare(few, "resolved", "control", "treat"))


def test_unknown_metric_is_refused(trials: list[dict]) -> None:
    with pytest.raises(ValueError, match="metric must be one of"):
        compare(trials, "vibes", "control", "treat")


def test_stats_compare_cli(plane: str) -> None:
    result = CliRunner().invoke(app, ["stats", "compare", EXP, "--data", plane, "--metric", "wall_s"])
    assert result.exit_code == 0, result.output
    assert "**wall_s**: treat vs control" in result.output and "truncated trace 1" in result.output
    missing = CliRunner().invoke(app, ["stats", "compare", "nope", "--data", plane])
    assert missing.exit_code == 2
