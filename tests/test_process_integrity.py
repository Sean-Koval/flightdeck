"""Synthetic trace-to-label integration checks; not a reward or training evaluator."""

import copy
from pathlib import Path

from test_process_metrics import _attrs, build, plane, rows

from flightdeck.dataplane.duck import connect
from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.dataplane.schema import write_partitioned


def test_local_data_plane_initializes_utc_after_loading_builtin_extensions(tmp_path: Path) -> None:
    with connect(str(tmp_path)) as con:
        assert con.execute("select current_setting('TimeZone')").fetchone() == ("UTC",)
        assert con.execute("select count(*) from process_metrics").fetchone() == (0,)


def test_unknown_test_result_does_not_complete_a_repair(tmp_path: Path) -> None:
    trace = build([
        ("bash", "pytest", "FAILED", False),
        ("edit", "module.py", "ok", True),
        ("bash", "pytest", "", None),
    ])
    with connect(str(plane(tmp_path, trace))) as con:
        (got,) = rows(con, "from process_metrics")
        assert (got["test_runs"], got["failing_test_runs"], got["fix_loops"]) == (2, 1, 0)


def test_unknown_test_does_not_hide_later_known_repair(tmp_path: Path) -> None:
    trace = build([
        ("bash", "pytest", "FAILED", False),
        ("edit", "module.py", "ok", True),
        ("bash", "pytest", "", None),
        ("bash", "pytest", "OK", True),
    ])
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select fix_loops from process_metrics").fetchone() == (1,)


def test_exact_duplicate_spans_do_not_inflate_labels_or_metrics(tmp_path: Path) -> None:
    trace = build()
    spans = trace["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans.append(copy.deepcopy(spans[-1]))
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select count(*) from step_labels").fetchone() == (17,)
        assert con.execute("select tool_calls, fix_loops from process_metrics").fetchone() == (17, 2)
        assert con.execute("select count(*) from spans where kind = 'tool.call'").fetchone() == (18,)


def test_exact_duplicate_export_does_not_inflate_trusted_outcomes(tmp_path: Path) -> None:
    trace = build()
    trace["resourceSpans"].append(copy.deepcopy(trace["resourceSpans"][0]))
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select tool_calls, trusted_test_runs from process_metrics").fetchall() == [(17, 1)]


def test_conflicting_span_identity_is_not_a_process_measurement(tmp_path: Path) -> None:
    trace = build()
    spans = trace["resourceSpans"][0]["scopeSpans"][0]["spans"]
    conflict = copy.deepcopy(spans[-1])
    conflict["attributes"] = [a for a in conflict["attributes"] if a["key"] != "hangar.tool.ok"] + _attrs({
        "hangar.tool.ok": False,
    })
    spans.append(conflict)
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select count(*) from process_metrics").fetchone() == (0,)
        assert con.execute("select count(*) from spans where kind = 'tool.call'").fetchone() == (18,)


def test_repair_evidence_cannot_cross_runs(tmp_path: Path) -> None:
    first = build([("bash", "pytest", "FAILED", False)], run="run-first")
    second = build([("edit", "module.py", "ok", True), ("bash", "pytest", "OK", True)], run="run-second")
    first["resourceSpans"] += second["resourceSpans"]
    with connect(str(plane(tmp_path, first))) as con:
        assert con.execute("select run_id, fix_loops from process_metrics order by run_id").fetchall() == [
            ("run-first", 0), ("run-second", 0),
        ]


def test_repair_evidence_cannot_cross_sources(tmp_path: Path) -> None:
    traces = [
        ("session", build([("bash", "pytest", "FAILED", False)])),
        ("job", build([("edit", "module.py", "ok", True), ("bash", "pytest", "OK", True)])),
    ]
    combined: dict[str, list[dict]] = {}
    for source, trace in traces:
        for name, values in flatten_trace(trace, source=source).items():
            combined.setdefault(name, []).extend(values)
    for name, values in combined.items():
        write_partitioned(name, values, str(tmp_path))
    with connect(str(tmp_path)) as con:
        assert con.execute("select source, fix_loops from process_metrics order by source").fetchall() == [
            ("job", 0), ("session", 0),
        ]


def test_labelled_tests_do_not_become_trusted_outcomes(tmp_path: Path) -> None:
    trace = build([("bash", "pytest", "OK", True)])
    trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"] = []
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select label from step_labels").fetchone() == ("test",)
        assert con.execute("select test_runs, trusted_test_runs from process_metrics").fetchone() == (1, 0)


def test_conflict_does_not_discard_another_run(tmp_path: Path) -> None:
    trace = build(run="run-conflict")
    conflict = copy.deepcopy(trace["resourceSpans"][0]["scopeSpans"][0]["spans"][-1])
    conflict["name"] = "conflicting name"
    trace["resourceSpans"][0]["scopeSpans"][0]["spans"].append(conflict)
    trace["resourceSpans"] += build(run="run-clean")["resourceSpans"]
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select run_id, tool_calls from process_metrics").fetchall() == [("run-clean", 17)]


def test_conflicting_truncation_metadata_does_not_select_favorable_copy(tmp_path: Path) -> None:
    trace = build()
    copy_with_loss = copy.deepcopy(trace["resourceSpans"][0])
    copy_with_loss["resource"]["attributes"] += _attrs({"hangar.export.truncated": True})
    trace["resourceSpans"].append(copy_with_loss)
    trace["resourceSpans"] += build(run="run-clean")["resourceSpans"]
    with connect(str(plane(tmp_path, trace))) as con:
        assert con.execute("select run_id, tool_calls from process_metrics").fetchall() == [("run-clean", 17)]
        assert con.execute("select truncated from runs where run_id = 'run-semver1' order by truncated").fetchall() == [
            (False,), (True,),
        ]
