import pytest
from hangar_export import EXP, export_dir, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.stats.compare import compare, exclusion, fmt, load_trials, plain, ratio, render, resolved


@pytest.fixture(scope="module")
def trials(plane: str) -> list[dict]:
    return load_trials(connect(plane), EXP)


def test_resolved_comparison_lists_exclusions_definition_and_saturated_tasks(trials: list[dict]) -> None:
    c = compare(trials, "resolved", "control", "treat")
    assert c.excluded == {"cancelled": 1, "drift": 1, "infra_error": 1, "not finished": 1, "task_invalid": 6}
    assert c.resolved_from == {"grader": 63} and c.saturated == ["t01", "t02"]  # t03's retry counts, not its attempt 1
    assert c.diff is not None and c.diff.n_tasks == 11 and c.diff.seed == 0
    assert c.concordant + c.discordant == 11 and c.concordant >= 2
    out = render(c)
    for text in ("95% Wilson", "Paired difference treat − control", "95% CI", "11 tasks, 63 trials",
                 "Resolved: grader for 63 trials", "Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, "
                 "task_invalid 6", "Saturated", "minimum detectable lift", "seed 0", "| 10 of 32 (31%) | 18% to 49% |",
                 "paired tasks × 3 trials", "$1.33 ($0.80 to $2.79)"):
        assert text in out, text
    assert "p=" not in out and "p-value" not in out  # no p-value without its interval
    assert "10/32" not in out and " - control" not in out and " x 3 " not in out  # ratios in words, minus sign, ×
    assert "Excluded" not in render(c, full=False) and "**resolved**" not in render(c, full=False)


def test_numbers_follow_the_brand_book() -> None:
    assert [fmt("resolved", v) for v in (0.312, None)] == ["31%", "—"]
    assert fmt("resolved", 0.212, True) == "+21.2 pp" and fmt("resolved", -0.05, True) == "−5.0 pp"
    assert fmt("cost_usd", 0.42) == "$0.42" and fmt("cost_usd", -0.092, True) == "−$0.09"
    assert fmt("wall_s", 174.935) == "174.9 s" and fmt("tool_calls", -0.682, True) == "−0.7 calls"
    assert ratio(10, 32) == "10 of 32 (31%)" and ratio(0, 0) == "—"


def test_truncated_traces_are_excluded_from_process_metrics_only(trials: list[dict]) -> None:
    t07 = next(t for t in trials if t["trial_key"] == "t07/control/1")
    assert t07["truncated"] and exclusion(t07, "resolved") is None
    assert exclusion(t07, "tool_calls") == "truncated trace"
    c = compare(trials, "tool_calls", "control", "treat")
    assert c.excluded["truncated trace"] == 1 and c.diff is not None and c.diff.estimate < 0
    assert "| variant | trials | mean |" in render(c) and "$ per resolved" not in render(c)  # no empty column
    assert "| control | 31 | 3.0 calls |" in render(c)
    assert compare(trials, "cost_usd", "control", "treat").arms["treat"]["per_resolved"] is not None


def test_include_drift_keeps_drifted_trials(trials: list[dict]) -> None:
    c = compare(trials, "resolved", "control", "treat", include_drift=True)
    assert "drift" not in c.excluded and c.diff is not None and c.diff.n_trials == 64


def test_verify_fallback_infra_outcome_and_unknown_values() -> None:
    base = {"experiment_id": "e", "variant": "a", "task_id": "x", "trial_key": "x/a/1", "outcome": "succeeded",
            "reason": None, "drift": [], "truncated": False, "task_invalid": None, "contaminated": None,
            "grade_exit": None, "grade_applied": None, "verify_passed": True, "cost_usd": None, "tool_calls": 3}
    assert resolved(base) == (True, "verify")
    assert resolved({**base, "grade_exit": 0, "grade_applied": False}) == (False, "grader")
    failed = {**base, "outcome": "failed"}
    infra = {**failed, "outcome_class": "infra_error", "infra_reason": "preempted"}
    assert exclusion(infra, "resolved") == "infra_error"
    assert exclusion({**failed, "excluded": True}, "resolved") == "infra_error"
    # hangar's class decides, not the failure reason: no class is unknown, never read as infrastructure's
    assert exclusion({**failed, "reason": "sandbox pool capacity exhausted"}, "resolved") is None
    assert exclusion({**failed, "outcome_class": "agent", "reason": "provider quota"}, "resolved") is None
    assert exclusion({**base, "outcome_class": "human"}, "resolved") == "human"
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


def test_stats_compare_cli_prints_a_readout_or_markdown(plane: str) -> None:
    result = CliRunner().invoke(app, ["stats", "compare", EXP, "--data", plane, "--metric", "wall_s"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("wall_s: treat vs control") and "truncated trace 1" in result.output
    assert "**" not in result.output and "| ---" not in result.output and "VARIANT  TRIALS" in result.output
    md = CliRunner().invoke(app, ["stats", "compare", EXP, "--data", plane, "--metric", "wall_s", "--md"])
    assert md.output.startswith("**wall_s**: treat vs control") and "| --- |" in md.output
    missing = CliRunner().invoke(app, ["stats", "compare", "nope", "--data", plane])
    assert missing.exit_code == 2


def test_plain_turns_markdown_into_aligned_columns() -> None:
    md = "**resolved**: `e`, seed 0\n\n| variant | trials | rate |\n| --- | --- | --- |\n| control | 32 | 31.2% |\n" \
         "| treat | 310 | - |\n\n### Next\n<!-- marker -->\nPaired difference: **+21.2 pp**."
    assert plain(md).splitlines() == ["resolved: e, seed 0", "", "VARIANT  TRIALS   RATE", "control      32  31.2%",
                                      "treat       310      -", "", "Next", "Paired difference: +21.2 pp."]
