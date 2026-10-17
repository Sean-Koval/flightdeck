# Behavior specs: `flightdeck.spec/v1`

A behavior spec is a predicate over what an agent did, read from hangar's trace export (`hangar.trace/v1`,
hangar `docs/api/traces.md`) as flattened into the data plane ([data-plane.md](data-plane.md)). Specs answer "how did
it work?" questions: tests before the commit, no push to `main`, asked before deleting. They do not answer "did it
work?". **Outcome graders come first**: a task's hidden tests decide whether a trial resolved, and a spec never
overrides a grader. Specs are predicates, and predicates can be gamed, so the language counts only trusted test runs
and `spec lint` flags the weak shapes below.

Code: `src/flightdeck/specs/lang.py`. Examples: [`specs/examples/`](../specs/examples/). Team specs live in the private
data repository ([ADR-0002](decisions/0002-public-code-private-data.md)).

```sh
flightdeck spec lint specs/examples/*.yaml
flightdeck spec test specs/examples/team-default.yaml --trace export.json [--engine python|sql]
```

`spec test` prints `spec<TAB>unit<TAB>result` and exits 1 on any `fail` or `unknown`.

## Writing a spec

A spec file is a YAML stream. Later documents inherit every key of the first except `id` and `assert`, so shared
headers are written once.

```yaml
schema: flightdeck.spec/v1
id: tests-before-commit
harness: "*"                    # harness NAME (glob), never a digest: contracts outlive digests
scope: job                      # turn (default) | job | session
applies_when: {source: [job, experiment, local], repo: "*"}
assert:
  before:
    first: {event: test.run}    # trusted runs only (below)
    then: {event: git.commit}
---
id: never-push-main
scope: turn
applies_when: {}                # override the inherited filter
assert:
  never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}
```

**Units.** A spec is judged once per unit: `turn` is one agent run (`hangar.run.id`), `job` a hangar job with all its
turns and its own events (verify, test runs, delivered commits, PR, merge), `session` one session's turns. Job-level
events sit on the job span, so a spec about `test.run`, `git.commit` events or `pr.merge` needs `scope: job`.

