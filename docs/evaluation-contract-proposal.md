# Evaluator evidence contract: first slice

This structural contract is not an enabled feature. Scope and adoption gates are in
[proposed ADR 0007](decisions/0007-evaluator-contract-foundation.md).

## Intended outcome

Let deterministic tests, process judges, and future learned-policy evaluators describe their evidence without
hard-coding one engine. A reviewer must be able to tell what was actually evaluated, on which pinned input, with
what coverage, and whether the result could be compared with existing outcomes. The first slice builds only the
structural contract and synthetic tests, not private-run evaluation or a live decision path.

## Contract boundary

The document identifies itself as `flightdeck.evaluation/v1`; actual evaluation records belong in private storage.
Only the schema and synthetic examples belong in this public repository.
The schema reference at `schemas/evaluation/README.md` defines the revision-1 fields and structural limits.

- Identity includes run source, scope, attempt, and exact input digest. Effective evaluator and rubric/test-specification
  identities are mandatory for determinate assessments. Other source pins can be explicitly unavailable, not invented.
  The input digest covers bytes actually evaluated, not a different original trace.
- Requested and actual evaluators carry kind, implementation version, configuration digest, and model identity when
  relevant. Deterministic tests, trace predicates, outcome graders, process rubrics, and learned-policy evaluation fit
  the envelope. Rubric-file bytes are not interchangeable with the selected-field digest from `judges.digest`.
- Execution is direct, fallback, or error. Fallback records why the requested method was not used; all assessments
  share the actual evaluator in this artifact. Infrastructure failure is not valid evidence of task failure.
- Evidence uses content digests and opaque locators plus optional stable trace/span/step selectors. Rationale, if
  referenced, stays private. Digests identify bytes but do not prove private storage, immutability, or correctness.
- A pinned selection policy defines eligible steps in a stated scope. Eligible, attempted, and determinate counts
  differ: one pass and one abstention over two eligible steps is 50% determinate coverage. Unknown denominator and
  zero eligible steps differ. Source truncation, input clipping, redaction, and unknown completeness remain visible.
- Outcome and process are independent. Assessed pass/fail/value results require evidence. Abstain/error/not-applicable
  results carry reasons and no score. Scores declare scale, unit, and direction; ordinal values are not silently
  normalized into binary outcomes. Outcome pass/process fail and outcome pass/process abstain are valid combinations.
- Claimed confidence, empirical calibration, and statistical uncertainty are separate concepts. No field grants
  promotion permission. Training eligibility separately excludes invalid tasks, contamination, infrastructure errors,
  missing probabilities, and insufficient evidence; this slice does not implement a training exporter.

An exact schema revision plus a namespaced extensions object permits experimental metadata without accepting core
field typos. Structural conformance and future tolerant-reader compatibility are separate policies; this does not
silently change the existing versioned interfaces' additive-compatibility promise.

## Structural conformance versus semantic integrity

JSON Schema can enforce identifier/digest shape, required provenance, known states, score absence on abstain/error,
required fallback reasons, and incompatible declared completeness flags. Tests prove those structural constraints.

A later counted production validator must verify digest contents, actual/requested identity equality on direct
execution, determinate <= attempted <= eligible counts, unique step IDs and source membership, evidence resolution,
scope/denominator derivation, finite/duplicate-key-safe JSON parsing, and values against external rubric semantics.
Complete coverage additionally requires determinate = attempted = eligible > 0 and exactly one determinate step entry
for each eligible ID. For example, one determinate step out of two eligible steps must never be labeled complete even
though it satisfies the count inequalities; the structural schema alone cannot reject that false claim.
A schema-only pass is not permission for runtime ingestion or decision use. Do not hide this validator in tests to
fit the source budget.

Current Parquet alone cannot prove full evidence completeness: `flatten_trace` propagates the source export flag
but also clips event text at 2,000 characters without a corresponding clipping flag. Future adapters must preserve
unknown completeness until they can reconcile the exact input. No missing or malformed evidence becomes a reward.

## Small implementation tasks

1. Freeze the bounded scope and record owner approval plus independent review; keep ADR0005 and #20 intact.
2. Add the versioned schema under `schemas/evaluation/` with the existing `jsonschema` dependency.
3. Add synthetic fixtures under `tests/fixtures/evaluation/`, spanning complete, partial, unknown, explicit fallback,
   valid failed, infrastructure-error, and missing-probability examples and at least two evaluator families.
4. Write deterministic tests first: validate good fixtures and reject missing pins, malformed digests, scores on
   abstain/error, determinate results without evidence, missing fallback reason, and contradictory completeness.
5. Verify focused tests, applicable aggregate checks, privacy/boundary guards, and source budget; report blocked or
   skipped stages separately. Independently review the final diff.
6. Later, design a counted semantic validator and licensed external-method adapter; no paid evaluator call is implied.
7. Later, design private review packets and blinded human labels. Current `judge label` exposes raw run IDs, which
   can encode stable/candidate variants. Use opaque review item IDs with a private reverse map, not report tail labels.
8. Later, define versioned change proposals: target/base/patch digests, hypothesis, evidence, fixed holdout, outcome/cost
   guardrails, acceptance/rollback criteria, and reviewer decision. Reuse scalar calibration/PPI and trusted grades.

The review surface starts with a private packet and the current experiment/PR report, not a dashboard. Evaluator
approval, candidate review, and training-job approval are separate. The existing #20 route B comparison and its
human-reviewed guardrails stay untouched. A primary report verdict is not full promotion eligibility.

## Test matrix

Positive structural cases: outcome pass/process fail; outcome pass/process abstain; evaluator error; explicit fallback;
truncated input with unknown denominator; zero eligible steps; and true numeric zero from a valid failed assessment.
Two evaluator families must use the same envelope.

Negative mutations: missing required pin, malformed digest, unsupported schema/state, score on abstain/error,
determinate result without evidence, absent fallback reason, invalid count, and contradictory declared completeness.

Deferred semantic negatives are explicit: well-shaped wrong digest, conflicting step IDs, arithmetic mismatch, false
complete-coverage claims,
foreign-run evidence, undeclared substitution, and an invalid externally defined scale value. They may pass the
structural schema and must fail a later production validator before ingestion.

## Compatibility baseline

This slice uses main `759eb1b05dc41a50a3153156b9a773d2a1ec7d1c`, including FDK report labels and theme-v14.
It changes no runtime source, dependency, CLI/report behavior, Parquet table, or existing judge/comparison format.
The measured source count remains 3,784 of the 3,785 cap; broader implementation and promotion gates remain intact.
