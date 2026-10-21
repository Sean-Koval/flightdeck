import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from hangar_export import CREATED, EXP, export_dir, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.dataplane.schema import write_partitioned
from flightdeck.ported import tails
from flightdeck.report import markdown
from flightdeck.stats.compare import Comparison
from flightdeck.stats.core import Interval


def report(plane: str, **kw: Any) -> str:
    return markdown.render_report(connect(plane), EXP, **kw)


def test_report_renders_from_parquet_alone_with_a_preregistered_verdict(plane: str, export_dir: Path) -> None:
    text = report(plane, decision=export_dir / "decision.yaml")
    assert text.startswith(f"<!-- flightdeck:report:{EXP} -->\n## candidate is better than control on resolved: "
                           "+21.2 pp (95% CI +1.5 to +43.9, margin −5.0)\n")  # the verdict is the headline
    order = [f"{tails.tail(EXP)} (`{EXP}`): candidate (the review skill) against control (no skills), 12 tasks, "
             "73 trials, seed 0. The arms differ in config_digest",
             "Rule, pre-registered in `decision.yaml`: resolved, higher is better, margin −5.0 pp, at least 10",
             "### Outcome", "### Process", "Tool calls", "Wall time", "### Cost", "### Behavior specs",
             "### Exclusions and drift", "Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, "
             "task_invalid 6; from the process and cost tables also truncated trace 1.", "1 drifted trial excluded",
             "<details><summary>Pins</summary>", "| config_digest | `sha256:2222", "Same in both arms: harness "
             "`claude-code 2.3.1`; model `claude-sonnet-5-1`; environment `plain`; harness_digest not recorded; "
             "environment_digest not recorded; grader `bash tests/test.sh`; hangar version `0.1.0`. Base SHAs: 12 "
             "across 12 tasks."]
    assert [text.index(s) for s in order] == sorted(text.index(s) for s in order)
    assert tails.tail(EXP) == "FDK-EXP-0531"  # a person reads the tail number first, the real ID beside it
    assert text.count("seed 0") == 1 and text.count("Excluded:") == 1 and "…" not in text  # once; no cut digests
    assert "Per task" not in text and "t05/candidate/2" not in text  # per-task details only behind --details


def test_details_put_discordant_tasks_first_with_trial_links(plane: str) -> None:
    text = report(plane, details=True, hangar="https://hangar.example")
    rows = [r for r in text.split("<details><summary>Per task")[1].splitlines() if r.startswith("| t")]
    zero = [i for i, r in enumerate(rows) if "| +0 pp |" in r]
    assert zero and zero == list(range(len(rows) - len(zero), len(rows)))
    assert f"https://hangar.example/api/experiments/{EXP}/trials/t03/control/1/trace" in text
    assert "- `t05/candidate/2`: harness drift" in text


def _commit(repo: Path, when: float) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": f"@{int(when)} +0000", "GIT_COMMITTER_DATE": f"@{int(when)} +0000"}
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    for args in (["init", "-q"], ["add", "decision.yaml"], ["commit", "-qm", "decision"]):
        subprocess.run(git + args, check=True, env=env)


@pytest.mark.parametrize("when", ["missing", "uncommitted", "committed late", "edited after commit"])
def test_no_verdict_without_a_decision_committed_before_the_trials(plane: str, tmp_path: Path, when: str) -> None:
    decision = tmp_path / "decision.yaml"
    if when != "missing":
        decision.write_text("metric: resolved\nmargin: -0.05\n")
        os.utime(decision, (CREATED - 10_000, CREATED - 10_000))  # an old mtime proves nothing
    if when == "committed late":
        _commit(tmp_path, CREATED + 100_000)
    if when == "edited after commit":
        _commit(tmp_path, CREATED - 10_000)
        decision.write_text("metric: resolved\nmargin: -0.20\n")
    text = report(plane, decision=decision)
    assert text.splitlines()[1].startswith("## No verdict: ")
    assert ("committed after" in text) == (when == "committed late")
    assert "### Outcome" in text  # the numbers are still there


