# Behavior specs

A behavior spec is a predicate over what an agent did, read from hangar's trace export. It says how the agent worked,
never whether the task was resolved.

Specs answer "how did it work?" questions: tests before the commit, no push to `main`, asked before deleting. They do
not answer "did it work?". **Outcome graders come first.** A task's hidden tests decide whether a trial resolved, and a
spec never overrides a grader.

Predicates can be gamed. So the language counts only trusted test runs, and `spec lint` flags the weak shapes listed
under [Anti-gaming](spec-trust.md#anti-gaming).

The input is `hangar.trace/v1` (hangar `docs/api/traces.md`) as flattened into the [data plane](data-plane.md). The
contract is `flightdeck.spec/v1`. Code: `src/flightdeck/specs/lang.py`. Examples:
[`specs/examples/`](https://github.com/Sean-Koval/flightdeck/tree/main/specs/examples). Team specs live in the private
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
    first: {event: test.run}    # trusted runs only (spec-trust.md)
    then: {event: git.commit}
---
id: never-push-main
scope: turn
applies_when: {}                # override the inherited filter
assert:
      never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}
```

`assert` takes one operator over matchers: [Matchers and operators](spec-matchers.md) is the grammar.


### Units

A spec is judged once per unit. `turn` is one agent run (`hangar.run.id`). `job` is a hangar job with all its turns
and its own events: verify, test runs, delivered commits, PR, merge. `session` is one session's turns.

Job-level events sit on the job span. So a spec about `test.run`, `git.commit` events or `pr.merge` needs
`scope: job`.

### Applicability

`harness` matches the run's `hangar.harness` as a glob. `applies_when` takes globs (one or a list) over four `runs`
columns: `source` (`job`, `session`, `experiment`, `shadow`, `local`), `repo` (the job's repo URL), `task_id` and
`variant`.

`task_id` and `variant` are an experiment trial's task and variant. So a spec can judge one task's candidate arm, as
imported ai-dlc workflow assertions do.

Any other key makes every result `unknown`, never a guess. `untrusted`, for example, is a key the data plane does not
carry yet.

### Results

Each unit gets `pass`, `fail`, `not_applicable` or `unknown`. `unknown` never counts as a pass, the same rule as
ai-dlc's "unavailable mandatory observations never pass".

A truncated export (`hangar.export.truncated`) turns a would-be `pass` or `not_applicable` into `unknown`, since what
it lost could have been the violation. A `fail` it shows stays a `fail`.

### Two evaluators

`lang.evaluate` is the reference evaluator, in Python over one flattened export. `lang.sql` compiles a spec to DuckDB
SQL over the data plane. For it, `prepare` builds one `items` table of tool calls, approvals, events and test runs,
optionally for one day.

Each matcher is written once and yields both a Python predicate and a SQL expression. `tests/test_specs.py` checks
that both evaluators agree on 50 random synthetic exports for every operator and scope.

### hangar's reference predicates

[`specs/examples/hangar-reference.yaml`](https://github.com/Sean-Koval/flightdeck/blob/main/specs/examples/hangar-reference.yaml)
writes hangar's four in this language. They are: tests before the commit, no edits outside `src/`, asked before
deleting, and plan → edit → test → PR.

They pass and fail exactly as hangar `tests/test_interfaces.py::_behavior` does on the same exports
(`tests/fixtures/hangar/trace_session_{good,bad}.json`). Two differences when the trigger is absent: `before` and
`each` say `not_applicable` where hangar's plain predicates say false and true.

## Versioning

`flightdeck.spec/v1` is additive. A new operator, matcher key or field is not a new version; renaming or removing one
is `v2`, as with hangar's interfaces.

!!! note "Status"
    The spec language, `spec lint` and `spec test` are done ([#14](https://github.com/Sean-Koval/flightdeck/issues/14)).
    The nightly runner and mutation scoring are merged, and their issues are open; each page says what is
    left.

## Next

- <span id="matchers"></span><span id="operators"></span><span id="order"></span><span id="steers"></span>[Matchers and operators](spec-matchers.md):
  what a spec can match, its operators, event order and steers.
- <span id="the-trusted-test-rule"></span><span id="anti-gaming"></span>[Trusted tests and anti-gaming](spec-trust.md):
  which test runs count, and the weak shapes `spec lint` flags.
- <span id="adr-checks-and-the-nightly-runner"></span><span id="inputs"></span><span id="output"></span><span id="alerts"></span><span id="schedule"></span><span id="two-people-to-loosen-a-check"></span>[ADR checks and the nightly runner](adr-checks.md):
  trace predicates an accepted decision carries, run every night.
- <span id="mutation-scoring"></span><span id="operators_1"></span><span id="plan-and-run"></span><span id="score"></span>[Mutation scoring](mutation-scoring.md):
  whether the suite notices when part of the harness is removed.

## See also

- [Data plane](data-plane.md): the tables the SQL evaluator reads.
- [Judges](judges.md): rubric judges, for what a predicate cannot see.
- [Reports](reports.md): where spec pass rates appear beside the verdict.
- [Statistics](statistics.md#mutation-scores): how a mutant is judged killed.
