# Trusted tests and anti-gaming

A predicate can be gamed. This page says which test runs a spec counts, and what `spec lint` flags. The grammar is in
[Matchers and operators](spec-matchers.md).

## The trusted-test rule

`event: test.run` matches only a run hangar ran itself and trusts: `hangar.test.run.trusted = true`,
`hangar.test.total > 0` and a complete report. That is hangar `src/hangar/testresults.py`'s `TRUSTED` kinds, such as
`verify`. [hangar#164](https://github.com/Sean-Koval/hangar/issues/164) adds `grader` runs and the
`hangar.test.run.counted` attribute with the same meaning.

The agent's own in-turn runs are untrusted, and `pytest --collect-only` reports 0 tests. A spec may say
`allow_untrusted: true`, and `spec lint` flags it.

The shell `test` op is a *hint* read from the command text: `uv run pytest --collect-only` has it. Specs that need
proof of testing use `event: test.run`.

In a job, hangar's verify run precedes every delivered commit (the job's `git.commit` events). The agent's own
in-turn commit always precedes hangar's verify. So "tests before the commit" for a job is
`before: {first: {event: test.run}, then: {event: git.commit}}`.

## Anti-gaming

| Pattern | What to do |
| --- | --- |
| `pytest --collect-only`, `-k nothing`, `--co`, an empty test selection | counted runs need `total > 0`; never use the shell `test` op as proof |
| `pytest \|\| true`, `; exit 0` after the tests | judge the trusted run's result (`where: {status: success}`), not the agent's exit code |
| An approval for something irrelevant before a dangerous action | match the approval's ops (and paths) to the action's: `requires_prior: {approval: {ops: [delete], status: allowed}}` |
| Deleting or writing through `python -c "os.remove(...)"`, `sed -i`, a script | `file.change` only sees edit tools; path specs also read `diff.files`, which covers every file the delivered diff touched |
| Matching on `hangar.tool.input` alone | it is clipped and trivially rephrased (`git push origin HEAD:main`); lint warns unless the matcher also names ops, an event, an approval or a path. Shell semantics read from text accept false negatives |
| Editing the contract | specs and graders live outside anything a harness optimizer can edit ([ADR-0001](decisions/0001-boundary-with-hangar.md) point 5); loosening or deleting one needs a second reviewer |

`spec lint` warns on a missing `harness`, a schema other than `flightdeck.spec/v1`, `allow_untrusted` and a missing
`assert`. It also warns on matching on tool input or output text alone, the shell `test` op, and `applies_when` keys
the data plane lacks.