def test_behavior_spec_section_gives_pass_rates_per_spec_per_variant(plane: str, tmp_path: Path) -> None:
    assert "No behavior-spec results for these trials" in report(plane)
    copy = tmp_path / "plane"
    shutil.copytree(plane, copy)
    rows = [{"run_id": f"{EXP}/t03/{v}/{n}", "source": "experiment", "dt": "2025-10-16", "spec_id": "tests-before-pr",
             "spec_source": "spec", "scope": "turn", "result": "pass" if v == "candidate" or n == 1 else "fail"}
            for v in ("control", "candidate") for n in (1, 2, 3)]
    rows += [{**rows[0], "spec_id": "no-force-push", "spec_source": "adr:team/0007", "result": "not_applicable"},
             {**rows[0], "run_id": f"{EXP}/t08/control/1", "spec_id": "tests-before-pr"}]  # t08: task_invalid
    write_partitioned("spec_results", rows, str(copy), "check-2025-10-16")
    text = report(str(copy))
    section = text.split("### Behavior specs")[1].split("###")[0]
    # t03/candidate/3 was infra_error (excluded); its retry 3~2 has no spec result: 2 candidate trials count
    assert "| tests-before-pr | 1 of 3 (33%) | 2 of 2 (100%) |" in section
    assert "no-force-push" not in section  # not applicable everywhere: no rate


def _c(est: float, lo: float, hi: float, n: int = 20, metric: str = "resolved", note: str = "") -> Comparison:
    c = Comparison("e", metric, "A", "B", 0)
    c.diff = Interval(est, lo, hi, n_tasks=n, note=note)
    return c


@pytest.mark.parametrize(("c", "rule", "start"), [
    (_c(-0.02, -0.04, 0.01), {"margin": "-0.05"}, "B is non-inferior to A on resolved: −2.0 pp (95% CI −4.0 to +1.0, "
                                                   "margin −5.0)."),
    (_c(0.10, 0.02, 0.2), {}, "B is better than A"),
    (_c(-0.2, -0.3, -0.1), {"margin": "0.05"}, "B is worse than A"),
    (_c(0.0, -0.2, 0.2), {"margin": "-0.05"}, "No decision: the interval on resolved spans the margin, +0.0 pp"),
    (_c(0.3, 0.1, 0.5, n=5), {"min_tasks": "10"}, "No decision: underpowered (5 paired tasks"),
    (_c(-0.1, -0.15, -0.05, metric="cost_usd"), {"direction": "lower"}, "B is better than A on cost_usd: +$0.10 (95% "
                                                                         "CI +0.05 to +0.15, margin +0.00)."),
])
def test_verdict_rules(c: Comparison, rule: dict, start: str) -> None:
    assert markdown.verdict(rule, c).startswith(start)


def test_read_decision(tmp_path: Path) -> None:
    f = tmp_path / "decision.yaml"
    f.write_text("# pre-registered\nmetric: resolved  # outcome\nmargin: -0.05\n\nmin_tasks: 10\n")
    assert markdown.read_decision(f) == {"metric": "resolved", "margin": "-0.05", "min_tasks": "10"}


class FakeGitHub:
    def __init__(self, existing: int = 0):
        self.comments = [{"id": i, "body": f"other {i}", "html_url": f"u/{i}"} for i in range(existing)]
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, token: str, body: dict | None = None) -> Any:
        self.calls.append((method, url))
        assert token == "t" and url.startswith("https://api.github.com/repos/o/r/issues")
        if method == "GET":
            page = int(url.rsplit("page=", 1)[1])
            return self.comments[(page - 1) * 100: page * 100]
        if method == "POST":
            self.comments.append({"id": 1000 + len(self.comments), "body": body and body["body"], "html_url": "new"})
            return self.comments[-1]
        c = next(c for c in self.comments if url.endswith(f"/comments/{c['id']}"))
        c["body"] = body and body["body"]
        return {**c, "html_url": "updated"}


