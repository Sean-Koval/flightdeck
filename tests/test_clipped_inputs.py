"""KAN-274: hangar marks a tool input it clipped (`hangar.tool.input_clipped`, a 200-character preview), and flightdeck
carries it into `spans.tool_input_clipped`, counts the calls in `process_metrics.clipped_calls` and says in the report
how many trials have one, since step labels and specs that read a command's text are lower bounds on those."""

from __future__ import annotations

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from hangar_export import EXP, export_dir, plane  # noqa: F401  (pytest fixtures)
from test_process_metrics import build, rows
from test_process_metrics import plane as write_plane

from flightdeck.dataplane.duck import connect
from flightdeck.report import markdown

STEPS = [("bash", "ls", "", True), ("bash", "python - <<'EOF'\n" + "x" * 600, "", True),
         ("bash", "pytest -q", "1 passed", True), ("bash", "cat <<'EOF' > a.py\n" + "y" * 600, "", True)]


def _clip(otlp: dict, calls: set[int]) -> dict:
    """Mark the tool calls at these positions (0-based, in step order) as clipped, as hangar does."""
    tools = [s for s in otlp["resourceSpans"][0]["scopeSpans"][0]["spans"] if s.get("parentSpanId")]
    for n in calls:
        tools[n]["attributes"].append({"key": "hangar.tool.input_clipped", "value": {"boolValue": True}})
    return otlp


def test_clipped_calls_are_carried_and_counted(tmp_path: Path) -> None:
    con = connect(str(write_plane(tmp_path, _clip(build(STEPS), {1, 3}))))
    got = rows(con, "select tool_input_clipped, attrs from spans where kind = 'tool.call' order by seq")
    assert [r["tool_input_clipped"] for r in got] == [None, True, None, True]
    assert all("input_clipped" not in (r["attrs"] or "") for r in got)  # its own column, not left in attrs
    assert rows(con, "select tool_calls, clipped_calls from process_metrics") == [{"tool_calls": 4, "clipped_calls": 2}]


def test_a_trace_without_the_attribute_counts_no_clipped_calls(tmp_path: Path) -> None:
    con = connect(str(write_plane(tmp_path, build(STEPS))))
    assert rows(con, "select clipped_calls from process_metrics") == [{"clipped_calls": 0}]


def test_a_plane_written_before_the_column_still_opens(tmp_path: Path) -> None:
    """Additive within v1: a spans file without `tool_input_clipped` reads it as null, and process_metrics runs."""
    write_plane(tmp_path, build(STEPS))
    for f in (tmp_path / "spans").glob("dt=*/*.parquet"):
        pq.write_table(pq.read_table(f).drop_columns(["tool_input_clipped"]), f)
    assert "tool_input_clipped" not in pq.read_schema(next((tmp_path / "spans").glob("dt=*/*.parquet"))).names
    con = connect(str(tmp_path))
    assert rows(con, "select count(*) as n, count(tool_input_clipped) as c from spans") == [{"n": 5, "c": 0}]
    assert rows(con, "select tool_calls, clipped_calls from process_metrics") == [{"tool_calls": 4, "clipped_calls": 0}]
    assert rows(con, "select distinct typeof(dt) as t from spans") == [{"t": "DATE"}]  # `dt` is still the path's


def test_the_report_says_how_many_trials_have_clipped_inputs(plane: str, tmp_path: Path) -> None:  # noqa: F811
    assert "clipped tool input" not in markdown.render_report(connect(plane), EXP)
    copy = tmp_path / "plane"
    shutil.copytree(plane, copy)
    run = connect(plane).execute("select min(run_id) from runs where experiment_id = ? and variant = 'candidate'",
                                 [EXP]).fetchone()
    for f in (copy / "spans").glob("dt=*/*.parquet"):
        t = pq.read_table(f)
        hit = [r == run[0] and k == "tool.call" or None for r, k in zip(t["run_id"].to_pylist(), t["kind"].to_pylist(),
                                                                         strict=True)] if run else []
        i = t.schema.get_field_index("tool_input_clipped")
        pq.write_table(t.set_column(i, "tool_input_clipped", pa.array(hit or [None] * len(t), pa.bool_())), f)
    text = markdown.render_report(connect(str(copy)), EXP)
    assert "Trials with a clipped tool input: 1 (labels and specs that read input are lower bounds)." in text
