# NNNN: <the decision, as a sentence>

Status: Proposed | Accepted | Superseded by NNNN · <Mon D, YYYY> · decision due <date>

## Context

What forces the decision: facts with sources (file paths, specs, measurements), and what breaks if nothing is decided.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. | | | |
| B. | | | |

## Decision

Choose <option>. The rules that follow from it, numbered, so later work can cite them.

## Consequences

What gets easier, what gets harder, what has to be built or removed, and what would make us revisit this.

## Checks (optional)

Trace predicates flightdeck runs nightly once this decision is Accepted ([behavior-specs.md](../behavior-specs.md):
the `flightdeck.spec/v1` grammar without the header). Loosening or deleting one needs two people.

```yaml
checks: []
# checks:
#   - id: never-push-main
#     scope: turn
#     assert: {never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}}
```
