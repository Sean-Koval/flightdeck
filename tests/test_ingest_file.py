"""`flightdeck ingest file` (KAN-312) and the trace attributes the flattener keeps on `runs` (KAN-309).

Every trace here is a synthetic fixture from tests/fixtures/hangar, or built in the test (ADR-0002)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hangar_export import Recorded, no_proxy  # noqa: F401  (a fixture, used through usefixtures)
from hangar_outbox import kv, write_run
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane import flatten, schema
from flightdeck.dataplane.duck import connect

FIX = Path(__file__).resolve().parent / "fixtures" / "hangar"
DIGESTS = {"hangar.harness.digest": "sha256:" + "a" * 64, "hangar.environment.digest": "sha256:" + "b" * 64}


def tables(root: Path) -> dict[str, list[str]]:
    con = connect(str(root))
    return {t: sorted(map(repr, con.sql(f"select * exclude (dt) from {t}").fetchall())) for t in schema.TABLES}


def ingest(*args: str) -> str:
    result = CliRunner().invoke(app, ["ingest", *args])
    assert result.exit_code == 0, result.output
    return result.output


def spans_of(doc: dict) -> list[dict]:
    return [s for rs in doc["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]


def kind(span: dict) -> Any:
    return next((a["value"]["stringValue"] for a in span["attributes"] if a["key"] == "hangar.kind"), None)


def job_trace(tmp_path: Path, **turn_attrs: Any) -> Path:
    """trace_job.json with hangar's digests on its turn span, a failed job (`hangar.job.reason`), cache writes and
    per-call usage on a tool span, as hangar's exporter or an offline import may add them."""
    doc = json.loads((FIX / "trace_job.json").read_text())
    for span in spans_of(doc):
        k = kind(span)
        extra = {**DIGESTS, **turn_attrs} if k == "turn" else {}
        if k == "job":
            span["attributes"] = [a for a in span["attributes"] if a["key"] != "hangar.job.state"]
            extra = {"hangar.job.state": "failed", "hangar.job.reason": "verify failed"}
        if k == "tool.call" and span["name"] == "execute_tool Edit":
            extra = {"gen_ai.usage.input_tokens": 120, "gen_ai.usage.output_tokens": 30}
        span["attributes"] = [a for a in span["attributes"] if a["key"] not in extra] + kv(extra)
    path = tmp_path / "trace_job.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.usefixtures("no_proxy")
def test_ingest_file_writes_the_rows_ingest_job_writes(tmp_path: Path) -> None:
    trace = job_trace(tmp_path, **{"gen_ai.usage.cache_write.input_tokens": 700})
    routes = {"/api/jobs/job-fixture01/trace": trace,
              "/api/jobs/job-fixture01/manifest?turn=1": FIX / "manifest_turn.json"}
    with Recorded(routes) as hangar:
        ingest("job", "job-fixture01", "--hangar", hangar.url, "--out", str(tmp_path / "rest"))
    out = ingest("file", str(trace), "--manifest", str(FIX / "manifest_turn.json"), "--out", str(tmp_path / "file"))
    assert out.startswith("job-job-fixture01: 1 runs")
    assert tables(tmp_path / "file") == tables(tmp_path / "rest")
    assert sorted(p.name for p in (tmp_path / "file").rglob("*.parquet")) == sorted(
        p.name for p in (tmp_path / "rest").rglob("*.parquet"))  # the same unit, so either replaces the other


@pytest.mark.usefixtures("no_proxy")
def test_reingesting_a_file_over_rest_rows_replaces_them_by_run_id(tmp_path: Path) -> None:
    trace, plane = job_trace(tmp_path), str(tmp_path / "plane")
    with Recorded({"/api/jobs/job-fixture01/trace": trace}) as hangar:
        ingest("job", "job-fixture01", "--hangar", hangar.url, "--out", plane)
    ingest("file", str(trace), "--out", plane)
    ingest("file", str(trace), "--out", plane)
    con = connect(plane)
    assert con.sql("select count(*), count(distinct run_id) from runs").fetchone() == (1, 1)
    assert con.sql("select count(*) = count(distinct span_id) from spans").fetchone() == (True,)


@pytest.mark.usefixtures("no_proxy")
def test_a_session_trace_without_a_manifest_matches_rest_session_ingest(tmp_path: Path) -> None:
    trace = FIX / "trace_session_good.json"
    with Recorded({"/api/sessions/dev-a-s1/trace?turn=1": trace}) as hangar:
        ingest("session", "dev-a-s1", "--turn", "1", "--hangar", hangar.url, "--out", str(tmp_path / "rest"))
    assert ingest("file", str(trace), "--out", str(tmp_path / "file")).startswith("session-ses-09a5e19b: 1 runs")
    assert tables(tmp_path / "file") == tables(tmp_path / "rest")


def test_a_manifest_that_misses_hangars_schema_warns_and_keeps_going(tmp_path: Path) -> None:
    bad = json.loads((FIX / "manifest_turn.json").read_text())
    bad["warnings"] = "none"  # an array in hangar.manifest/v1
    (tmp_path / "m.json").write_text(json.dumps(bad))
    result = CliRunner().invoke(app, ["ingest", "file", str(FIX / "trace_job.json"), "--manifest",
                                      str(tmp_path / "m.json"), "--out", str(tmp_path / "plane")])
    assert result.exit_code == 0, result.output
    assert "does not match hangar manifest.schema.json" in result.output and "1 manifests" in result.output


