"""Pure functions from hangar's interface files to `flightdeck.parquet/v1` rows (dicts keyed by column).

Inputs, as hangar documents them: a `hangar.manifest/v1` dict (hangar `docs/api/manifest.schema.json`), one OTLP/JSON
`hangar.trace/v1` export (`docs/api/traces.md`; opentelemetry-proto 1.11.1 JSON: `intValue` is a decimal string,
lists are `arrayValue.values`) and a `hangar.experiment/v1` index (`docs/api/experiment.schema.json`). The compactor
and the ingest command share these, so each table has one implementation. Unknown attributes land in `attrs` JSON;
strings that still look like a credential after hangar's redaction are masked, not stored.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

Row = dict[str, Any]

SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{36}\b|\bgithub_pat_\w{40,}"
    r"|\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}|\bAKIA[0-9A-Z]{16}\b|\bxox[abpr]-[A-Za-z0-9-]{10,}"
)
MASK = "***"
TEXT_MAX = 2000

# Span attributes that have their own column; everything else goes to `attrs`.
SPAN_COLS = {
    "hangar.kind": "kind", "hangar.seq": "seq", "hangar.seq.end": "seq_end", "hangar.tool.kind": "tool_kind",
    "gen_ai.tool.name": "tool_name", "hangar.tool.input": "tool_input", "hangar.tool.output": "tool_output",
    "hangar.tool.ok": "tool_ok", "hangar.shell.ops": "shell_ops", "hangar.file.repo_path": "file_repo_path",
    "hangar.mcp.server": "mcp_server", "hangar.mcp.tool": "mcp_tool", "gen_ai.skill.name": "skill_name",
    "hangar.approval.status": "approval_status", "hangar.approval.by": "approval_by",
}
EVENT_COLS = {
    "hangar.seq": "seq", "hangar.file.repo_path": "file_repo_path", "hangar.file.op": "file_op", "hangar.text": "text",
}


def scrub(v: Any) -> Any:
    """Mask anything that looks like a credential, recursively."""
    if isinstance(v, str):
        return SECRET.sub(MASK, v)
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items()}
    return v


def otlp_value(v: dict[str, Any]) -> Any:
    """One OTLP/JSON AnyValue as a Python value."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [otlp_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return otlp_attrs(v["kvlistValue"].get("values", []))
    return None


def otlp_attrs(kvs: list[dict[str, Any]]) -> dict[str, Any]:
    return {kv["key"]: scrub(otlp_value(kv.get("value", {}))) for kv in kvs}


def _dt(seconds: float | None) -> str | None:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d") if seconds is not None else None


def _ts(seconds: float | None) -> datetime | None:
    return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None


def _json(d: dict[str, Any]) -> str | None:
    return json.dumps(d, sort_keys=True, default=str) if d else None


def _split(attrs: dict[str, Any], cols: dict[str, str]) -> tuple[Row, str | None]:
    """Attributes with a column, and the rest as JSON."""
    row = {col: attrs[k] for k, col in cols.items() if k in attrs}
    return row, _json({k: v for k, v in attrs.items() if k not in cols})


# --- manifests ---------------------------------------------------------------------------------------------------


