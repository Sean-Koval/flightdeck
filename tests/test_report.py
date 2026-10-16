import os
from pathlib import Path
from typing import Any

import pytest
from hangar_export import CREATED, EXP, export_dir, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.report import markdown
from flightdeck.stats.compare import Comparison
from flightdeck.stats.core import Interval


def report(plane: str, **kw: Any) -> str:
    return markdown.render_report(connect(plane), EXP, **kw)


def test_report_renders_from_parquet_alone_with_a_preregistered_verdict(plane: str, export_dir: Path) -> None:
    text = report(plane, decision=export_dir / "decision.yaml")
    assert text.startswith(f"<!-- flightdeck:report:{EXP} -->\n")
    order = ["**Verdict**: treat is better than control on resolved", "### Pins", "### Outcome", "### Process",
             "**tool_calls**", "**wall_s**", "### Cost", "**cost_usd**", "### Exclusions and drift"]
    assert [text.index(s) for s in order] == sorted(text.index(s) for s in order)
    assert "claude-code 2.3.1" in text and "bash tests/test.sh" in text and "| hangar version | 0.1.0 |" in text
    assert "<details>" not in text and "t05/treat/2" not in text  # per-task details only behind --details


def test_details_put_discordant_tasks_first_with_trial_links(plane: str) -> None:
    text = report(plane, details=True, hangar="https://hangar.example")
    rows = [r for r in text.split("<details>")[1].splitlines() if r.startswith("| t")]
    zero = [i for i, r in enumerate(rows) if "| +0 pp |" in r]
    assert zero and zero == list(range(len(rows) - len(zero), len(rows)))
    assert f"https://hangar.example/api/experiments/{EXP}/trials/t03/control/1/trace" in text
    assert "- `t05/treat/2`: harness drift" in text


@pytest.mark.parametrize("when", ["missing", "late"])
def test_no_verdict_without_a_decision_written_before_the_trials(plane: str, tmp_path: Path, when: str) -> None:
    decision = tmp_path / "decision.yaml"
    if when == "late":
        decision.write_text("metric: resolved\nmargin: -0.05\n")
        os.utime(decision, (CREATED + 10_000, CREATED + 10_000))
    text = report(plane, decision=decision)
    assert "**Verdict**" not in text and "**No verdict**" in text
    assert "### Outcome" in text  # the numbers are still there


def _c(est: float, lo: float, hi: float, n: int = 20, metric: str = "resolved", note: str = "") -> Comparison:
    c = Comparison("e", metric, "A", "B", 0)
    c.diff = Interval(est, lo, hi, n_tasks=n, note=note)
    return c


@pytest.mark.parametrize(("c", "rule", "start"), [
    (_c(-0.02, -0.04, 0.01), {"margin": "-0.05"}, "B is non-inferior to A on resolved (-2.0 pp, CI -4.0…+1.0"),
    (_c(0.10, 0.02, 0.2), {}, "B is better than A"),
    (_c(-0.2, -0.3, -0.1), {"margin": "0.05"}, "B is worse than A"),
    (_c(0.0, -0.2, 0.2), {"margin": "-0.05"}, "No decision: the interval on resolved spans the margin"),
    (_c(0.3, 0.1, 0.5, n=5), {"min_tasks": "10"}, "No decision: underpowered (5 paired tasks"),
    (_c(-0.1, -0.15, -0.05, metric="cost_usd"), {"direction": "lower"}, "B is better than A on cost_usd (+0.1"),
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
    gh = FakeGitHub()
    markdown.post(head + "x" * 70_000, "o/r#1", "t", full="report.md", gh=gh)
    body = gh.comments[-1]["body"]
    assert len(body) <= markdown.LIMIT and body.rstrip().endswith("full report: report.md.*")


def test_report_cli_writes_and_posts(plane: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, str | None]] = []
    monkeypatch.setattr(markdown, "post", lambda text, target, token, full=None: posted.append((target, full)) or "u")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    out = tmp_path / "report.md"
    args = ["report", "experiment", EXP, "--data", plane, "--out", str(out), "--post", "o/r#9"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert out.read_text().startswith(markdown.marker(EXP)) and posted == [("o/r#9", str(out))]
    result = CliRunner().invoke(app, ["report", "post", str(out), "--to", "o/r#10"])
    assert result.exit_code == 0 and posted[-1] == ("o/r#10", str(out))
