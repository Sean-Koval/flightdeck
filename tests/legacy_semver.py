"""hangar evals/semver's `classify.rule()` and `metrics.py` (hangar 9013e81), kept verbatim in logic as the
reference `src/flightdeck/metrics/process.sql` is tested against (tests/test_process_metrics.py). Spans are the
old private schema: {kind: tool|llm, name, args, result, error}. Not shipped; hangar deleted the originals (KAN-86).
"""

from __future__ import annotations

import re


def rule(span: dict) -> str:
    a = (span.get("name") or "") + " " + (span.get("args") or "")
    if re.search(r"^(search_web|read_url_content|web_search|fetch)|node_modules|/opt/hangar/harness|require\(", a):
        return "reference"
    if re.search(r"\bgit (add|commit|status|log|diff|show)", a):
        return "vcs"
    if re.search(r"unittest|pytest", a):
        return "test"
    if re.search(r"^(write|edit|write_to_file|replace_file_content|multi_replace|create_file)|cat >|tee |apply_patch",
                 a):
        return "edit"
    if re.search(r"^(read|view_file|list_dir|find_by_name|grep_search|codebase_search)|\b(ls|cat|find|grep|rg|head|"
                 r"sed -n)\b", a):
        return "explore"
    if re.search(r"python3", a):
        return "verify"
    return "other"


def metrics(spans: list[dict]) -> dict:
    """metrics.py's process numbers for one trial, without the Decision-1 columns, tokens or cost."""
    tools = [s for s in spans if s["kind"] == "tool"]
    rseq = [rule(s) for s in tools]
    first_edit = next((i for i, c in enumerate(rseq) if c == "edit"), None)
    test_runs = [s for s in tools if re.search(r"unittest|pytest", s.get("args") or "")]
    test_fail = [s for s in test_runs if s.get("error") or re.search(r"FAILED|Error|Traceback", s.get("result") or "")]
    ref = [s for s in tools if re.search(r"node_modules|/opt/hangar/harness|require\(", s.get("args") or "")
           or re.match(r"search_web|read_url_content|web_search|fetch", s.get("name") or "")]
    loops, state = 0, None
    for s, c in zip(tools, rseq, strict=True):
        is_test = s in test_runs
        if is_test and s in test_fail:
            state = "failed"
        elif c == "edit" and state == "failed":
            state = "edited"
        elif is_test and state == "edited":
            loops += 1
            state = None
    by_rule: dict[str, int] = {}
    for c in rseq:
        by_rule[c] = by_rule.get(c, 0) + 1
    return {"tool_calls": len(tools), "tool_errors": sum(1 for s in tools if s.get("error")),
            "tool_calls_before_first_edit": first_edit, "edit_calls": rseq.count("edit"),
            "test_runs": len(test_runs), "failing_test_runs": len(test_fail), "fix_loops": loops,
            "reference_lookups": len(ref), "by_label": by_rule}