def flatten_manifest(m: dict[str, Any], source: str = "session", dt: str | None = None) -> Row:
    """One `hangar.manifest/v1` as a `manifests` row (deduplicated downstream by `digest`)."""
    if m.get("schema") != "hangar.manifest/v1":
        raise ValueError(f"not a hangar.manifest/v1: {m.get('schema')!r}")
    m = scrub(m)
    subj, h, model = m.get("subject") or {}, m.get("harness") or {}, m.get("model") or {}
    env, repo = m.get("environment") or {}, m.get("repo") or {}
    skills = (m.get("skills") or {}).get("effective") or []
    return {
        "run_id": subj.get("run_id"), "source": source, "dt": dt or _dt(m.get("captured_at")), "digest": m["digest"],
        "config_digest": m.get("config_digest"), "captured_at": _ts(m.get("captured_at")),
        "subject_kind": subj.get("kind"), "session_id": subj.get("session_id"), "turn": subj.get("turn"),
        "job_id": subj.get("job"), "person": subj.get("person"), "harness_name": h.get("name"),
        "harness_version": h.get("version"), "harness_locked": h.get("locked"), "harness_mode": h.get("mode"),
        "harness_digest": m.get("harness_digest"), "model_id": model.get("id"), "model_policy": model.get("policy"),
        "model_provider": model.get("provider"), "skills_effective": [f"{s['name']}@{s['digest']}" for s in skills],
        "mcp_servers": [s["name"] for s in m.get("mcp_servers") or []],
        "hooks": [f"{x['event']}:{x['source']}" for x in m.get("hooks") or []],
        "approvals": (m.get("permissions") or {}).get("approvals"),
        "egress_mode": ((m.get("egress") or {}).get("effective") or {}).get("mode"),
        "environment_name": env.get("name"), "environment_spec_digest": env.get("spec_digest"),
        "environment_digest": m.get("environment_digest"),
        "knowledge_snapshot": (m.get("knowledge") or {}).get("snapshot"), "repo_url": repo.get("url"),
        "base_sha": repo.get("base_sha"), "json": json.dumps(m, sort_keys=True),
    }


# --- traces ------------------------------------------------------------------------------------------------------


def flatten_trace(otlp: dict[str, Any], source: str | None = None, run_id: str | None = None) -> dict[str, list[Row]]:
    """One OTLP/JSON `hangar.trace/v1` export as rows of `runs` (one per turn), `spans`, `events` and `test_cases`.

    Each span and event row's `run_id` is its turn's `hangar.run.id`; spans above the turns (the job or session root)
    take `run_id` if given, else the job or session id. Rows keep `hangar.seq`, so ordering by `(seq, start)` within a
    session reproduces the log's order.
    """
    out: dict[str, list[Row]] = {"runs": [], "spans": [], "events": [], "test_cases": []}
    for rs in otlp.get("resourceSpans", []):
        res = otlp_attrs(rs.get("resource", {}).get("attributes", []))
        if res.get("hangar.trace.schema", "hangar.trace/v1") != "hangar.trace/v1":
            raise ValueError(f"not a hangar.trace/v1 export: {res.get('hangar.trace.schema')!r}")
        job_id, session_id = res.get("hangar.job.id"), res.get("hangar.session.id")
        src = source or ("job" if job_id else "session")
        root_run = run_id or job_id or session_id
        truncated = bool(res.get("hangar.export.truncated"))
        spans = [(s, otlp_attrs(s.get("attributes", []))) for ss in rs.get("scopeSpans", []) for s in ss["spans"]]
        by_id = {s["spanId"]: (s, a) for s, a in spans}

        def turn_of(span: dict[str, Any], by_id: dict = by_id, root_run: str | None = root_run) -> str | None:
            seen = set()
            while span is not None and span["spanId"] not in seen:
                seen.add(span["spanId"])
                attrs = by_id[span["spanId"]][1]
                if attrs.get("hangar.kind") == "turn":
                    return attrs.get("hangar.run.id") or root_run
                span = by_id.get(span.get("parentSpanId", ""), (None, None))[0]
            return root_run

        workflow = next((a for _, a in spans if a.get("hangar.kind") in ("job", "session")), {})
        wf_events = [
            (e, otlp_attrs(e.get("attributes", [])))
            for s, a in spans
            if a.get("hangar.kind") in ("job", "session")
            for e in s.get("events", [])
        ]
        for span, attrs in spans:
            rid = turn_of(span)
            day = _dt(int(span["startTimeUnixNano"]) / 1e9)
            cols, rest = _split(attrs, SPAN_COLS)
            out["spans"].append(
                {
                    "run_id": rid, "source": src, "dt": day, "trace_id": span["traceId"], "span_id": span["spanId"],
                    "parent_span_id": span.get("parentSpanId") or None, "job_id": job_id, "session_id": session_id,
                    "environment": res.get("hangar.environment"), "person": res.get("hangar.person"),
                    "name": span.get("name"), "start_ns": int(span["startTimeUnixNano"]),
                    "end_ns": int(span["endTimeUnixNano"]), "status_code": (span.get("status") or {}).get("code"),
                    **cols, "attrs": rest,
                }
            )
            for ev in span.get("events", []):
                ea = otlp_attrs(ev.get("attributes", []))
                if ev["name"] in ("test.run", "test.case"):
                    out["test_cases"].append(_test_row(ev, ea, rid, src, span["traceId"]))
                    continue
                ecols, erest = _split({k: v for k, v in ea.items() if k != "hangar.kind"}, EVENT_COLS)
                if isinstance(ecols.get("text"), str):
                    ecols["text"] = ecols["text"][:TEXT_MAX]
                out["events"].append(
                    {
                        "run_id": rid, "source": src, "dt": _dt(int(ev["timeUnixNano"]) / 1e9),
                        "trace_id": span["traceId"], "span_id": span["spanId"], "span_kind": attrs.get("hangar.kind"),
                        "name": ev["name"], "time_ns": int(ev["timeUnixNano"]), **ecols, "attrs": erest,
                    }
                )
            if attrs.get("hangar.kind") == "turn":
                out["runs"].append(_turn_row(span, attrs, res, workflow, wf_events, rid, src, day, truncated))
    return out