**Applicability.** `harness` matches the run's `hangar.harness` (a glob); `applies_when` takes globs (one or a list)
over four `runs` columns: `source` (`job`, `session`, `experiment`, `shadow`, `local`), `repo` (the job's repo URL),
`task_id` and `variant` (an experiment trial's task and variant, so a spec can judge one task's treatment arm, as
imported ai-dlc workflow assertions do). Any other key (for example `untrusted`, which the data plane does not carry
yet) makes every result `unknown`, never a guess.

### Matchers

A matcher is a mapping; every key in it must hold for an item to match.

| Key | Matches | From |
| --- | --- | --- |
| `tool: {kind, ops, mcp: {server, tool}, skill}` | a `tool.call` span | `hangar.tool.kind` (`shell edit read search web mcp skill plan other`), `hangar.shell.ops` (any of `test git.commit git.push pr.open delete`), `hangar.mcp.*`, `gen_ai.skill.name` |
| `approval: {ops, status}` | an `approval` span | `hangar.shell.ops`, `hangar.approval.status` (`allowed`, `denied`...) |
| `event: <name>` | a span event by name (any traces.md event: `file.change`, `verify`, `git.commit`, `pr.open`, `pr.merge`, `steer`...) or `test.run` | events, `test_cases` |
| `path: <glob>` | the item's repo-relative path | `hangar.file.repo_path` |
| `input: <regex>`, `output: <regex>` | the clipped tool input or output (500 characters) | `hangar.tool.input`, `hangar.tool.output` |
| `where: {field: test}` | a field test | below |

`where` fields are item columns (`name`, `tool_kind`, `seq`, `turn`, `path`, `op` (file op), `input`, `output`,
`status`, `mcp_server`, `mcp_tool`, `skill`, `trusted`, `total`, `complete`) or a full attribute name
(`hangar.pr.merged_by`, `hangar.verify.passed`). A test is a scalar (equality; `null` means absent) or a mapping of
`not`, `in`, `regex`, `glob`, `gt`, `gte`, `lt`, `lte`. A missing value never matches `not`. Globs are
`fnmatch`/DuckDB `GLOB`: `*` also matches `/`, so `src/*` and `src/**` are the same. Regexes are the common subset of
Python `re` and RE2 (DuckDB): no lookaround or backreferences.

### Operators

`assert` holds one operator.

| Operator | Result |
| --- | --- |
| `never: M` | fail if any item matches |
| `eventually: M` | pass if any item matches |
| `count: {match: M, min: N, max: N}` | pass if the number of matches is in range |
| `before: {first: A, then: B}` | `not_applicable` without a B; pass if the first A precedes the first B; fail otherwise (no A included) |
| `order: [M1, M2, ...]` | pass if every Mi occurs and their first occurrences are in that order |
| `each: B`, `requires_prior: A`, `within: {seq: N}` or `{turns: N}` | for every B an A earlier in order and at most N log positions (or turns) before it; `not_applicable` without a B |
| `all: {paths: {from: [file.change, diff.files]}, match: <glob or list>}` | every path matches; a `file.change` outside the checkout has no repo path and fails; `not_applicable` with no paths |
| `any: {paths: {from: [...]}, match: <glob or list>}` | at least one path matches (a delivered file, for ai-dlc's `path-committed`); `not_applicable` with no paths |

**Order** is `hangar.seq` within a session, the event log's position, because many items share a timestamp. Items
without a seq (job events, test runs, `steer`/`interrupt`) are compared by time, so mixed comparisons are by time
(traces.md 'Order'). A `within: {seq: N}` window on an item without a seq is `unknown`. Across sessions (best-of-N
attempts) order is by time only.

### Results

Each unit gets `pass`, `fail`, `not_applicable` or `unknown`. `unknown` never counts as a pass (the same rule as
ai-dlc's "unavailable mandatory observations never pass"): a truncated export (`hangar.export.truncated`) turns a
would-be `pass` or `not_applicable` into `unknown`, since what it lost could have been the violation; a `fail` it
shows stays a `fail`.

### Two evaluators

`lang.evaluate` is the reference evaluator, in Python over one flattened export. `lang.sql` compiles a spec to DuckDB
SQL over the data plane (`prepare` builds one `items` table of tool calls, approvals, events and test runs, optionally
for one day). Each matcher is written once and yields both a Python predicate and a SQL expression;
`tests/test_specs.py` checks that both evaluators agree on 50 random synthetic exports for every operator and scope.

### Hangar's reference predicates

[`specs/examples/hangar-reference.yaml`](../specs/examples/hangar-reference.yaml) writes hangar's four
(tests before the commit, no edits outside `src/`, asked before deleting, plan → edit → test → PR) in this language.
They pass and fail exactly as hangar `tests/test_interfaces.py::_behavior` does on the same exports
(`tests/fixtures/hangar/trace_session_{good,bad}.json`). Two differences when the trigger is absent: `before` and
`each` say `not_applicable` where hangar's plain predicates say false and true.

## The trusted-test rule

`event: test.run` matches only a run hangar ran itself and trusts: `hangar.test.run.trusted = true`,
`hangar.test.total > 0` and a complete report (hangar `src/hangar/testresults.py`, the `TRUSTED` kinds such as
`verify`; hangar #164 adds `grader` runs and the `hangar.test.run.counted` attribute with the same meaning). The
agent's own in-turn runs are untrusted, and `pytest --collect-only` reports 0 tests. A spec may say
`allow_untrusted: true`, and `spec lint` flags it.

The shell `test` op is a *hint* read from the command text: `uv run pytest --collect-only` has it. Specs that need
proof of testing use `event: test.run`. In a job, hangar's verify run precedes every delivered commit (the job's
`git.commit` events), while the agent's own in-turn commit always precedes hangar's verify, so "tests before the
commit" for a job is `before: {first: {event: test.run}, then: {event: git.commit}}`.

## Anti-gaming

| Pattern | What to do |
| --- | --- |
| `pytest --collect-only`, `-k nothing`, `--co`, an empty test selection | counted runs need `total > 0`; never use the shell `test` op as proof |
| `pytest \|\| true`, `; exit 0` after the tests | judge the trusted run's result (`where: {status: success}`), not the agent's exit code |
| An approval for something irrelevant before a dangerous action | match the approval's ops (and paths) to the action's: `requires_prior: {approval: {ops: [delete], status: allowed}}` |
| Deleting or writing through `python -c "os.remove(...)"`, `sed -i`, a script | `file.change` only sees edit tools; path specs also read `diff.files`, which covers every file the delivered diff touched |
| Matching on `hangar.tool.input` alone | it is clipped and trivially rephrased (`git push origin HEAD:main`); lint warns unless the matcher also names ops, an event, an approval or a path. Shell semantics read from text accept false negatives |
| Editing the contract | specs and graders live outside anything a harness optimizer can edit ([ADR-0001](decisions/0001-boundary-with-hangar.md) point 5); loosening or deleting one needs a second reviewer |

`spec lint` warns on: a missing `harness`, a schema other than `flightdeck.spec/v1`, `allow_untrusted`, matching on
tool input or output text alone, the shell `test` op, `applies_when` keys the data plane lacks, and a missing
`assert`.

## ADR checks and the nightly runner

An accepted decision can carry trace predicates that flightdeck runs every night: executable decisions. The `checks:`
convention for ADRs is ai-dlc's (Sean-Koval/ai-dlc#207: `docs/decisions/NNNN-slug.md` with knowledge-note
frontmatter); the grammar is this page's. Each check is a spec without the header: `id`, optional `scope`,
`applies_when`, `harness` (default `"*"`) and `assert`.

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

The expected actor is written in the check, not in flightdeck's code: it depends on hangar's landing identity. Checks
can also sit in a fenced `yaml` block holding `checks:` under a plain `Status: Accepted` line (flightdeck's own
[template](decisions/0000-template.md)). A check written in another grammar (ai-dlc's example `predicate:` string) has
no `assert` and yields `unknown` for every unit, never a pass.

```sh
flightdeck check run --data ./plane [--date 2026-11-03] --specs specs/ --adrs ~/src/team-app:docs/decisions \
    [--alerts-repo team/flightdeck-data]
```

- **Inputs.** The day's `dt=` partition of the data plane and git: `<checkout>:<dir>` reads the ADRs of the
  checkout's committed `HEAD` (uncommitted edits don't count); a plain directory is read as is. No hangar endpoint.
- **Output.** `spec_results` rows (`dt, run_id` (the unit), `source` (the run's), `spec_id`, `spec_source` (`spec` or
  `adr:<repo>/<adr>`), `scope`, `result`, `repo`, `harness_digest`, `knowledge_snapshot`) written to
  `<out>/spec_results/dt=<date>/` (a local root; sync it to the bucket), plus one summary line per check with counts and
  example failing unit ids. A rerun replaces the day's partition.
- **Alerts.** Per (check, repo), over the last `--window` days of `spec_results`: the daily violation rate
  (`fail / (pass + fail)`). The runner picks the split into before/after that best explains the counts (a binomial
  likelihood ratio, an offline change-point) and alerts only when the rate rose and the two Wilson 95% intervals don't
  overlap. The alert names the `harness_digest`/`knowledge_snapshot` values first seen on the change day and links
  example runs. With `--alerts-repo` it opens or comments on one issue per check, labelled `flightdeck:violation`,
  through the operator's `gh` login (flightdeck holds no credentials). Violations go to the Friday review. A check that
  fails on most runs is wrong or badly compiled into the harness. Mute it only by editing the ADR, which needs two
  people.
- **Schedule.** After the nightly compactor: a Cloud Run job, or a GitHub Actions cron in the private data repo. Both
  run while hangar's sandbox pools are off:

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

### Two people to loosen a check

`flightdeck check diff <old> <new>` compares two spec files or ADRs by check id and prints `tightened` (added),
`loosened`, `removed` or `unchanged` per check, then the worst as `label: checks:<label>`. Any edit to an existing
check counts as `loosened`: whether a new regex, window or filter admits more runs can't be decided in general, so a
second reviewer looks. A GitHub Action in the team repo runs it on PRs that touch `docs/decisions/` or `specs/`
(`git show origin/main:<path> > old`) and adds the label; branch protection plus a CODEOWNERS entry for those paths
(the hangar/ai-dlc side) require a reviewer other than the author for `checks:loosened` and `checks:removed`.

## Versioning

`flightdeck.spec/v1` is additive: a new operator, matcher key or field is not a new version; renaming or removing one
is `v2`, as with hangar's interfaces.
