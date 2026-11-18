# Importing ai-dlc scenarios

An ai-dlc evaluation suite becomes flightdeck tasks, behavior specs and a suite file, in one command.

ai-dlc's scenario contract moved here (#17): `src/flightdeck/ported/aidlc/contracts.py` (`Suite`, `Scenario`,
`Assertion`) and its JSON Schema, `schemas/aidlc/scenario.schema.json`, from ai-dlc's handoff commit `f5be4f4`.

```sh
flightdeck task import-aidlc evaluations/suites/smoke.json --out tasks/imported/smoke
```

It validates the suite with ai-dlc's models. A credential-shaped key or value is refused, naming the field and never
the value. Ids must be unique, both arms must run, and each fixture must match its digest. It writes nothing unless
every scenario converts.

## What it writes

`<scenario>/`, a task. `goal` is `instruction.md`. The fixture is `environment/workspace/`, copied into ai-dlc's
digest-pinned Python image. The hidden fixture's `test_*.py` are `tests/`, run by a generic `test.sh` with unittest,
as ai-dlc's controller ran them. It runs on an isolated copy of the whole tree; narrow it to the code under test when
you can.

`answers` become `[flightdeck.agent] answers`: bounded replies, where an unmatched question is needs-input, which
hangar models as a cancelled trial. `limits` become `[agent] timeout_sec` and `[flightdeck] max_turns`. `answers` sit
under `[flightdeck]`, not Harbor's `[agent]`, so the task stays valid for Harbor.

`specs/<scenario>.yaml`: one [behavior spec](behavior-specs.md) per assertion that isn't the grader, scoped with
`applies_when: {task_id: <scenario>}`. Workflow assertions also take `variant: treatment`, since ai-dlc judged
workflow only in the treatment arm.

`suite.yaml`: the scenarios as tasks and the arms as variants `treatment` and `baseline`. The variants are left empty
for you to fill with the hangar overlay that makes each arm what ai-dlc meant (with or without ai-dlc).

## Assertions

The command prints the mapping as a table. Assertions map like this, and any other kind fails the import:

| ai-dlc assertion | Becomes |
| --- | --- |
| `hidden-tests` | the task's grader (`tests/`) |
| `commit-present` | `eventually: {event: git.commit}`; with a `path`, `any` delivered file (`diff.files`) matches it |
| `path-committed` | `any` delivered file (`diff.files`) matches the path |
| `ordering` | `before`: the first edit of `before`'s path precedes `after`'s. Approximate: hangar's `git.commit` events carry no paths, so this is edit order, not commit order |
| `artifact-present` | `any` changed or delivered file matches `expect` (refused without `expect`) |
| quality dimension (`human-review`) | a spec with no `assert` and a `pending` note: always `unknown` until a person records it, or a judge calibrated under #27 |
| `checkpoints` | dropped, and listed: ai-dlc never observed them |

`diff.files` is the delivered diff on hangar, and the committed plus uncommitted paths on the local runner. So
`path-committed` means "would be delivered".

## Outcomes

ai-dlc's `ArmReport.outcome` keeps failures apart, and flightdeck keeps them apart the same way. `infrastructure` is
`outcome_class = infra_error`, excluded from comparisons. `product` is an unresolved grade. `workflow-violation` is a
failing workflow spec. `unavailable` is `unknown`: a missing grade or a spec without evidence, which never passes.

Transcripts are never evidence. Test runs count only when the controller or hangar ran them (`trusted`).

## Not ported

ai-dlc's `evaluate.py`: its grading is the grader plus the specs above. `planning.py`'s profile and attempt matrix:
suite files and variants replace them. Its credential tripwire, field-naming validation and the fixture `tree_digest`
are kept in `ported/aidlc/planning.py`.

## Next

- [Tasks](tasks.md): the task directory the import writes.
- [Behavior specs](behavior-specs.md): the specs each assertion becomes.
- [The two public tasks](task-fixtures.md): csv-validator, the fixture first converted by hand.
