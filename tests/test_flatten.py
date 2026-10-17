import json
from pathlib import Path

import jsonschema
import pyarrow.parquet as pq
import pytest

from flightdeck.dataplane import flatten, schema
from flightdeck.dataplane.ingest import _vendored as SCHEMAS

FIX = Path(__file__).resolve().parent / "fixtures" / "hangar"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _tests_before_commit(spans: list[dict]) -> bool:
    """hangar tests/test_interfaces.py::_behavior's first predicate, from `spans` rows ordered by (seq, start)."""
    calls = sorted(
        (s for s in spans if s["kind"] == "tool.call" and s.get("seq") is not None),
        key=lambda s: (s["seq"], s["start_ns"]),
    )
    first = {
        op: next((s["seq"] for s in calls if op in (s.get("shell_ops") or [])), None) for op in ("test", "git.commit")
    }
    test, commit = first["test"], first["git.commit"]
    return test is not None and commit is not None and test < commit


def edits_in_src(events: list[dict]) -> bool:
    return all((e.get("file_repo_path") or "").startswith("src/") for e in events if e["name"] == "file.change")


@pytest.mark.parametrize(("name", "good"), [("trace_session_good.json", True), ("trace_session_bad.json", False)])
def test_session_trace_rows_reproduce_hangars_predicates(name: str, good: bool) -> None:
    rows = flatten.flatten_trace(load(name))
    assert len(rows["runs"]) == 1 and rows["runs"][0]["outcome"] == "exited"
    assert _tests_before_commit(rows["spans"]) is good
    assert edits_in_src(rows["events"]) is good
    kinds = {s["kind"] for s in rows["spans"]}
    assert {"turn", "tool.call"} <= kinds
    assert all(s["run_id"] == rows["runs"][0]["run_id"] for s in rows["spans"])


def test_good_session_keeps_tool_columns_and_approvals() -> None:
    rows = flatten.flatten_trace(load("trace_session_good.json"))
    shell = [s for s in rows["spans"] if s.get("tool_kind") == "shell"]
    assert any("delete" in s["shell_ops"] for s in shell)
    approval = next(s for s in rows["spans"] if s.get("kind") == "approval")
    assert approval["approval_status"] == "allowed" and approval["approval_by"] == "alice"
    assert all(s["source"] == "session" and s["dt"] == "2025-10-15" for s in rows["spans"])


def test_job_trace_runs_and_test_cases() -> None:
    rows = flatten.flatten_trace(load("trace_job.json"))
    (run,) = rows["runs"]
    assert run["source"] == "job" and run["job_id"] == "job-fixture01" and run["run_id"] == "run-j1"
    assert run["outcome_class"] == "agent" and run["infra_reason"] is None  # hangar#166's turn attributes
    assert run["verify_passed"] is True and run["pr_number"] == 7 and run["merged"] is True
    assert run["merged_by"] == "reviewer-b" and run["diff_files"] == ["src/reaper.py", "tests/test_reaper.py"]
    assert run["cost_usd"] == pytest.approx(0.42) and run["truncated"] is False
    runs = [r for r in rows["test_cases"] if r["case_name"] is None]
    trusted = {r["test_run_id"]: (r["trusted"], r["total"]) for r in runs}
    assert trusted == {"tr-agent1": (False, 0), "tr-verify1": (True, 42)}
    assert any(r["case_name"] == "tests/test_reaper.py::test_slow" for r in rows["test_cases"])
    # job-level spans and events belong to the job, not a turn
    root = next(s for s in rows["spans"] if s["kind"] == "job")
    assert root["run_id"] == "job-fixture01"


def test_untrusted_collect_only_does_not_count_as_testing() -> None:
    """The agent's `pytest --collect-only` is a shell `test` op (a hint); only trusted test.run rows prove testing."""
    rows = flatten.flatten_trace(load("trace_job.json"))
    assert _tests_before_commit(rows["spans"])  # the naive predicate is fooled
    proof = [r for r in rows["test_cases"] if r["case_name"] is None and r["trusted"] and (r["total"] or 0) > 0]
    assert [r["run_kind"] for r in proof] == ["verify"]


