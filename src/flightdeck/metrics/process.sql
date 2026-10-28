-- Process metrics: how an agent run got to its result. The only implementation of docs/process-metrics.md.
-- Ported from hangar evals/semver (9013e81): classify.py's rule() becomes step_labels, metrics.py becomes
-- process_metrics. Both read hangar.trace/v1 columns (tool_kind, shell_ops) instead of harness logs, so spans.py's
-- per-harness parsing is gone. classify.py's Decision-1 call is not ported: flightdeck holds no model credentials
-- (ADR-0001), and step labels from a model wait for a calibrated judge (docs/judges.md). Loaded by dataplane/duck.py.

-- One label per tool call (the step taxonomy of hangar 0007 §5.5), first match wins, in classify.rule()'s order.
-- Keyed on hangar.tool.kind and hangar.shell.ops; the command text is read only for what shell_ops doesn't name
-- (read-only git, shell writes and reads, running a script). `idx` is the call's 0-based position in its run.
create or replace view step_labels as
select run_id, source, seq, start_ns, tool_kind, tool_name, tool_input, tool_output, tool_ok, shell_ops,
    file_repo_path,
    case
        when tool_kind = 'web' or regexp_matches(coalesce(tool_input, ''), 'node_modules|/opt/hangar/harness|require\(')
            then 'reference'
        when list_has_any(coalesce(shell_ops, []), ['git.commit', 'git.push', 'pr.open'])
            or (tool_kind = 'shell' and regexp_matches(tool_input, '\bgit (add|status|log|diff|show)\b')) then 'vcs'
        when list_contains(coalesce(shell_ops, []), 'test') then 'test'
        when tool_kind = 'edit' or (tool_kind = 'shell' and regexp_matches(tool_input, 'cat >|tee |apply_patch'))
            then 'edit'
        when tool_kind = 'plan' then 'plan'
        when tool_kind in ('read', 'search')
            or (tool_kind = 'shell' and regexp_matches(tool_input, '\b(ls|cat|find|grep|rg|head|sed -n)\b'))
            then 'explore'
        when tool_kind = 'shell' and regexp_matches(tool_input, '\bpython3?\b|\bnode\b') then 'verify'
        else 'other'
    end as label,
    -- the agent's answer key: a third-party implementation on disk (pi's pack carried node-semver)
    regexp_matches(coalesce(tool_input, ''), 'node_modules|/opt/hangar/harness') as answer_key_risk,
    row_number() over (partition by run_id, source order by seq nulls last, start_ns) - 1 as idx
from spans where kind = 'tool.call';

-- One row per agent run (a turn or a trial) that is not truncated. A test run fails when its tool call failed or its
-- output shows a failure; a fix loop is metrics.py's: a failing test run, then an edit, then the next passing one.
create or replace view process_metrics as
with s as (
    select *, label = 'test' and (tool_ok is false or regexp_matches(coalesce(tool_output, ''), 'FAILED|Error|Traceback'))
        as test_failed
    from step_labels
), f as (
    select *, max(case when test_failed then idx end) over (partition by run_id, source order by idx
        rows between unbounded preceding and 1 preceding) as last_fail
    from s
), passes as (
    select f.run_id, f.source, f.idx, (select min(e.idx) from s e where e.run_id = f.run_id and e.source = f.source
        and e.label = 'edit' and e.idx > f.last_fail) as edit_after
    from f where f.label = 'test' and not f.test_failed and f.last_fail is not null
), loops as (
    select run_id, source, count(*) as fix_loops from passes p
    where p.edit_after < p.idx and not exists (select 1 from s t where t.run_id = p.run_id and t.source = p.source
        and t.label = 'test' and not t.test_failed and t.idx > p.edit_after and t.idx < p.idx)
    group by run_id, source
), steps as (
    select run_id, source, count(*) as tool_calls, count(*) filter (where tool_ok is false) as tool_errors,
        min(idx) filter (where label = 'edit') as tool_calls_before_first_edit,
        count(*) filter (where label = 'edit') as edit_calls,
        count(*) filter (where label = 'test') as test_runs,
        count(*) filter (where test_failed) as failing_test_runs,
        count(*) filter (where label = 'reference') as reference_lookups,
        count(*) filter (where answer_key_risk) as answer_key_reads
    from s group by run_id, source
), counts as (
    select run_id, source, map_from_entries(list({'k': label, 'v': n})) as by_label
    from (select run_id, source, label, count(*) as n from s group by all) group by run_id, source
), trusted as (  -- hangar's own checks, apart from the agent's word (hangar.test.run.counted)
    select run_id, source, count(*) as trusted_test_runs,
        count(*) filter (where status <> 'success' or failed > 0 or errors > 0) as failing_trusted_test_runs
    from test_cases where case_name is null and trusted and total > 0 and complete group by run_id, source
)
select r.run_id, r.source, r.experiment_id, r.task_id, r.variant, r.trial, r.harness, r.model_id,
    coalesce(st.tool_calls, 0) as tool_calls, coalesce(st.tool_errors, 0) as tool_errors,
    st.tool_calls_before_first_edit, coalesce(st.edit_calls, 0) as edit_calls,
    coalesce(st.test_runs, 0) as test_runs, coalesce(st.failing_test_runs, 0) as failing_test_runs,
    coalesce(l.fix_loops, 0) as fix_loops, coalesce(st.reference_lookups, 0) as reference_lookups,
    coalesce(st.answer_key_reads, 0) as answer_key_reads, c.by_label,
    coalesce(t.trusted_test_runs, 0) as trusted_test_runs,
    coalesce(t.failing_trusted_test_runs, 0) as failing_trusted_test_runs,
    r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cost_usd, r.cost_source,
    epoch(r.finished_at - r.started_at) as wall_s
from runs r
left join steps st using (run_id, source)
left join counts c using (run_id, source)
left join loops l using (run_id, source)
left join trusted t using (run_id, source)
where not coalesce(r.truncated, false);