def _turn_row(
    span: dict, a: dict, res: dict, wf: dict, wf_events: list, rid: str | None, src: str, day: str | None,
    truncated: bool,
) -> Row:
    after = [ea for e, ea in wf_events if e["name"] == "verify" and ea.get("hangar.verify.phase") == "after_turn"]
    merges = [ea for e, ea in wf_events if e["name"] == "pr.merge"]
    prs = [ea for e, ea in wf_events if e["name"] == "pr.open"]
    return {
        "run_id": rid, "source": src, "dt": day, "job_id": res.get("hangar.job.id"),
        "session_id": a.get("hangar.session.id") or res.get("hangar.session.id"), "turn": a.get("hangar.turn.number"),
        "person": res.get("hangar.person"), "repo": wf.get("hangar.repo"), "environment": res.get("hangar.environment"),
        "harness": a.get("hangar.harness"), "harness_version": a.get("hangar.harness.version"),
        "model_id": a.get("gen_ai.response.model") or a.get("gen_ai.request.model"),
        "outcome": a.get("hangar.turn.outcome"), "outcome_class": a.get("hangar.outcome.class"),
        "infra_reason": a.get("hangar.outcome.infra_reason"), "manifest_digest": a.get("hangar.manifest.digest"),
        "cost_usd": a.get("hangar.cost_usd"), "cost_source": a.get("hangar.cost_source"),
        "input_tokens": a.get("gen_ai.usage.input_tokens"), "output_tokens": a.get("gen_ai.usage.output_tokens"),
        "cache_read_tokens": a.get("gen_ai.usage.cache_read.input_tokens"),
        "started_at": _ts(int(span["startTimeUnixNano"]) / 1e9), "finished_at": _ts(int(span["endTimeUnixNano"]) / 1e9),
        "verify_passed": after[-1].get("hangar.verify.passed") if after else None,
        "pr_url": wf.get("hangar.pr.url") or (prs[-1].get("hangar.pr.url") if prs else None),
        "pr_number": prs[-1].get("hangar.pr.number") if prs else None, "merged": bool(merges) if prs else None,
        "merged_by": merges[-1].get("hangar.pr.merged_by") if merges else None,
        "diff_files": wf.get("hangar.diff.files"), "truncated": truncated,
    }


