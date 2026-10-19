"""The nightly runner: ADR checks, spec_results, change-point alerts and check-edit labels."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
from spec_traces import example, trace
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.dataplane.schema import write_partitioned
from flightdeck.specs import checks, lang

ROOT = Path(__file__).resolve().parent.parent
ADRS = ROOT / "tests" / "fixtures" / "adrs"


def test_parse_adr_both_styles() -> None:
    status, cs = checks.parse_adr((ADRS / "0007-landing-stays-in-hangar.md").read_text())
    assert status == "accepted" and [c["id"] for c in cs] == ["landing-stays-in-hangar", "no-merge-outside-landing"]
    status, cs = checks.parse_adr((ADRS / "0008-push-policy.md").read_text())
    assert status == "accepted" and [c["id"] for c in cs] == ["never-push-main"]
    assert checks.parse_adr((ROOT / "docs/decisions/0000-template.md").read_text())[0] == "proposed"


def test_only_accepted_adrs_run_and_git_reads_committed_head(tmp_path: Path) -> None:
    specs = checks.adr_specs(str(ADRS))
    assert [(s["spec_source"], s["id"]) for s in specs] == [
        ("adr:adrs/0007-landing-stays-in-hangar", "landing-stays-in-hangar"),
        ("adr:adrs/0007-landing-stays-in-hangar", "no-merge-outside-landing"),
        ("adr:adrs/0008-push-policy", "never-push-main")]
    repo = tmp_path / "team"
    shutil.copytree(ADRS, repo / "docs" / "decisions")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "adrs")
    (repo / "docs/decisions/0008-push-policy.md").unlink()  # uncommitted: the committed ADR still runs
    got = checks.adr_specs(f"{repo}:docs/decisions")
    assert [s["spec_source"] for s in got][-1] == "adr:team/0008-push-policy"


def _plane(tmp_path: Path) -> tuple[Path, str]:
    merged = trace([("tool", "edit", "src/a.py", []), ("event", "pr.merge", {"hangar.pr.merged_by": "dev-a"})],
                   job="job-merge", session="ses-merge", runs="rm")
    tables: dict[str, list[dict]] = {}
    for otlp in (example("job_pass"), example("job_fail"), merged):
        for name, rows in flatten_trace(otlp).items():
            tables.setdefault(name, []).extend(rows)
    for name, rows in tables.items():
        write_partitioned(name, rows, str(tmp_path / "plane"))
    return tmp_path / "plane", tables["runs"][0]["dt"]


def test_check_run_writes_spec_results(tmp_path: Path) -> None:
    plane, day = _plane(tmp_path)
    out = CliRunner().invoke(app, ["check", "run", "--data", str(plane), "--date", day, "--adrs", str(ADRS),
                                   "--specs", str(ROOT / "specs/examples/team-default.yaml")])
    assert out.exit_code == 0, out.output
    rows = pq.ParquetDataset(plane / "spec_results", partitioning="hive").read().to_pylist()
    got = {(r["spec_source"], r["spec_id"], r["run_id"]): r["result"] for r in rows}
    assert got[("adr:adrs/0007-landing-stays-in-hangar", "landing-stays-in-hangar", "job-merge")] == "fail"
    assert got[("adr:adrs/0007-landing-stays-in-hangar", "landing-stays-in-hangar", "job-job_pass")] == "pass"
    assert got[("adr:adrs/0007-landing-stays-in-hangar", "no-merge-outside-landing", "rm-1")] == "unknown"
    assert got[("adr:adrs/0008-push-policy", "never-push-main", "run-1")] == "fail"
    assert got[("spec", "tests-before-commit", "job-job_fail")] == "fail"
    assert {r["source"] for r in rows} == {"job"} and all(r["repo"] for r in rows)
    assert re.search(r"^SPEC +APPLIED +PASSED +FAILED +UNKNOWN$", out.output, re.M)
    assert re.search(r"^landing-stays-in-hangar \(adr:.*\) +3 +2 +1 +0 +e\.g\. job-merge$", out.output, re.M)
    assert re.search(r"^never-push-main \(adr:.*\) +[—] +— +— +0 +not applied$", out.output, re.M) is None  # it applied
    assert re.search(r"^\d+ specs over \d+ units: \d+ failed, \d+ unknown$", out.output, re.M)
    assert "not-yet" not in out.output  # proposed ADR
    again = CliRunner().invoke(app, ["check", "run", "--data", str(plane), "--date", day, "--adrs", str(ADRS)])
    assert again.exit_code == 0 and "ALERT" not in again.output  # rerun replaces the day's partition


def _day(d: int, n: int, k: int, digest: str) -> list[dict]:
    return [{"spec_source": "adr:team/0007", "spec_id": "landing", "repo": "r", "dt": f"2026-10-0{d}",
             "run_id": f"job-{d}-{i}", "result": "fail" if i < k else "pass", "harness_digest": digest,
             "knowledge_snapshot": "ks-1"} for i in range(n)]


def test_step_change_raises_one_alert_naming_the_digest() -> None:
    rows = [r for d in range(1, 8) for r in _day(d, 40, 2 if d < 5 else 20, "sha256:aaa" if d < 5 else "sha256:bbb")]
    (a,) = checks.alerts(rows)
    assert a["day"] == "2026-10-05" and a["changed"] == ["harness_digest=sha256:bbb"]
    assert a["before"] == 0.05 and a["after"] == 0.5 and a["examples"][0] == "job-5-0"
    flat = [r for d in range(1, 8) for r in _day(d, 40, 2, "sha256:aaa")]
    assert checks.alerts(flat) == []
    better = [r for d in range(1, 8) for r in _day(d, 40, 20 if d < 5 else 2, "sha256:aaa")]
    assert checks.alerts(better) == []  # fewer violations is no alert


def test_file_alerts_opens_then_updates_one_issue() -> None:
    calls: list[list[str]] = []
    issues: list[dict] = []

    def gh(argv: list[str], **_: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(issues) if "state=open" in argv[2] else "{}")

    rows = [r for d in range(1, 8) for r in _day(d, 40, 2 if d < 5 else 20, "sha256:aaa" if d < 5 else "sha256:bbb")]
    found = checks.alerts(rows)
    checks.file_alerts(found, "team/flightdeck-data", gh=gh)
    assert calls[-1][2] == "repos/team/flightdeck-data/issues" and "labels[]=flightdeck:violation" in calls[-1]
    assert any("sha256:bbb" in x for x in calls[-1])
    issues.append({"number": 3, "title": calls[-1][4].removeprefix("title=")})
    checks.file_alerts(found, "team/flightdeck-data", gh=gh)
    assert calls[-1][2] == "repos/team/flightdeck-data/issues/3/comments"


def test_check_diff_labels(tmp_path: Path) -> None:
    base = (ADRS / "0008-push-policy.md").read_text()
    old = tmp_path / "old.md"
    old.write_text(base)
    cases = {
        "removed": base.replace("  - id: never-push-main", "  - id: renamed"),
        "loosened": base.replace("(main|master)", "(main)"),
        "loosened ": base.replace("scope: turn", "scope: turn\n    allow_untrusted: true"),
        "unchanged": base,
    }
    for want, text in cases.items():
        (tmp_path / "new.md").write_text(text)
        res = checks.diff(checks.load_checks(old), checks.load_checks(tmp_path / "new.md"))
        assert max(res.values(), key=checks.LABELS.index) == want.strip(), (want, res)
    assert checks.diff([], checks.load_checks(old)) == {"never-push-main": "tightened"}
    out = CliRunner().invoke(app, ["check", "diff", str(old), str(tmp_path / "gone.md")])
    assert out.exit_code == 0 and out.output.strip().endswith("label: checks:removed")
    spec = lang.load((ROOT / "specs/examples/team-default.yaml").read_text())
    assert set(checks.diff(spec, spec[1:]).values()) == {"removed", "unchanged"}


def test_check_run_alerts_from_history(tmp_path: Path) -> None:
    rows = [r for d in range(1, 8) for r in _day(d, 40, 2 if d < 5 else 20, "sha256:aaa" if d < 5 else "sha256:bbb")]
    write_partitioned("spec_results", [{**r, "source": "job", "scope": "job"} for r in rows], str(tmp_path))
    out = CliRunner().invoke(app, ["check", "run", "--data", str(tmp_path), "--date", "2026-10-08"])
    assert out.exit_code == 0, out.output
    assert out.output.count("ALERT") == 1 and "2026-10-05\t5% -> 50%\tchanged: harness_digest=sha256:bbb" in out.output
