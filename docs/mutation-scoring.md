# Mutation scoring

A suite with a low mutation score is decoration. If deleting part of the harness changes nothing the suite can see,
the suite isn't testing that part. `flightdeck mutate` removes one component of a harness at a time and checks that
some grader or spec notices. Code: `src/flightdeck/specs/mutate.py`.

```sh
flightdeck mutate plan tasks/smoke/suite.yaml --harness claude-code --out mutants.yaml [--ops ...] [--max 12] \
  [--n 2] [--data <plane>]
flightdeck mutate run mutants.yaml [--max-usd 40] [--dry-run]
flightdeck mutate score mutants.yaml <run-set> --specs specs/team.yaml --data <plane> [--out score.md]
```

## Operators

Over the base variant's hangar overlay (`Variant{skills, skills_remove, instructions, instructions_append,
approvals}`):

| Operator | Mutants |
| --- | --- |
| `drop-skill` | one per skill: the variant's `skills` minus it, or `skills_remove: [name]` for the skills seen in `--data`'s traces when the variant names none |
| `drop-instruction-line` | one per block of `instructions` and `instructions_append`: blocks start at markdown headings, else each non-empty line is one |
| `approvals` | `approvals: auto` when the base is `deny-risky` |
| `noop` | the variant unchanged: a control that must come out equivalent |
| `drop-hook`, `widen-egress` | not generated, and said so: hooks need harness locks ([hangar#133](https://github.com/Sean-Koval/hangar/issues/133)); hangar fixes egress per experiment, so widening it is a separate experiment |

## Plan and run

`plan` writes a suite file: the base and its mutants as variants named `mutant-<op>-<component>`, `n` trials each
(default 2), plus `base:` and `mutants:` for `score`. Keep tasks cheap: a changed instruction changes the prompt
prefix, and every trial runs in full.

**Equivalent** mutants are listed but not run, and never counted: the no-op, and a dropped skill no trace in `--data`
ever used (by `spans.skill_name`).

`run` submits through `experiment run`'s cost gate. It prints the projection first and refuses a plan above
`--max-usd` (default $40). Mutants are per harness; hooks and the in-turn verify gate differ by runtime.

A mutant is never promoted. `decision.yaml` and `stats compare` name the variants they read, and `mutant-*` variants
appear nowhere else.

## Score

A mutant is **killed** ([statistics](statistics.md#mutation-scores)) when the resolved rate differs from the base's
(paired task bootstrap interval excluding 0). It is also killed when a spec that held on the base (pass^k at or above
`--bound`, default 0.9) falls below it on the mutant. Otherwise it **survived**.

The score is killed / (killed + survived) with a Wilson interval. Equivalent and not-run mutants are left out.

`score` prints a markdown section for the report or PR: the score, then each mutant's verdict and why. Each survivor's
component comes with a spec worth adding; for a dropped skill that is `eventually: {tool: {skill: <name>}}`.

Example: the semver smoke task with `tests-before-commit`. The base variant's `instructions_append` says "Write your
own tests ... and make them pass"; the mutant drops that block. When the mutant's trials commit without a trusted test
run, the spec's pass^k falls from 1 to 0 and the mutant is killed. The no-op is equivalent.

!!! note "Status"
    Code merged ([#53](https://github.com/Sean-Koval/flightdeck/pull/53)). Issue
    [#16](https://github.com/Sean-Koval/flightdeck/issues/16) stays open until the first live mutation run on hangar
    (at most $40). The acceptance case so far is shown on stored results in tests.