def test_posting_twice_updates_one_comment(plane: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    gh, text = FakeGitHub(existing=150), report(plane)  # two pages of other comments
    assert markdown.post(text, "o/r#7", "t", gh=gh) == "new"
    assert markdown.post(text.replace("seed 0", "seed 0 (again)"), "o/r#7", "t", gh=gh) == "updated"
    ours = [c for c in gh.comments if c["body"].startswith(markdown.marker(EXP))]
    assert len(ours) == 1 and "(again)" in ours[0]["body"]
    assert [m for m, _ in gh.calls] == ["GET", "GET", "POST", "GET", "GET", "PATCH"]


def test_post_refuses_secrets_bad_targets_and_clips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    head = markdown.marker("e") + "\n"
    with pytest.raises(ValueError, match="secret-looking"):
        markdown.post(head + "token ghp_" + "a" * 36, "o/r#1", "t", gh=FakeGitHub())
    with pytest.raises(ValueError, match="owner/repo#number"):
        markdown.post(head, "o/r", "t", gh=FakeGitHub())
    with pytest.raises(ValueError, match="https:// URL"):
        markdown.post(head, "o/r#1", "t", full="report.md", gh=FakeGitHub())
    gh, url = FakeGitHub(), "https://github.com/team/flightdeck-data/blob/main/reports/e.md"
    markdown.post(head + "x" * 70_000, "o/r#1", "t", full=url, gh=gh)
    body = gh.comments[-1]["body"]
    assert len(body) <= markdown.LIMIT and body.rstrip().endswith(f"[full report]({url}).*")
    markdown.post(markdown.marker("f") + "\n" + "x" * 70_000, "o/r#1", "t", gh=gh)
    assert gh.comments[-1]["body"].rstrip().endswith("the full report is not linked (`--full-url` or `--gist`).*")


def test_a_clipped_report_can_link_a_secret_gist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    calls: list[tuple[str, str, dict | None]] = []

    def gh(method: str, url: str, token: str, body: dict | None = None) -> Any:
        calls.append((method, url, body))
        return [] if method == "GET" else {"html_url": "https://gist.github.com/x/1" if "gists" in url else "c"}

    text = markdown.marker("e") + "\n" + "x" * 70_000
    markdown.post(text, "o/r#1", "t", gist=True, gh=gh)
    method, url, body = calls[0]
    assert (method, url) == ("POST", "https://api.github.com/gists") and body
    assert body["public"] is False and body["files"]["report.md"]["content"] == text
    assert "[full report](https://gist.github.com/x/1)" in (calls[-1][2] or {})["body"]


def test_report_cli_writes_and_posts(plane: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, str | None]] = []
    monkeypatch.setattr(markdown, "post",
                        lambda text, target, token, full=None, gist=False: posted.append((target, full)) or "u")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    out = tmp_path / "report.md"
    args = ["report", "experiment", EXP, "--data", plane, "--out", str(out), "--post", "o/r#9"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert out.read_text().startswith(markdown.marker(EXP)) and posted == [("o/r#9", None)]  # never a local path
    lines = result.output.splitlines()  # the verdict and what was written, not the markdown
    assert lines[0] == "No verdict: no pre-registered decision.yaml" and lines[1].startswith(f"wrote {out} (")
    shown = CliRunner().invoke(app, ["report", "experiment", EXP, "--data", plane]).output
    assert shown.startswith("No verdict: ") and "**" not in shown and "<!--" not in shown
    result = CliRunner().invoke(app, ["report", "post", str(out), "--to", "o/r#10", "--full-url", "https://x/r.md"])
    assert result.exit_code == 0 and posted[-1] == ("o/r#10", "https://x/r.md")