def test_unknown_attributes_land_in_attrs_and_truncation_is_flagged() -> None:
    otlp = load("trace_session_good.json")
    res = otlp["resourceSpans"][0]
    res["resource"]["attributes"].append({"key": "hangar.export.truncated", "value": {"boolValue": True}})
    span = res["scopeSpans"][0]["spans"][0]
    span["attributes"].append({"key": "hangar.future.field", "value": {"intValue": "7"}})
    rows = flatten.flatten_trace(otlp)
    assert rows["runs"][0]["truncated"] is True
    assert json.loads(rows["spans"][0]["attrs"])["hangar.future.field"] == 7


def test_secrets_are_masked() -> None:
    otlp = load("trace_session_good.json")
    span = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"][1]
    span["attributes"].append({"key": "hangar.tool.output", "value": {"stringValue": "ghp_" + "x" * 36}})
    rows = flatten.flatten_trace(otlp)
    assert rows["spans"][1]["tool_output"] == "***"


def test_rejects_other_schemas() -> None:
    with pytest.raises(ValueError):
        flatten.flatten_manifest({"schema": "hangar.manifest/v2"})
    with pytest.raises(ValueError):
        flatten.flatten_experiment({"schema": "nope"})


def test_manifest_row() -> None:
    m = load("manifest_turn.json")
    jsonschema.Draft202012Validator(SCHEMAS("manifest.schema.json")).validate(m)
    row = flatten.flatten_manifest(m)
    assert row["digest"] == m["digest"] and row["run_id"] == "run-j1" and row["harness_name"] == "claude-code"
    assert row["skills_effective"] == ["review@sha256:" + "7" * 64] and row["mcp_servers"] == ["github"]
    assert row["egress_mode"] == "allowlist" and row["harness_digest"] is None and row["dt"] == "2025-10-16"


def test_experiment_rows() -> None:
    index = load("experiment_index.json")
    jsonschema.Draft202012Validator(SCHEMAS("experiment.schema.json")).validate(index)
    rows = flatten.flatten_experiment(index)
    assert len(rows["runs"]) == 7 and len(rows["grades"]) == 6
    r = next(x for x in rows["runs"] if x["trial_key"] == "retry/treat/1")
    assert r["run_id"] == "job-exp01/retry/treat/1" and r["variant"] == "treat" and r["drift"]
    assert r["base_sha"] == "a" * 40 and r["cost_usd"] == pytest.approx(0.4)
    g = next(x for x in rows["grades"] if x["trial_key"] == "semver/control/2")
    assert g["exit_code"] == 1 and g["applied"] is True and json.loads(g["data"]) == {"reward": 0}


def test_all_six_tables_round_trip_through_parquet(tmp_path: Path) -> None:
    tables: dict[str, list[dict]] = {name: [] for name in schema.TABLES}
    for name in ("trace_session_good.json", "trace_session_bad.json", "trace_job.json"):
        for table, rows in flatten.flatten_trace(load(name)).items():
            tables[table] += rows
    for table, rows in flatten.flatten_experiment(load("experiment_index.json")).items():
        tables[table] += rows
    tables["manifests"].append(flatten.flatten_manifest(load("manifest_turn.json")))
    for table, rows in tables.items():
        assert rows, table
        paths = schema.write_partitioned(table, rows, str(tmp_path))
        back = pq.ParquetDataset(tmp_path / table, partitioning="hive").read()
        assert back.num_rows == len(rows) and all("dt=" in p for p in paths)
        assert back.schema.metadata and back.schema.metadata[b"flightdeck.schema"] == b"flightdeck.parquet/v1"


def test_to_table_rejects_unknown_columns() -> None:
    with pytest.raises(ValueError, match="not in flightdeck.parquet/v1"):
        schema.to_table("runs", [{"run_id": "r", "bogus": 1}])


def test_query_over_a_local_data_plane(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from flightdeck.cli import app

    rows = flatten.flatten_experiment(load("experiment_index.json"))
    for table, trows in rows.items():
        schema.write_partitioned(table, trows, str(tmp_path))
    schema.write_partitioned("spans", flatten.flatten_trace(load("trace_job.json"))["spans"], str(tmp_path))
    sql = "select count(*) as n, count(distinct dt) as days from runs"
    result = CliRunner().invoke(app, ["query", sql, "--data", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["n\tdays", "7\t1"]
    joined = "select r.variant, count(*) from runs r join grades g using (run_id) group by 1 order by 1"
    out = CliRunner().invoke(app, ["query", joined, "--data", str(tmp_path)]).output.splitlines()
    assert out[1:] == ["control\t3", "treat\t3"]