def _test_row(ev: dict, a: dict, rid: str | None, src: str, trace_id: str) -> Row:
    g = a.get
    return {
        "run_id": rid, "source": src, "dt": _dt(int(ev["timeUnixNano"]) / 1e9), "trace_id": trace_id,
        "test_run_id": g("hangar.test.run.id"), "suite": g("test.suite.name"), "status": g("test.suite.run.status"),
        "run_kind": g("hangar.test.run.kind"), "trusted": g("hangar.test.run.trusted"),
        "exit_code": g("hangar.test.exit_code"), "total": g("hangar.test.total"), "passed": g("hangar.test.passed"),
        "failed": g("hangar.test.failed"), "errors": g("hangar.test.errors"), "skipped": g("hangar.test.skipped"),
        "complete": g("hangar.test.complete"), "flaky": g("hangar.test.flaky") if ev["name"] == "test.run" else None,
        "time_ns": int(ev["timeUnixNano"]), "case_name": g("test.case.name"),
        "case_status": g("test.case.result.status"), "case_outcome": g("hangar.test.outcome"),
        "sha": g("vcs.ref.head.revision"),
    }


# --- experiments -------------------------------------------------------------------------------------------------


def trial_ref(t: dict[str, Any]) -> str:
    """A trial's own name: its key, plus `~<attempt>` for a retry after an infra error (hangar#166)."""
    return t["key"] + (f"~{t['attempt']}" if (t.get("attempt") or 1) > 1 else "")


def flatten_experiment(index: dict[str, Any]) -> dict[str, list[Row]]:
    """One `hangar.experiment/v1` index as `runs` (one per trial attempt, `run_id` = experiment id + `trial_ref`) and
    `grades`. An `infra_error` trial hangar retried stays, `excluded`, beside its retry under the same key."""
    if index.get("schema") != "hangar.experiment/v1":
        raise ValueError(f"not a hangar.experiment/v1: {index.get('schema')!r}")
    index = scrub(index)
    exp_id, pins = index["id"], index.get("pins") or {}
    variants, tasks = pins.get("variants") or {}, pins.get("tasks") or {}
    runs: list[Row] = []
    grades: list[Row] = []
    for t in index.get("trials", []):
        rid = f"{exp_id}/{trial_ref(t)}"
        day = _dt(t.get("finished_at") or t.get("started_at") or index.get("created_at"))
        v, task, usage = variants.get(t["variant"]) or {}, tasks.get(t["task"]) or {}, t.get("usage") or {}
        verify = t.get("verify") or {}
        runs.append(
            {
                "run_id": rid, "source": "experiment", "dt": day, "job_id": t.get("job"),
                "session_id": t.get("session"), "experiment_id": exp_id, "trial_key": t["key"], "task_id": t["task"],
                "variant": t["variant"], "trial": t["trial"], "person": index.get("person"), "repo": task.get("repo"),
                "variant_description": v.get("description"),
                "environment": v.get("environment"), "harness": v.get("harness"),
                "harness_version": v.get("harness_version"), "model_id": usage.get("model") or v.get("model"),
                "outcome": t.get("outcome"), "reason": t.get("reason"), "outcome_class": t.get("outcome_class"),
                "infra_reason": t.get("infra_reason"), "excluded": t.get("excluded"), "attempt": t.get("attempt"),
                "config_digest": t.get("config_digest"),
                "harness_digest": t.get("harness_digest"), "environment_digest": t.get("environment_digest"),
                "manifest_digest": next((m for m in t.get("manifests") or [] if m), None),
                "base_sha": task.get("base_sha"), "cost_usd": usage.get("cost_usd"),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "cache_read_tokens": usage.get("cache_read_tokens"), "started_at": _ts(t.get("started_at")),
                "finished_at": _ts(t.get("finished_at")), "verify_passed": verify.get("passed"),
                "drift": t.get("drift") or [], "task_invalid": t.get("task_invalid"),
                "contaminated": t.get("contaminated"), "grade_trust": t.get("trust"),
            }
        )
        if (g := t.get("grade")) is not None:
            grades.append(
                {
                    "run_id": rid, "source": "experiment", "dt": day, "experiment_id": exp_id, "trial_key": t["key"],
                    "command": g.get("command"), "exit_code": g.get("exit_code"), "applied": g.get("applied"),
                    "seconds": g.get("seconds"), "error": g.get("error"),
                    "data": json.dumps(g["data"], sort_keys=True) if g.get("data") is not None else None,
                    "grader_digest": g.get("digest"),
                }
            )
    return {"runs": runs, "grades": grades}
