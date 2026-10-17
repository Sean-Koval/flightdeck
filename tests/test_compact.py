"""The compactor (#5): a synthetic outbox tree in, all six tables out, idempotent, late runs and deletions handled."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import fsspec
import jsonschema
from hangar_outbox import run_doc, write_event, write_run
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import compact, schema
from flightdeck.dataplane.duck import connect

DAY, NEXT = "2026-11-03", "2026-11-04"
SRC = Path(__file__).resolve().parent.parent / "src" / "flightdeck" / "dataplane"


def outbox(root: Path) -> Path:
    write_run(root, DAY, "ses-1", "run-00000001", job="job-7", grade=True, steers={"n": 1, "by_class": {}})
    write_run(root, DAY, "ses-2", "run-00000002", job="job-8", untrusted=True)
    write_run(root, DAY, "ses-3", "run-00000003", complete=False)  # still arriving
    write_event(root, DAY, "job-7", "pr.merge", by="bob", green_to_merge_seconds=3600)
    return root


def files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def compact_cli(*args: str) -> str:
    result = CliRunner().invoke(app, ["compact", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_synthetic_run_json_matches_hangars_schema() -> None:
    doc = json.loads((SRC / "hangar_schemas" / "run.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(run_doc("ses-1", "run-00000001", DAY, job="job-7"), doc)


def test_compact_fills_all_six_tables_and_a_rerun_is_byte_identical(tmp_path: Path) -> None:
    src, out = outbox(tmp_path / "outbox"), tmp_path / "plane"
    compact_cli("--date", DAY, "--lookback", "0", "--input", f"file://{src}", "--out", str(out))
    con = connect(str(out))
    for t in schema.TABLES:
        assert con.sql(f"select count(*) from {t}").fetchone()[0] > 0, t  # type: ignore[index]
    runs = con.sql("select run_id, job_id, source, cost_usd, untrusted, steers, dt::varchar from runs order by 1")
    assert runs.fetchall() == [("run-00000001", "job-7", "job", 1.5, False, 1, DAY),
                               ("run-00000002", "job-8", "job", 1.5, True, 0, DAY)]
    assert con.sql("select count(distinct run_id) from spans").fetchone() == (2,)
    assert con.sql("select tool_output from spans where tool_name = 'Bash' limit 1").fetchone() == ("token ***",)
    assert con.sql("select kind, green_to_merge_seconds from job_events").fetchall() == [("pr.merge", 3600.0)]
    assert con.sql("select count(*), any_value(trusted) from test_cases").fetchone() == (2, True)
    record = json.loads((out / "_compactor" / f"{DAY}.json").read_text())
    assert all(o["sha256"] for k, o in record["objects"].items() if k.endswith(".json"))
    assert not any("run-00000003" in k for k in record["objects"])

    before = files(out)
    assert "unchanged" in compact_cli("--date", DAY, "--lookback", "0", "--input", str(src), "--out", str(out))
    compact_cli("--date", DAY, "--lookback", "0", "--rebuild", "--input", str(src), "--out", str(out))
    assert files(out) == before
    assert not list(out.rglob("*.tmp"))


def test_incomplete_run_is_picked_up_the_next_night_by_lookback(tmp_path: Path) -> None:
    src, out = outbox(tmp_path / "outbox"), str(tmp_path / "plane")
    compact.compact_date(str(src), out, DAY)
    write_run(src, DAY, "ses-3", "run-00000003", job="job-9")  # run.json lands after the night's compaction
    output = compact_cli("--date", NEXT, "--input", str(src), "--out", out)  # lookback 3 covers DAY
    assert f"{DAY}: " in output and "3 runs" in output
    assert connect(out).sql("select count(*) from runs").fetchone() == (3,)


def test_deleted_run_disappears_after_rebuild(tmp_path: Path) -> None:
    src, out = outbox(tmp_path / "outbox"), str(tmp_path / "plane")
    compact.compact_date(str(src), out, DAY)
    for p in sorted((src / "v1" / "runs" / DAY / "ses-2.run-00000002").iterdir()):
        p.unlink()
    (src / "v1" / "_deletions").mkdir()
    (src / "v1" / "_deletions" / "req-1.json").write_text(json.dumps({"runs": ["run-00000001"]}))
    compact_cli("--date", DAY, "--lookback", "0", "--rebuild", "--input", str(src), "--out", out)
    con = connect(out)
    assert con.sql("select count(*) from runs").fetchone() == (0,)
    assert con.sql("select count(*) from spans").fetchone() == (0,)


def test_compacts_through_fsspec_memory_filesystem(tmp_path: Path) -> None:
    src = outbox(tmp_path / "outbox")
    mem = fsspec.filesystem("memory")
    for p in src.rglob("*"):
        if p.is_file():
            mem.pipe_file(f"/box/{p.relative_to(src)}", p.read_bytes())
    counts = compact.compact_date("memory://box", "memory://plane", DAY)
    assert counts and counts["runs"] == 2 and counts["job_events"] == 1
    assert mem.exists(f"/plane/runs/dt={DAY}/part-0.parquet") and not mem.glob("/plane/**/*.tmp")


def test_compactor_needs_no_hangar_endpoint() -> None:
    tree = ast.parse((SRC / "compact.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    http = {"urllib.request", "http.client", "requests", "httpx", "aiohttp", "flightdeck.dataplane.ingest",
            "flightdeck.runners.hangar"}
    assert not names & http, names & http
    assert "HANGAR_URL" not in (SRC / "compact.py").read_text(encoding="utf-8")
