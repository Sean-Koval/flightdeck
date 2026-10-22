# Matchers and operators

A spec's `assert` holds one operator over matchers. This page is the grammar; [Behavior specs](behavior-specs.md)
covers files, units and results.

## Matchers

A matcher is a mapping; every key in it must hold for an item to match.

| Key | Matches | From |
| --- | --- | --- |
| `tool: {kind, ops, mcp: {server, tool}, skill}` | a `tool.call` span | `hangar.tool.kind` (`shell edit read search web mcp skill plan other`), `hangar.shell.ops` (any of `test git.commit git.push pr.open delete`), `hangar.mcp.*`, `gen_ai.skill.name` |
| `approval: {ops, status}` | an `approval` span | `hangar.shell.ops`, `hangar.approval.status` (`allowed`, `denied`...) |
| `event: <name>` | a span event by name (any traces.md event: `file.change`, `verify`, `git.commit`, `pr.open`, `pr.merge`, `steer`...) or `test.run` | events, `test_cases` |
| `path: <glob>` | the item's repo-relative path | `hangar.file.repo_path` |
| `input: <regex>`, `output: <regex>` | the clipped tool input or output (500 characters) | `hangar.tool.input`, `hangar.tool.output` |
| `where: {field: test}` | a field test | below |

`where` fields are item columns or a full attribute name such as `hangar.pr.merged_by` or `hangar.verify.passed`.
The columns: `name`, `tool_kind`, `seq`, `turn`, `path`, `op` (file op), `input`, `output`, `status`, `mcp_server`,
`mcp_tool`, `skill`, `trusted`, `total`, `complete`.

A test is a scalar (equality; `null` means absent) or a mapping of `not`, `in`, `regex`, `glob`, `gt`, `gte`, `lt`,
`lte`. A missing value never matches `not`.

Globs are `fnmatch` and DuckDB `GLOB`: `*` also matches `/`, so `src/*` and `src/**` are the same. Regexes are the
common subset of Python `re` and RE2 (DuckDB): no lookaround or backreferences.

## Operators

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

## Order

Order is `hangar.seq` within a session: the event log's position, because many items share a timestamp. Items
without a seq are compared by time, so mixed comparisons are by time (traces.md "Order"). Those are job events, test
runs, and steers recorded before [hangar#162](https://github.com/Sean-Koval/hangar/issues/162).

A `within: {seq: N}` window on an item without a seq is `unknown`. Across sessions (best-of-N attempts) order is by
time only.

## Steers

Since [hangar#162](https://github.com/Sean-Koval/hangar/issues/162), `steer` and `interrupt` events carry `hangar.seq`
(the event-log position where the steer was delivered) and `hangar.steer.class`. The class is `correction`,
`redirect`, `new_info` or `unclassified`, with `hangar.steer.classified_by`; a later classification is also a
`steer.classified` event.

A steer that arrives after its turn ended is `queued` and starts the next turn, so its seq is that turn's start.
Steer-avoidance counts only corrections: `never: {event: steer, where: {hangar.steer.class: correction}}`.

Steers recorded before hangar#162 have no seq and the class `unclassified`. Analyses that need a fork point
([#29](https://github.com/Sean-Koval/flightdeck/issues/29)) take the nearest preceding seq and a judge's class (a
[calibrated rubric](judges.md)), and say the result is approximate.
