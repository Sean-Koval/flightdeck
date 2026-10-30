# Outcome labels

How much of an agent's PR did the merge keep? Two weekly metrics answer it, from labels hangar records on every
merged agent PR (KAN-232). They are a finer signal than merged or reverted, and feed the attention metric (KAN-70)
and the choice of regression tasks.

## Where the labels come from

hangar reads them from GitHub when the PR merges and sends them on the `pr.merge` job event
([hangar's outcome labels](https://sean-koval.github.io/hangar/api/outcome-labels/)). The compactor keeps them in
`job_events.data`.

The agent's diff runs from the base to the head hangar last pushed. The merged diff runs from the base to the PR's
head at merge. hangar matches added lines by file and stripped text, and sends counts, not code.

A PR merged before hangar recorded labels, or with `outcome_error`, has none. The views leave it out.

## Survival at merge

Of the lines the agent's diff adds, the share the merged diff still adds. It is surviving lines ÷ the agent's added
lines, summed over agent PRs merged in the week. `weekly_survival_at_merge` returns it as `value`, with `n` the PRs.

It is a share of lines, not of PRs, so it has no Wilson interval: lines of one PR are not independent. A low value
means reviewers rewrote or dropped the agent's code before merging.

## Human-edit share

Of the lines the merged diff adds, the share that are not the agent's. It is (merged added − surviving lines) ÷
merged added lines, over the same PRs (`weekly_human_edit_share`). Human commits pushed onto the branch raise it.

## Per PR

`pr_outcomes` has one row per merged agent PR in scope, with `survival_at_merge` and `human_edit_share`. It also has
`human_commits`, the commits on the branch hangar didn't author, and `review_rounds`, the head commits a human
reviewed. Use it to
pick PRs for regression tasks or to label failures.

```sql
select job_id, pr_url, survival_at_merge, human_commits from pr_outcomes order by survival_at_merge limit 10;
```
