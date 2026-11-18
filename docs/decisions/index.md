# Decisions

Why is flightdeck built this way? Each decision record answers one question, with the options that lost. Two set the
boundary, one sets holdout custody, six keep the code small, and one records the first decision.

## Boundary and custody

| Record | It decides | Status |
| --- | --- | --- |
| [0001](0001-boundary-with-hangar.md) | hangar runs, flightdeck judges, Tower governs. flightdeck holds no sandbox code and no credentials | Accepted |
| [0002](0002-public-code-private-data.md) | The code is public. Traces, mined tasks, sealed holdouts and judge labels are private | Accepted |
| [0006](0006-holdout-custody.md) | Sealed holdouts are hash-manifested, canaried, written blind and scored once | Accepted |
| [0007](0007-evaluator-contract-foundation.md) | Evaluator evidence gets a contract and conformance tests, with no new decision path | Proposed |

## The line budget

flightdeck's analysis code has a fixed size, counted in CI by `scripts/loc_budget.py`. Each record below moved the
limit, or kept it, and says what the lines bought.

| Record | It decides | Limit, in counted lines | Status |
| --- | --- | --- | --- |
| [0003](0003-line-budget.md) | The v0 budget rises from 1,500 | 2,500 | Accepted |
| [0004](0004-local-runner-budget.md) | The local runner's adapter counts | 2,800 | Accepted |
| [0005](0005-post-v0-budget.md) | The post-v0 batch is counted, piece by piece | 3,785 | Accepted |
| [0008](0008-cleanup-after-the-ports.md) | The cleanup drops the local real-client path | 3,785 | Proposed |
| [0009](0009-label-and-integrity-budget.md) | Step labels and process integrity get room | 3,850 | Accepted |
| [0010](0010-default-specs-budget.md) | The team-default spec fixes fit | 3,875 | Accepted |

## The first decision

flightdeck v0 must change one real team decision ([#20](https://github.com/Sean-Koval/flightdeck/issues/20)).

| Record | It decides | Status |
| --- | --- | --- |
| [0011](0011-first-decision-plugin-ab.md) | Day-one users get the channel the pre-registered plugin A/B decides; `stable` stays r1 until then | Proposed |

## Proposals and research

Notes behind a decision that is still open. None of them describes an enabled feature.

- [Evaluator evidence contract](../evaluation-contract-proposal.md): the first slice ADR 0007 proposes.
- [Process integrity](../research/process-integrity.md): what the check establishes, and what it does not.
- [Process integrity plan](../research/process-integrity-plan.md): the scope of that slice.
- [Trace-learning protocol](../research/trace-learning-protocol.md): how a later evaluation avoids leakage.

## Writing one

Copy the [template](https://github.com/Sean-Koval/flightdeck/blob/main/docs/decisions/0000-template.md) to the next
number and open a pull request. The reviewer is never the author. A record may carry a `checks:` block of trace
predicates, which flightdeck runs nightly ([ADR checks](../adr-checks.md)).

## Next

- [0001: the boundary with hangar](0001-boundary-with-hangar.md): the record every other page cites.
- [What's shipped](../status.md): what these decisions have produced so far.
