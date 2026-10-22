# ADR checks and the nightly runner

An accepted decision can carry trace predicates that flightdeck runs every night: executable decisions. The `checks:`
convention for ADRs is ai-dlc's ([ai-dlc#207](https://github.com/Sean-Koval/ai-dlc/issues/207):
`docs/decisions/NNNN-slug.md` with knowledge-note frontmatter); the grammar is flightdeck's
[spec language](spec-matchers.md).

Each check is a spec without the header: `id`, optional `scope`, `applies_when`, `harness` (default `"*"`) and
`assert`.

```yaml
---
id: decision/0007-landing-stays-in-hangar
kind: decision
status: accepted                 # only accepted ADRs run
checks:
  - id: landing-stays-in-hangar
    scope: job
    assert: {never: {event: pr.merge, where: {hangar.pr.merged_by: {not: "hangar-landing[bot]"}}}}
---
```

The expected actor is written in the check, not in flightdeck's code: it depends on hangar's landing identity.

Checks can also sit in a fenced `yaml` block holding `checks:` under a plain `Status: Accepted` line (flightdeck's own
[template](https://github.com/Sean-Koval/flightdeck/blob/main/docs/decisions/0000-template.md)). A check written in
another grammar, such as ai-dlc's example `predicate:` string, has no `assert`. It yields `unknown` for every unit,
never a pass.

```sh
flightdeck check run --data ./plane [--date 2026-11-03] --specs specs/ --adrs ~/src/team-app:docs/decisions \
    [--alerts-repo team/flightdeck-data]
```

## Inputs

The day's `dt=` partition of the data plane, and git. `<checkout>:<dir>` reads the ADRs of the checkout's committed
`HEAD`; uncommitted edits don't count. A plain directory is read as is. No hangar endpoint.

## Output

`spec_results` rows: `dt`, `run_id` (the unit), `source` (the run's), `spec_id`, `spec_source` (`spec` or
`adr:<repo>/<adr>`), `scope`, `result`, `repo`, `harness_digest`, `knowledge_snapshot`. They are written to
`<out>/spec_results/dt=<date>/`, a local root to sync to the bucket.

The runner also prints one summary line per check with counts and example failing unit ids. A rerun replaces the
day's partition.

## Alerts

Per (check, repo), over the last `--window` days of `spec_results`, the runner computes the daily violation rate:
`fail / (pass + fail)`. It picks the split into before and after that best explains the counts (a binomial likelihood
ratio, an offline change-point). It alerts only when the rate rose and the two Wilson 95% intervals don't overlap.

The alert names the `harness_digest` and `knowledge_snapshot` values first seen on the change day and links example
runs. With `--alerts-repo` it opens or comments on one issue per check, labelled `flightdeck:violation`, through the
operator's `gh` login. flightdeck holds no credentials.

Violations go to the Friday review. A check that fails on most runs is wrong, or badly compiled into the harness.
Mute it only by editing the ADR, which needs two people.

## Schedule

After the nightly compactor: a Cloud Run job, or a GitHub Actions cron in the private data repo. Both run while
hangar's sandbox pools are off.

```yaml
on: {schedule: [{cron: "30 8 * * *"}]}     # 04:30 ET, after the compactor
jobs:
  checks:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7              # the private data repo: plane/, specs/
      - run: git clone --depth 1 https://github.com/team/app team-app
      - run: uvx --from git+https://github.com/Sean-Koval/flightdeck flightdeck check run --data plane --specs specs
               --adrs team-app:docs/decisions --alerts-repo ${{ github.repository }}
        env: {GH_TOKEN: "${{ secrets.GITHUB_TOKEN }}"}
```

## Two people to loosen a check

`flightdeck check diff <old> <new>` compares two spec files or ADRs by check id. It prints `tightened` (added),
`loosened`, `removed` or `unchanged` per check, then the worst as `label: checks:<label>`.

Any edit to an existing check counts as `loosened`. Whether a new regex, window or filter admits more runs can't be
decided in general, so a second reviewer looks.

A GitHub Action in the team repo runs it on PRs that touch `docs/decisions/` or `specs/`
(`git show origin/main:<path> > old`) and adds the label. Branch protection plus a CODEOWNERS entry for those paths
then require a second reviewer for `checks:loosened` and `checks:removed`. That is the hangar or ai-dlc side.

!!! note "Status"
    Code merged ([#41](https://github.com/Sean-Koval/flightdeck/pull/41)). Issue
    [#15](https://github.com/Sean-Koval/flightdeck/issues/15) stays open until one real team ADR carries a `checks:`
    block and the nightly run is scheduled in the private data repository.
