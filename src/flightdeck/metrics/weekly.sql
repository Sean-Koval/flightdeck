-- The weekly team metrics: the only implementation of docs/metrics.md (hangar reads the result, never recomputes).
-- DuckDB views over flightdeck.parquet/v1. Parameters are DuckDB variables set by weekly.py:
--   ws, we      the ISO week's start and end (timestamptz, UTC; the week is [ws, we))
--   person      one person's metrics, or NULL for everyone
--   repo        one repository (owner/repo), or NULL for all
-- Rate views return k (numerator) and n (denominator); weekly.py adds the Wilson 95% interval.

-- One delegated hangar job (source 'job'; experiment trials and shadows are not delegation), from its job events and
-- the runs of its turns. A job is terminal when its PR merged, its PR closed unmerged, it was abandoned (cancelled),
-- or, with no PR, its last run left it succeeded, failed or cancelled. It counts when it ran at least one turn
-- (excludes cancelled-before-start) and its last run was not an infra_error.
create or replace view metric_jobs as
with ev as (
    select job_id, any_value(repo) as ev_repo, any_value(person) as ev_person, any_value(pr_url) as pr_url,
        min(ts) filter (where kind = 'pr.open') as opened_at,
        min(ts) filter (where kind = 'review.first') as reviewed_at,
        min(ts) filter (where kind = 'pr.merge') as merged_at,
        min(ts) filter (where kind = 'pr.close') as closed_at,
        min(ts) filter (where kind = 'abandon') as abandoned_at,
        any_value(reason) filter (where kind = 'abandon') as abandon_reason,
        any_value(green_to_merge_seconds) filter (where kind = 'pr.merge') as green_to_merge_s,
        any_value(data) filter (where kind = 'pr.merge') as merge_data
    from job_events where source = 'job' group by job_id
), rn as (
    select job_id, any_value(repo) as rn_repo, any_value(person) as rn_person, count(*) as runs,
        sum(cost_usd) as cost_usd,
        sum(coalesce(steers, 0) + coalesce(questions, 0) + (coalesce(job_turn, 1) > 1)::int) as human_touches,
        arg_max(outcome_class, finished_at) as last_class, arg_max(job_state, finished_at) as last_state,
        max(finished_at) as last_finished_at
    from runs where source = 'job' and job_id is not null group by job_id
)
select *, coalesce(ev_repo, rn_repo) as repo, coalesce(ev_person, rn_person) as person,
    coalesce(merged_at, least(closed_at, abandoned_at),
             case when opened_at is null and last_state in ('succeeded', 'failed', 'cancelled')
                  then last_finished_at end) as terminal_at,
    coalesce(runs, 0) > 0 and last_class is distinct from 'infra_error' as counted
from ev full join rn using (job_id);

create or replace view scoped_jobs as
select * from metric_jobs
where (getvariable('person') is null or person = getvariable('person'))
  and (getvariable('repo') is null or repo = getvariable('repo'));

-- yield: jobs whose PR merged / counted jobs that became terminal in the week.
create or replace view weekly_yield as
select count(*) filter (where merged_at is not null) as k, count(*) as n
from scoped_jobs where counted and terminal_at >= getvariable('ws')::timestamptz and terminal_at < getvariable('we')::timestamptz;

-- abandon: counted jobs terminal in the week that were abandoned or whose PR closed unmerged / the same denominator
-- as yield. By reason: hangar's abandon reason, 'unlabelled' when none was given.
create or replace view weekly_abandon as
select count(*) filter (where merged_at is null and coalesce(closed_at, abandoned_at) is not null) as k, count(*) as n
from scoped_jobs where counted and terminal_at >= getvariable('ws')::timestamptz and terminal_at < getvariable('we')::timestamptz;

create or replace view weekly_abandon_reasons as
select coalesce(abandon_reason, 'unlabelled') as reason, count(*) as n
from scoped_jobs where counted and terminal_at >= getvariable('ws')::timestamptz and terminal_at < getvariable('we')::timestamptz
  and merged_at is null and coalesce(closed_at, abandoned_at) is not null
group by 1 order by 2 desc, 1;

-- agent share: merged PRs in the week that a hangar job opened / all PRs merged in the week on the team's repos
-- (prs table, from GitHub). Team or repo scope only: a person filter does not apply.
create or replace view weekly_agent_share as
select count(*) filter (where url in (select pr_url from metric_jobs where pr_url is not null)) as k, count(*) as n
from prs where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz
  and (getvariable('repo') is null or repo = getvariable('repo'));

