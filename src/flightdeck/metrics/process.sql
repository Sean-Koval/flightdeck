-- Process metrics: how an agent run got to its result. The only implementation of docs/process-metrics.md.
-- Ported from hangar evals/semver (9013e81): classify.py's rule() becomes step_labels, metrics.py becomes
-- process_metrics. Both read hangar.trace/v1 columns (tool_kind, shell_ops) instead of harness logs, so spans.py's
-- per-harness parsing is gone. classify.py's Decision-1 call is not ported: flightdeck holds no model credentials
-- (ADR-0001), and step labels from a model wait for a calibrated judge (docs/judges.md). Loaded by dataplane/duck.py.

-- Command patterns, as constant macros. A command position is the start of a line or of a segment (after ; & | ( do
-- then), behind `FOO=bar` assignments and wrappers (sudo, timeout 60, npx, `uv run --project x` and its kin).
create or replace macro step_re_at() as
    '(^|[;&|(\n]|\bdo\s|\bthen\s)\s*(\w+=\S*\s+)*((sudo|time|nice|env|xvfb-run|npx|bunx|timeout(\s+-\S+)*\s+\d+[smh]?'
    || '|(uv|poetry|pipenv|hatch|pdm)\s+run(\s+--?[\w-]+(=\S+|\s+[^-\s;&|]\S*)?)*)\s+)*(\S*/)?';
-- A test runner: what hangar's shell_ops calls `test`, plus test and CI scripts (`bash scripts/ci/verify.sh`).
create or replace macro step_re_runner() as step_re_at()
    || '(python[\d.]*\s+-m\s+(pytest|unittest)|pytest|py\.test|tox|nox|jest|vitest|mocha|rspec|phpunit|ctest'
    || '|go\s+test|cargo\s+(test|nextest)|(npm|pnpm|yarn|bun)(\s+run)?\s+tests?|make\s+(test|check)|bazel\s+test'
    || '|dotnet\s+test|mvn\s+(test|verify)|gradlew?\s+(test|check)'
    || '|((ba)?sh\s+)?(\S*/)?(run[_-]?)?(tests?|verify|check|ci)[\w-]*\.sh)($|[\s;&|)])';
-- A probe: a runner asked only for its version or help, or to list tests without running them.
create or replace macro step_re_probe() as
    '\b(pytest|py\.test|unittest|tox|nox|jest|vitest|mocha)\b[^\n;&|]*\s(--version|--help|--collect-only|-V)'
    || '($|[\s;&|)])';
-- A look around: which tool, which version, what is installed, where a module lives. The python is read before
-- quotes are blanked (`python -c "import x; print(x.__file__)"`), and runs nothing for `verify`.
create or replace macro step_re_look_print() as
    '\s*(import\s+[\w.]+(\s*,\s*[\w.]+)*\s*;\s*)*print\(\s*[\w.]*'
    || '(__file__|__version__|__path__|path|version|version_info|executable)\s*\)\s*;?\s*';
create or replace macro step_re_look_py() as
    'python[\d.]*\s+-c\s+("' || step_re_look_print() || '"|''' || step_re_look_print() || ''')';
-- A program's --version is a look; `python -m pkg --help` runs the agent's own CLI, which is `verify`.
create or replace macro step_re_look() as step_re_at()
    || '((which|whereis|command\s+-v)(\s+-\S+)*\s+[^-\s;&|]\S*|[\w.+-]+\s+--version|(python[\d.]*|pytest|py\.test)\s+-V'
    || '|python[\d.]*\s+-m\s+(pytest|pip|uv)\s+--version'
    || '|((python[\d.]*\s+-m\s+|uv\s+)?pip[\d.]*|npm)\s+(list|ls|show|freeze))($|[\s;&|)])';
create or replace macro step_re_setup() as step_re_at()
    || '(pip[\d.]*\s+install|python[\d.]*\s+-m\s+(pip\s+install|venv)|uv\s+(sync|venv|add|pip\s+install|tool\s+install)'
    || '|poetry\s+(install|add)|pipenv\s+install|conda\s+(install|create)|(npm|pnpm|yarn|bun)\s+(ci|install|i|add)'
    || '|(apt|apt-get|brew|apk|dnf|yum)\s+(-\S+\s+)*install|cargo\s+(fetch|install)|go\s+(mod\s+download|get|install)'
    || '|bundle\s+install|gem\s+install|composer\s+install|mise\s+install)($|[\s;&|)])';
-- A shell write: cat > and tee (hangar's kit), in-place editors, patches, python that writes or rewrites files, and
-- redirects into a source or config file.
create or replace macro step_re_write() as
    'cat >|tee |apply_patch|\bsed\s+(-\S+\s+)*-i|\bperl\s+-\S*i|\bgit\s+apply\b|\bpatch\s+-p|open\([^)\n]*,\s*[''"][wa]'
    || '|\.write_(text|bytes)\(|[^>&\d]>>?\s*[''"]?[\w./-]+\.(py|pyi|js|mjs|ts|tsx|jsx|go|rs|java|kt|rb|php|c|h|cc|cpp'
    || '|hpp|cs|swift|sql|sh|toml|ya?ml|md|rst|cfg|ini|html|css)\b'
    -- a python heredoc that reads a file and replaces text in it: its write is often past the clipped input
    || '|(?s:python[\d.]*\s+-\s*<<.*(read_text\(|\.read\(\)).*\.replace\()';

-- The labels of each tool call (the step taxonomy of hangar 0007 §5.5, plus `setup`), in classify.rule()'s order:
-- `labels` has every label a call matches, `label` the first. Keyed on hangar.tool.kind and hangar.shell.ops; the
-- command text is read for what shell_ops doesn't name (read-only git, setup, shell writes and reads, running a
-- script) and for test runs it misses (loops, wrapper flags, CI scripts). `idx` is the call's 0-based position.
create or replace view step_labels as
with c as (
    select *, coalesce(tool_input, '') as inp, coalesce(shell_ops, []) as ops, tool_kind = 'shell' as sh,
        -- quoted text blanked, so `hangar-agent done "... python -m x ..."` runs no python (nor does pytest under -m)
        regexp_replace(coalesce(tool_input, ''), '"[^"\n]*"?|''[^''\n]*''?', '""', 'g') as cmd
    from (select distinct * from spans) where kind = 'tool.call'
), m as (
    select *, list_filter([
        case when tool_kind = 'web' or regexp_matches(inp, 'node_modules|/opt/hangar/harness|require\(')
            then 'reference' end,
        case when list_has_any(ops, ['git.commit', 'git.push', 'pr.open'])
            or (sh and regexp_matches(inp, '\bgit (init|add|status|log|diff|show)\b')) then 'vcs' end,
        case when (list_contains(ops, 'test') and not regexp_matches(inp, step_re_probe()))
            or (sh and regexp_matches(regexp_replace(inp, step_re_probe(), ' ', 'g'), step_re_runner()))
            then 'test' end,
        case when tool_kind = 'edit' or (sh and regexp_matches(inp, step_re_write())) then 'edit' end,
        case when sh and regexp_matches(cmd, step_re_setup()) then 'setup' end,
        case when tool_kind = 'plan' then 'plan' end,
        case when tool_kind in ('read', 'search')
            or (sh and regexp_matches(inp, '\b(ls|cat|find|grep|rg|head|tail|wc|tree|sed -n)\b'))
            or (sh and (regexp_matches(cmd, step_re_look()) or regexp_matches(inp, step_re_look_py())))
            then 'explore' end,
        case when sh and regexp_matches(regexp_replace(
            -- `cmd` again, with python that only looks around taken out first
            regexp_replace(regexp_replace(inp, step_re_look_py(), ' ', 'g'), '"[^"\n]*"?|''[^''\n]*''?', '""', 'g'),
            'python[\d.]*\s+-m\s+(pytest|unittest|pip|venv)\b', ' ', 'g'),
            step_re_at() || '(python[\d.]*|node)\s+([^-\s]|-[cme]?\s)') then 'verify' end
    ], lambda x: x is not null) as found
    from c
)
select run_id, source, seq, start_ns, tool_kind, tool_name, tool_input, tool_output, tool_ok, shell_ops,
    file_repo_path, coalesce(found[1], 'other') as label, if(len(found) = 0, ['other'], found) as labels,
    -- the agent's answer key: a third-party implementation on disk (pi's pack carried node-semver)
    regexp_matches(inp, 'node_modules|/opt/hangar/harness') as answer_key_risk,
    row_number() over (partition by run_id, source order by seq nulls last, start_ns) - 1 as idx
from m;

-- One row per agent run (a turn or a trial) that is not truncated. Edits and test runs count every call whose labels
-- have them. A test run fails when its tool call failed or its output shows a failure; a fix loop is metrics.py's: a
-- failing test run, then an edit, then the next passing one (the edit may be in the same call, before its tests).
create or replace view process_metrics as
with s as (
    select *, list_contains(labels, 'test') as is_test, list_contains(labels, 'edit') as is_edit,
        list_contains(labels, 'test') and (tool_ok is false
            or regexp_matches(coalesce(tool_output, ''), 'FAILED|Error|Traceback')) as test_failed
    from step_labels
), f as (
    select *, max(case when test_failed then idx end) over (partition by run_id, source order by idx
        rows between unbounded preceding and 1 preceding) as last_fail
    from s
), passes as (
    select f.run_id, f.source, f.idx, (select min(e.idx) from s e where e.run_id = f.run_id and e.source = f.source
        and e.is_edit and e.idx > f.last_fail) as edit_after
    from f where f.is_test and f.tool_ok is true and not f.test_failed and f.last_fail is not null
), loops as (
    select run_id, source, count(*) as fix_loops from passes p
    where p.edit_after <= p.idx and not exists (select 1 from s t where t.run_id = p.run_id and t.source = p.source
        and t.is_test and t.tool_ok is true and not t.test_failed and t.idx > p.edit_after and t.idx < p.idx)
    group by run_id, source
), steps as (
    select run_id, source, count(*) as tool_calls, count(*) filter (where tool_ok is false) as tool_errors,
        min(idx) filter (where is_edit) as tool_calls_before_first_edit,
        count(*) filter (where is_edit) as edit_calls,
        count(*) filter (where is_test) as test_runs,
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
    from (select distinct * from test_cases)
    where case_name is null and trusted and total > 0 and complete group by run_id, source
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
from (select distinct * from runs) r
left join steps st using (run_id, source)
left join counts c using (run_id, source)
left join loops l using (run_id, source)
left join trusted t using (run_id, source)
where not coalesce(r.truncated, false)
    -- An identity with conflicting content has no unique process history. Keep raw rows, omit its aggregate.
    and not exists (select 1 from spans s where s.run_id = r.run_id and s.source = r.source
        group by s.trace_id, s.span_id having count(distinct s) > 1)
    and not exists (select 1 from runs conflicting where conflicting.run_id = r.run_id and conflicting.source = r.source
        group by conflicting.run_id, conflicting.source having count(distinct conflicting) > 1);