def offline_session(turns: int) -> dict:
    """A single-session export with no manifest, job or run ids, as an offline import of a transcript may write."""
    t0, spans = 1_762_000_000 * 10**9, []
    root = {"traceId": "c" * 32, "spanId": "0" * 16, "name": "invoke_workflow hangar.session",
            "startTimeUnixNano": str(t0), "endTimeUnixNano": str(t0 + 10**12),
            "attributes": kv({"hangar.kind": "session", "hangar.harness": "claude-code",
                              "gen_ai.usage.input_tokens": 9, "gen_ai.usage.cache_write.input_tokens": 4})}
    for n in range(1, turns + 1):
        turn = f"{n:016x}"
        spans += [{"traceId": "c" * 32, "spanId": turn, "parentSpanId": "0" * 16, "name": "invoke_agent claude-code",
                   "startTimeUnixNano": str(t0 + n * 10**11), "endTimeUnixNano": str(t0 + n * 10**11 + 10**9),
                   "attributes": kv({"hangar.kind": "turn", "hangar.turn.number": n, "hangar.harness": "claude-code"})},
                  {"traceId": "c" * 32, "spanId": f"{n:08x}" + "f" * 8, "parentSpanId": turn,
                   "name": "execute_tool Bash",
                   "startTimeUnixNano": str(t0 + n * 10**11 + 1), "endTimeUnixNano": str(t0 + n * 10**11 + 2),
                   "attributes": kv({"hangar.kind": "tool.call", "gen_ai.tool.name": "Bash", "hangar.seq": n})}]
    res = kv({"hangar.trace.schema": "hangar.trace/v1", "hangar.session.id": "ses-offline1"})
    return {"resourceSpans": [{"resource": {"attributes": res}, "scopeSpans": [{"spans": [root, *spans]}]}]}


def test_an_offline_session_export_lands_as_runs_keyed_by_hangars_turn_key(tmp_path: Path) -> None:
    (tmp_path / "t.json").write_text(json.dumps(offline_session(2)))
    assert ingest("file", str(tmp_path / "t.json"), "--out", str(tmp_path / "plane")).startswith(
        "session-ses-offline1: 2 runs")
    con = connect(str(tmp_path / "plane"))
    assert con.sql("select run_id, source, session_id, turn from runs order by turn").fetchall() == [
        ("ses-offline1/turn/1", "session", "ses-offline1", 1), ("ses-offline1/turn/2", "session", "ses-offline1", 2)]
    assert con.sql("select run_id, count(*) from spans group by 1 order by 1").fetchall() == [
        ("ses-offline1", 1), ("ses-offline1/turn/1", 2), ("ses-offline1/turn/2", 2)]


def test_a_trace_without_turns_is_one_run_from_its_root_span() -> None:
    (run,) = flatten.flatten_trace(offline_session(0))["runs"]
    assert (run["run_id"], run["source"], run["harness"]) == ("ses-offline1", "session", "claude-code")
    assert run["turn"] is None
    assert (run["input_tokens"], run["cache_write_tokens"]) == (9, 4)


# --- KAN-309 -----------------------------------------------------------------------------------------------------


def test_a_job_trace_fills_digests_job_state_and_cache_write_tokens(tmp_path: Path) -> None:
    trace = job_trace(tmp_path, **{"gen_ai.usage.cache_write.input_tokens": 700})
    rows = flatten.flatten_trace(json.loads(trace.read_text()))
    (run,) = rows["runs"]
    assert (run["harness_digest"], run["environment_digest"]) == tuple(DIGESTS.values())
    assert (run["job_state"], run["job_reason"], run["cache_write_tokens"]) == ("failed", "verify failed", 700)
    edit = next(s for s in rows["spans"] if s["name"] == "execute_tool Edit")  # per-call usage stays for later
    assert json.loads(edit["attrs"])["gen_ai.usage.input_tokens"] == 120
    assert schema.to_table("runs", rows["runs"]).column("cache_write_tokens").to_pylist() == [700]


def test_the_outbox_wins_over_the_trace_where_both_have_a_value(tmp_path: Path) -> None:
    src, out = tmp_path / "outbox", tmp_path / "plane"
    d = write_run(src, "2026-11-03", "ses-1", "run-00000001", job="job-7", harness_digest="sha256:outbox",
                  job_reason=None, usage={"input_tokens": 10, "output_tokens": 5, "cache_write_tokens": 33})
    doc = json.loads((d / "trace.otlp.json").read_text())
    turn = next(s for s in spans_of(doc) if kind(s) == "turn")
    turn["attributes"] += kv({"hangar.harness.digest": "sha256:trace", "hangar.environment.digest": "sha256:env",
                              "gen_ai.usage.cache_write.input_tokens": 99})
    (d / "trace.otlp.json").write_text(json.dumps(doc))
    CliRunner().invoke(app, ["compact", "--date", "2026-11-03", "--lookback", "0", "--input", str(src), "--out",
                             str(out)], catch_exceptions=False)
    con = connect(str(out))
    rows = con.sql("select harness_digest, environment_digest, cache_write_tokens, job_state from runs").fetchall()
    assert rows == [("sha256:outbox", "sha256:env", 33, "delivering")]


@pytest.mark.parametrize("name", ["trace_session_good.json", "trace_semver.json"])
def test_older_traces_without_the_new_attributes_leave_them_null(name: str) -> None:
    for run in flatten.flatten_trace(json.loads((FIX / name).read_text()))["runs"]:
        assert run["harness_digest"] is None and run["cache_write_tokens"] in (None, 0)