-- review wait: hours from the PR opening to its first counting review, for agent PRs first reviewed in the week.
create or replace view weekly_review_wait as
select count(*) as n, quantile_cont(epoch(reviewed_at - opened_at) / 3600, 0.5) as p50_h,
    quantile_cont(epoch(reviewed_at - opened_at) / 3600, 0.9) as p90_h
from scoped_jobs
where reviewed_at >= getvariable('ws')::timestamptz and reviewed_at < getvariable('we')::timestamptz and opened_at is not null;

-- green-to-merge: hours from checks green to merge (hangar's green_to_merge_seconds), agent PRs merged in the week.
create or replace view weekly_green_to_merge as
select count(*) as n, quantile_cont(green_to_merge_s / 3600, 0.5) as p50_h,
    quantile_cont(green_to_merge_s / 3600, 0.9) as p90_h
from scoped_jobs
where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz and green_to_merge_s is not null;

-- steer rate: human touches (steers + agent questions answered + follow-up turns) over the jobs merged in the week /
-- jobs merged in the week.
create or replace view weekly_steer_rate as
select count(*) as n, sum(human_touches) / count(*) as value
from scoped_jobs where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz;

-- cost per merged PR: summed run cost_usd of the jobs merged in the week / jobs merged in the week.
create or replace view weekly_cost_per_merged_pr as
select count(*) as n, sum(cost_usd) / count(*) as value
from scoped_jobs where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz;

-- 14-day revert rate: agent PRs merged in the week two weeks earlier (so every one has had 14 days) that a PR merged
-- within 14 days reverts / agent PRs merged that week. Needs both PRs in the prs table.
create or replace view weekly_revert as
select count(*) filter (where exists (
        select 1 from prs r where r.repo = p.repo and r.reverts = p.number
          and r.merged_at <= j.merged_at + interval 14 day)) as k,
    count(*) as n
from scoped_jobs j join prs p on p.url = j.pr_url
where j.merged_at >= getvariable('ws')::timestamptz - interval 14 day and j.merged_at < getvariable('we')::timestamptz - interval 14 day;

-- Outcome labels of each agent PR (KAN-232), from hangar's pr.merge data (hangar docs/api/outcome-labels.md): the
-- share of the agent's added lines the merged diff still adds, and the share of the merged diff's added lines that
-- are not the agent's. Null when hangar recorded none (merged before it did, or `outcome_error`).
create or replace view pr_outcomes as
select job_id, repo, person, merged_at, pr_url, agent_added, merged_added, surviving,
    surviving / nullif(agent_added, 0) as survival_at_merge,
    (merged_added - surviving) / nullif(merged_added, 0) as human_edit_share,
    json_extract_string(merge_data, '$.human_commits')::int as human_commits,
    json_extract_string(merge_data, '$.review_rounds')::int as review_rounds
from (select *, json_extract_string(merge_data, '$.agent_added_lines')::double as agent_added,
          json_extract_string(merge_data, '$.merged_added_lines')::double as merged_added,
          json_extract_string(merge_data, '$.surviving_lines')::double as surviving
      from scoped_jobs where merged_at is not null);

-- survival at merge: surviving lines / the agent's added lines, summed over agent PRs merged in the week with labels.
-- A share of lines, not of PRs, so no interval (lines of one PR are not independent). n is the PRs.
create or replace view weekly_survival_at_merge as
select count(*) as n, sum(surviving) / nullif(sum(agent_added), 0) as value
from pr_outcomes where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz
  and agent_added > 0;

-- human-edit share: merged added lines that are not the agent's / merged added lines, over the same PRs.
create or replace view weekly_human_edit_share as
select count(*) as n, sum(merged_added - surviving) / nullif(sum(merged_added), 0) as value
from pr_outcomes where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz
  and merged_added > 0;

-- active delegators: people with at least 3 agent PRs merged in the week (value) / people with a job run that week (n).
create or replace view weekly_active_delegators as
select count(*) filter (where merged >= 3) as value, count(*) filter (where active) as n
from (select person, count(*) filter (where merged_at >= getvariable('ws')::timestamptz and merged_at < getvariable('we')::timestamptz) as merged,
          bool_or(last_finished_at >= getvariable('ws')::timestamptz and last_finished_at < getvariable('we')::timestamptz) as active
      from scoped_jobs where person is not null group by person);

-- infra errors: runs in the week hangar classed infra_error (left out of yield and abandon), reported as a count.
create or replace view weekly_infra_errors as
select count(*) as value from runs
where outcome_class = 'infra_error' and finished_at >= getvariable('ws')::timestamptz and finished_at < getvariable('we')::timestamptz
  and (getvariable('person') is null or person = getvariable('person'))
  and (getvariable('repo') is null or repo = getvariable('repo'));
