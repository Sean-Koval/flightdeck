# Evaluator evidence contract: first slice

This structural contract is not an enabled feature. Scope and adoption gates are in
[proposed ADR 0007](decisions/0007-evaluator-contract-foundation.md).

## Intended outcome

Let deterministic tests, process judges, and future learned-policy evaluators report evidence without hard-coding an
engine. Reviewers must identify evaluated input, coverage, and outcome comparability.

This slice builds only a structural contract and synthetic tests, not private-run evaluation or a live decision path.

## Contract boundary

The `flightdeck.evaluation/v1` artifact belongs in private storage. Only its schema and synthetic examples belong here.
See `schemas/evaluation/README.md` for revision-1 fields and limits.

- Pin run source, scope, attempt, and exact evaluated bytes. Determinate assessments require effective evaluator and
  specification pins. Other source pins may be explicitly unavailable. Rubric-file digests are not interchangeable with `judges.digest`.
- Preserve requested/actual evaluator kind, implementation/configuration pins, applicable model identity, and fallback
  reason. All assessments share one actual evaluator. Fallback confers no trust.
- Evidence references identify content and exact spans/steps without inline private text. Digests establish neither
  correctness, immutability, nor private storage.
- Pin the selection policy and scope. Distinguish eligible, attempted, and determinate counts; unknown denominator
  differs from zero. Preserve source truncation, input clipping, redaction, and unknown completeness.
- Keep outcomes and process assessments independent. Determinate results require evidence; abstain/error/not-applicable
  require reasons without scores. Preserve score scale, unit, and direction, without silently binarizing ordinal values.
- Missing evidence, infrastructure failures, and missing probabilities never become failure rewards or zero.
  Claimed confidence, empirical calibration, and statistical uncertainty remain separate. No field permits promotion.

Closed core objects reject typos; extensions require namespaced keys. Additions require an exact revision
and deliberate reader-compatibility policy, not silent changes to existing interfaces' additive-compatibility guarantees.

## Structural conformance versus semantic integrity

Schema conformance does not establish semantic integrity. A counted production validator must verify digests and
requested/actual identity equality on direct execution. It must verify unique steps, source membership, evidence
resolution, scope/denominator derivation, finite/duplicate-key-safe JSON, and external rubric semantics.

Determinate counts cannot exceed attempted counts; attempted counts cannot exceed eligible counts.
Complete coverage requires equal positive determinate, attempted, and eligible counts, plus exactly one determinate
step entry per eligible ID. One determinate step over two eligible steps is never complete, although the inequalities
hold. The schema alone cannot reject that false claim.

A schema-only pass permits neither runtime ingestion nor decisions. Do not hide production validation in tests to bypass
the source budget.

`flatten_trace` preserves the source export flag but clips event text at 2,000 characters without a clipping flag.
Adapters must preserve unknown completeness until reconciling exact input. Malformed evidence never becomes a reward.

## Small implementation tasks

1. Record bounded owner approval and independent review; keep ADR0005 and #20 intact.
2. Add the versioned schema under `schemas/evaluation/` with the existing `jsonschema` dependency.
3. Add synthetic fixtures under `tests/fixtures/evaluation/`; write deterministic tests first using the matrix below.
4. Verify focused/aggregate checks, privacy/boundary guards, and source budget; report skipped/blocked stages separately.
   Independently review the final diff.
5. Later, design counted semantic validation and licensed adapters; no paid evaluator call is implied.
6. Later, pair private packets and blinded labels with current experiment/PR reports, not a dashboard. `judge label` exposes potentially
   variant-revealing run IDs; use opaque IDs and a private reverse map.
7. Later, define versioned change proposals with target/base/patch digests, hypothesis, evidence, fixed holdout,
   outcome/cost guardrails, acceptance/rollback criteria, and reviewer decision. Reuse scalar calibration/PPI and trusted grades.

Evaluator, candidate, and training-job approvals remain separate. Training eligibility separately excludes invalid or
contaminated tasks, infrastructure errors, missing probabilities, and insufficient evidence. No exporter is implemented.
The #20 route B comparison and human-reviewed guardrails stay untouched; report verdicts are not promotion eligibility.

## Test matrix

Positive cases: complete, partial, unknown, explicit fallback, evaluator error, missing probabilities, and valid failed
assessments including numeric zero. Include outcome pass/process fail, outcome pass/process abstain, truncated input,
unknown denominator, zero eligible steps, and two evaluator families.

Negative mutations: missing required pin, malformed digest, unsupported schema/state, score on abstain/error,
determinate result without evidence, absent fallback reason, invalid count, and contradictory declared completeness.

Deferred negatives include wrong digests, conflicting steps, arithmetic mismatches, false complete coverage,
foreign-run evidence, undeclared substitutions, and externally invalid scale values. These may pass structural tests;
production validation must reject them before ingestion.

## Compatibility baseline

This slice uses main `759eb1b05dc41a50a3153156b9a773d2a1ec7d1c`, including FDK report labels and theme-v14.
It changes no runtime source, dependency, CLI/report behavior, Parquet table, or existing judge/comparison format.
The measured source count remains 3,784 of the 3,785 cap; broader implementation and promotion gates remain intact.
