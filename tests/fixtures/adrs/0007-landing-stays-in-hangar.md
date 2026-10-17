---
id: decision/0007-landing-stays-in-hangar
kind: decision
scope: team
label: internal
status: accepted
author: human:dev-a
valid_from: 2026-10-20
checks:
  - id: landing-stays-in-hangar
    scope: job
    assert: {never: {event: pr.merge, where: {hangar.pr.merged_by: {not: "hangar-landing[bot]"}}}}
  - id: no-merge-outside-landing
    over: hangar.trace/v1
    predicate: "not exists(e where e.kind == 'pr.merge' and e.actor != 'hangar-landing')"
    severity: warn
---
# 0007 Landing stays in hangar

Synthetic fixture (ai-dlc#207 frontmatter). The second check is in another grammar, so its results are unknown.
