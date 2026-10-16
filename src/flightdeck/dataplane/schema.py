"""`flightdeck.parquet/v1`: the tables flightdeck reads hangar's runs from.

Wide, denormalized rows partitioned by `dt=YYYY-MM-DD/`. Additive within v1, like hangar's interfaces: a new optional
column is not a new version; removing or renaming one is. Columns hangar doesn't emit yet (`harness_digest`,
`environment_digest`, `knowledge_snapshot`, `grader_digest`, an `infra_error` outcome) are nullable and fill in as
soon as hangar emits them. Every row carries `run_id`, `source` and `dt`.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

VERSION = "flightdeck.parquet/v1"
SOURCES = ("job", "session", "experiment", "shadow")

TYPES = {"str": pa.string(), "int": pa.int64(), "float": pa.float64(), "bool": pa.bool_(),
         "ts": pa.timestamp("ms", tz="UTC"), "strs": pa.list_(pa.string())}


def _schema(name: str, cols: str) -> pa.Schema:
    """A table from `name[:type]` words (type defaults to str), after the common `run_id source dt`."""
    fields = [w.partition(":") for w in f"run_id source dt {cols}".split()]
    return pa.schema([pa.field(n, TYPES[t or "str"]) for n, _, t in fields],
                     metadata={"flightdeck.schema": VERSION, "flightdeck.table": name})


# One hangar run (a turn) or one experiment trial.
RUNS = _schema("runs", """
    job_id session_id turn:int experiment_id trial_key task_id variant trial:int person repo environment harness
    harness_version model_id outcome reason config_digest harness_digest environment_digest manifest_digest base_sha
    cost_usd:float cost_source input_tokens:int output_tokens:int cache_read_tokens:int started_at:ts finished_at:ts
    verify_passed:bool pr_url pr_number:int merged:bool merged_by diff_files:strs drift:strs truncated:bool""")

# One OTLP span. `attrs`: JSON of every attribute without its own column.
SPANS = _schema("spans", """
    trace_id span_id parent_span_id job_id session_id environment person kind name start_ns:int end_ns:int seq:int
    seq_end:int status_code:int tool_kind tool_name tool_input tool_output tool_ok:bool shell_ops:strs
    file_repo_path mcp_server mcp_tool skill_name approval_status approval_by attrs""")

# One span event other than test results.
EVENTS = _schema("events", """
    trace_id span_id span_kind name time_ns:int seq:int file_repo_path file_op text attrs""")

# One hangar.manifest/v1, deduplicated by digest. `json`: the whole manifest.
MANIFESTS = _schema("manifests", """
    digest config_digest captured_at:ts subject_kind session_id turn:int job_id person harness_name harness_version
    harness_locked harness_mode harness_digest model_id model_policy model_provider skills_effective:strs
    mcp_servers:strs hooks:strs approvals egress_mode environment_name environment_spec_digest environment_digest
    knowledge_snapshot repo_url base_sha json""")

# One grader result for a trial. `data`: JSON the grader wrote to $HANGAR_GRADE_OUT.
GRADES = _schema("grades", """
    experiment_id trial_key command exit_code:int applied:bool seconds:float error data grader_digest""")

# One test.run (case_name null) or one test.case event.
TEST_CASES = _schema("test_cases", """
    trace_id test_run_id suite status run_kind trusted:bool exit_code:int total:int passed:int failed:int errors:int
    skipped:int complete:bool flaky:int time_ns:int case_name case_status case_outcome sha""")

TABLES: dict[str, pa.Schema] = {"runs": RUNS, "spans": SPANS, "events": EVENTS, "manifests": MANIFESTS,
                                "grades": GRADES, "test_cases": TEST_CASES}


def to_table(name: str, rows: list[dict]) -> pa.Table:
    """Rows as a table of the named schema: missing columns are null, unknown keys are an error."""
    schema = TABLES[name]
    extra = {k for r in rows for k in r} - set(schema.names)
    if extra:
        raise ValueError(f"{name}: columns not in {VERSION}: {sorted(extra)}")
    return pa.Table.from_pylist(rows, schema=schema)


def write_partitioned(name: str, rows: list[dict], root: str) -> list[str]:
    """Write rows under `<root>/<name>/dt=YYYY-MM-DD/part-0.parquet` (zstd), one file per day; `dt` lives in the path
    (hive partitioning), not in the file. Returns the paths."""
    paths = []
    for day in sorted({r.get("dt") or "unknown" for r in rows}):
        part = Path(root) / name / f"dt={day}"
        part.mkdir(parents=True, exist_ok=True)
        path = part / "part-0.parquet"
        table = to_table(name, [r for r in rows if (r.get("dt") or "unknown") == day])
        pq.write_table(table.drop_columns(["dt"]), path, compression="zstd")
        paths.append(str(path))
    return paths
