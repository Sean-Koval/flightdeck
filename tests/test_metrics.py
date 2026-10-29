"""Weekly team metrics (#6) on a synthetic week: the outbox compacted, plus GitHub PRs, with known answers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import fsspec
import jsonschema
import pytest
from hangar_outbox import write_event, write_run
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import compact, github
from flightdeck.dataplane.duck import connect
from flightdeck.metrics import weekly

WEEK = "2026-W45"  # Mon 2026-11-02 .. Sun 2026-11-08
SCHEMA = Path(weekly.__file__).with_name("weekly.schema.json")


def pull(n: int, title: str, merged: str | None, closed: str | None = None, body: str = "", sha: str = "",
         bot: bool = True) -> dict:
    return {"number": n, "title": title, "body": body, "html_url": f"https://github.com/acme/app/pull/{n}",
            "user": {"login": "hangar[bot]" if bot else "dev", "type": "Bot" if bot else "User"},
            "created_at": "2026-10-01T00:00:00Z", "merged_at": merged, "closed_at": closed or merged,
            "merge_commit_sha": sha or None, "updated_at": closed or merged}


PULLS = [
    pull(1, "Fix a", "2026-11-03T14:00:00Z"), pull(6, "Fix b", "2026-11-05T12:00:00Z"),
    pull(100, "Human change", "2026-11-04T09:00:00Z", bot=False),
    pull(8, "Feature eight", "2026-10-20T12:00:00Z", sha="bbbb8888cccc"),
    pull(9, "Feature nine", "2026-10-21T12:00:00Z"),
    pull(101, 'Revert "Feature eight"', "2026-10-25T12:00:00Z", body="Reverts acme/app#8"),
    pull(102, "Back out", "2026-10-26T12:00:00Z", body="This reverts commit bbbb8888."),
    pull(103, 'Revert "Feature nine"', "2026-11-20T12:00:00Z"),  # more than 14 days after #9 merged
]


# hangar's outcome labels on a merge (KAN-232); job-7 merged with none
LABELS1 = {"agent_added_lines": 10, "merged_added_lines": 12, "surviving_lines": 8, "survival_at_merge": 0.8,
           "human_commits": 1, "review_rounds": 2}


@pytest.fixture(scope="module")
def plane(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("week")
    src, out = root / "outbox", str(root / "plane")
    runs = [("job-1", "2026-11-03", "ana", {"steers": {"n": 1, "by_class": {}}}), ("job-2", "2026-11-03", "ana", {}),
            ("job-3", "2026-11-04", "bob", {}), ("job-4", "2026-11-04", "bob",
                                                 {"outcome_class": "infra_error", "job_state": "failed"}),
            ("job-6", "2026-11-05", "ana", {}), ("job-7", "2026-11-05", "ana", {})]
    for i, (job, day, person, kw) in enumerate(runs, 1):
        write_run(src, day, f"ses-{job}", f"run-0000000{i}", job=job, person=person, **kw)
    ev = [("job-1", "2026-11-03", "pr.open", 10, {}), ("job-1", "2026-11-03", "review.first", 12, {"by": "bob"}),
          ("job-1", "2026-11-03", "pr.merge", 14, {"green_to_merge_seconds": 3600, **LABELS1}),
          ("job-2", "2026-11-03", "pr.open", 10, {}), ("job-2", "2026-11-04", "review.first", 10, {}),
          ("job-2", "2026-11-04", "pr.close", 12, {}),
          ("job-3", "2026-11-04", "abandon", 15, {"reason": "flaky_env", "person": "bob"}),
          ("job-5", "2026-11-04", "abandon", 16, {"reason": "other", "run_ids": []}),  # cancelled before it started
          ("job-6", "2026-11-05", "pr.merge", 12, {"green_to_merge_seconds": 7200, "agent_added_lines": 10,
                                                   "merged_added_lines": 10, "surviving_lines": 10}),
          ("job-7", "2026-11-05", "pr.merge", 13, {"green_to_merge_seconds": 10800}),
          ("job-8", "2026-10-20", "pr.merge", 12, {}), ("job-9", "2026-10-21", "pr.merge", 12, {})]
    for job, day, kind, hour, data in ev:
        write_event(src, day, job, kind, hour, **data)
    CliRunner().invoke(app, ["compact", "--date", "2026-11-05", "--lookback", "20", "--input", str(src), "--out", out])
    rows = github.pr_rows("acme/app", PULLS, datetime(2026, 10, 1, tzinfo=UTC))
    fs, base = fsspec.core.url_to_fs(out)
    for day in sorted({r["dt"] for r in rows}):
        compact.write_partition(fs, base, "prs", day, [r for r in rows if r["dt"] == day])
    return out


def test_revert_detection_from_body_sha_and_title() -> None:
    rows = {r["number"]: r["reverts"] for r in github.pr_rows("acme/app", PULLS, datetime(2026, 10, 1, tzinfo=UTC))}
    assert rows[101] == 8 and rows[102] == 8 and rows[103] == 9 and rows[1] is None


def test_every_metric_on_a_synthetic_week(plane: str) -> None:
    m = weekly.build(plane, WEEK)["metrics"]
    assert (m["yield"]["k"], m["yield"]["n"]) == (3, 5)  # job-4 infra_error and job-5 never-started are left out
    assert (m["abandon"]["k"], m["abandon"]["n"], m["abandon"]["by_reason"]) == (2, 5, {"flaky_env": 1,
                                                                                       "unlabelled": 1})
    assert (m["agent_share"]["k"], m["agent_share"]["n"]) == (2, 3)
    assert m["review_wait"] == {"n": 2, "p50_h": pytest.approx(13.0), "p90_h": pytest.approx(21.8)}
    assert m["green_to_merge"] == {"n": 3, "p50_h": pytest.approx(2.0), "p90_h": pytest.approx(2.8)}
    assert m["steer_rate"] == {"n": 3, "value": pytest.approx(1 / 3)}
    assert m["cost_per_merged_pr"] == {"n": 3, "value": pytest.approx(1.5)}
    assert (m["revert"]["k"], m["revert"]["n"]) == (1, 2)  # cohort: merged in 2026-W43
    assert m["survival_at_merge"] == {"n": 2, "value": pytest.approx(18 / 20)}  # lines, pooled; job-7 has no labels
    assert m["human_edit_share"] == {"n": 2, "value": pytest.approx(4 / 22)}
    assert m["active_delegators"] == {"value": 1, "n": 2}
    assert m["infra_errors"] == {"value": 1}
    lo, hi = m["yield"]["ci95"]
    assert lo < 0.6 < hi


def test_pr_outcomes_per_agent_pr(plane: str) -> None:
    con = connect(plane)
    con.execute(files("flightdeck.metrics").joinpath("weekly.sql").read_text(encoding="utf-8"))
    for name in ("person", "repo"):
        con.execute(f"set variable {name} = ?", [None])
    rows = con.sql("select job_id, survival_at_merge, human_edit_share, human_commits, review_rounds from pr_outcomes"
                   " where job_id in ('job-1', 'job-7') order by 1").fetchall()
    assert rows == [("job-1", 0.8, pytest.approx(4 / 12), 1, 2), ("job-7", None, None, None, None)]


def test_person_and_repo_scope(plane: str) -> None:
    bob = weekly.build(plane, WEEK, person="bob")["metrics"]
    assert (bob["yield"]["k"], bob["yield"]["n"]) == (0, 1) and bob["infra_errors"] == {"value": 1}
    other = weekly.build(plane, WEEK, repo="acme/other")["metrics"]
    assert other["yield"]["n"] == 0 and other["yield"]["rate"] is None


def test_cli_writes_latest_json_valid_against_the_schema(plane: str, tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["metrics", "weekly", "--week", WEEK, "--data", plane, "--reports", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "60% (23%-88%, 3/5)" in out.output  # under 20 observations: the interval, not only the point estimate
    assert "2026-W42 | 2026-W43 | 2026-W44 | 2026-W45" in out.output
    assert "| 90% (n=2) |" in out.output and "| 18% (n=2) |" in out.output  # survival, human-edit share
    latest = json.loads((tmp_path / "weekly" / "latest.json").read_text())
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text())).validate(latest)
    assert (tmp_path / "weekly" / f"{WEEK}.md").read_text() == out.output.rstrip("\n") + "\n"
    assert [t["week"] for t in latest["trailing"]] == ["2026-W42", "2026-W43", "2026-W44", "2026-W45"]


def test_slack_blocks_and_scoped_runs_write_no_shared_files(plane: str, tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["metrics", "weekly", "--week", WEEK, "--format", "slack", "--person", "ana",
                                   "--data", plane, "--reports", str(tmp_path)])
    assert out.exit_code == 0, out.output
    blocks = json.loads(out.output)["blocks"]
    assert blocks[0]["type"] == "header" and "*Agent PR yield*" in blocks[1]["text"]["text"]
    assert not (tmp_path / "weekly").exists()
