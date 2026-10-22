# 0007: Design evaluator evidence without enabling a new decision path

Status: Proposed · Oct 21, 2026 · the existing ADR 0005 feature gate remains in force

## Context

The owner requested smaller implementation tasks, product-boundary validation, and an agent team to begin an
evaluation/learning integration. This proposal narrows the first slice to a contract and synthetic conformance
tests. It does not accept itself or silently supersede the owner-ratified [ADR 0005](0005-post-v0-budget.md).

The implementation base is main `759eb1b05dc41a50a3153156b9a773d2a1ec7d1c`, measured at 3,784 of 3,785 counted
lines, following the report-label and theme-v14 updates. This slice leaves that count and limit unchanged.

The report and ADR required by [#20](https://github.com/Sean-Koval/flightdeck/issues/20) remain a prerequisite for
new feature work, not just runtime expansion. An artifact-only design is not an automatic exemption from that gate.

On October 21, 2026, the owner approved the bounded schema, synthetic fixtures, deterministic tests, and written
architecture decision scope. That authorizes this preparatory exception only;
it does not satisfy #20, raise the cap, accept this ADR for merge, or authorize runtime adoption.

Existing `judges/` ingests scalar labels supplied by external evaluators, calibrates each rubric/model digest
against human labels, and reuses PPI. `stats.compare.METRICS` accepts only `resolved`, `cost_usd`, `tool_calls`,
and `wall_s`; a rubric gate does not make process scores an implemented comparison metric. Trace text may be
clipped, so successful parsing alone cannot establish full process evidence.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Import an evaluator/RL engine now | Couple the path directly to one engine | Apparent feature coverage | Licensing ambiguity, credential/runtime boundaries, and misleading missing-data rewards |
| B. Specify a backend-neutral contract first | Schema, synthetic fixtures, tests, and adoption gates | Reviewable and deterministic, preserves decisions | Does not run an evaluator or provide review UI |
| C. Build a dashboard first | New service and UI | Early visual feedback | No trustworthy contract; conflicts with present scope |

## Decision proposed

Choose B for review, limited to [the contract proposal](../evaluation-contract-proposal.md). The owner's bounded
authorization, not zero counted source impact, permits constructing these artifacts. Runtime adoption remains out.

1. Hangar captures and executes. Flightdeck owns evaluator contracts, validation, calibration, and analysis.
   Team harness/skill/agent changes remain versioned configuration. Tower is an existing governance product;
   Flightdeck's promotion-approval edge remains planned, not an already enforced integration.
2. Keep the source-budget limit, `ported/`, reports, CLI commands, comparison metrics, and Parquet schemas unchanged.
   Do not put production logic in tests or another uncounted directory to bypass the source budget.
3. Add only a versioned JSON Schema, synthetic public fixtures, deterministic conformance tests, and documentation.
   Schema conformance does not establish evidence authenticity, calibration, or fitness for promotion.
4. Keep evaluator readiness separate from candidate performance, and process assessments separate from verified
   outcomes. Missing evidence, partial coverage, infrastructure failures, and missing token probabilities must not
   silently become failure rewards or numeric zero.
5. Preserve requested and actual evaluator identity and explicit fallback reason. All assessments in one artifact
   use its declared actual evaluator. Mixed methods require separate artifacts. Fallback does not confer trust.
6. Evidence references identify content and exact spans/steps without inline private text. Public fixtures contain
   synthetic references only, never private traces, rationale text, credentials, labels, or code excerpts.
7. Do not vendor or depend on either similarly named upstream without separate review.
   [`xid32/ECHO@861e20c`](https://github.com/xid32/ECHO/tree/861e20c7e149c509cf50029a7a793d3ba67de2f4)
   has no discovered redistribution license. MIT-licensed
   [`microsoft/echo-rl@f4c3c7e`](https://github.com/microsoft/echo-rl/tree/f4c3c7ecf78412a507d3c7b0dc0079cdae45d10c)
   is a different weight-training stack. Naming similarity is not permission or an adapter contract.
8. Any production semantic validator, evaluator adapter, review UI, metric bridge, or training exporter needs a
   separately measured design and the existing real-decision gate. All new production code counts. A cap change
   needs an accepted ADR, not an edit to the limit or an exemption for a prototype.

## Consequences

This slice establishes a shared structural shape without claiming an operational learning loop. It does not trust
arbitrary producer assertions or add a metric to `stats compare`. Later adoption must verify content, references,
cross-field consistency, coverage, private access, calibrated scalar conversion, and held-out outcomes. A proposal
is never permission to execute, train, deploy, modify a live harness, or promote an agent.

An independent reviewer must review this ADR before acceptance, per CONTRIBUTING.md. The proposal remains Proposed
until that review is incorporated; the bounded implementation exception and broader runtime acceptance are separate.
