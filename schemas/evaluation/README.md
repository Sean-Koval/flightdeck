# Evaluation evidence artifact, v1 revision 1

`evaluation.schema.json` is a **structural design contract**, not a runtime API. No Flightdeck command ingests it,
no report or comparison reads its scores, and validating a document does not authorize training or promotion.
See [ADR 0007](../../docs/decisions/0007-evaluator-contract-foundation.md) for the bounded implementation exception.

## Envelope

Every record declares `schema: flightdeck.evaluation/v1` and `schema_revision: 1`. Core objects reject unknown fields;
optional `extensions` accepts namespaced keys such as `example.review_state`. Extensions do not change core semantics.

| Field | Meaning |
| --- | --- |
| `evaluation_id` | Stable identity for this assessment artifact, not an approval ID |
| `subject` | Run identity, source, scope, and attempt |
| `input` | Exact evaluated bytes, format, and declared source/input/redaction completeness; null if unavailable |
| `requested_evaluator` | Intended implementation and configuration pins |
| `actual_evaluator` | Effective implementation and configuration pins; null if unavailable |
| `specification` | Rubric/test specification ID, version, and exact file-byte digest; null if unavailable |
| `execution` | `completed`, explicit `fallback` with reason, or `error` with reason |
| `coverage` | Selection digest, scope, eligible denominator, attempted count, and determinate count |
| `assessments` | Independent outcome and process assessments |
| `steps` | Assessments for attempted steps, identified by stable step IDs |
| `calibration` | Optional calibration artifact, explicitly null when unavailable; not an approval |

All assessments in an artifact use its one actual evaluator. Mixed evaluators require separate artifacts. `kind` is
an open identifier so additional evaluator families do not need a core enum change. Known `process_judge` and
`learned_policy` kinds require `model_id`; other model-based kinds must also declare their model identity by convention.
An implementation digest pins code, and a configuration digest pins effective settings; neither replaces the model ID.

`specification.digest_method` is `artifact_bytes_sha256`: hash the exact specification file bytes. This is **not**
the existing `judges.digest` selected-field hash. A future adapter must preserve both identities and verify the mapping,
not relabel an existing judge digest as a file-byte digest.

## Evidence and scores

References contain an opaque `artifact:` locator and a lowercase `sha256:` content digest, plus optional trace/span/step
selectors. They deliberately have no raw URL or inline rationale field. Actual inputs and rationale belong in private,
access-controlled storage; public fixtures contain synthetic identifiers only. The locator grammar is not a privacy
filter: identifiers, extensions, and metadata can still leak information if producers misuse them. Validate/redact those
before publication. A digest does not prove storage is immutable or that the referenced content was evaluated.

Each assessment has a status and evidence array. `pass`, `fail`, and `scored` require at least one reference. `scored`
requires a score; pass/fail can omit it. `abstain`, `error`, and `not_applicable` require a machine-readable reason and
forbid scores. Binary scores are 0 or 1, with pass=1 and fail=0. Other scores specify ordinal/continuous scale, unit,
and direction. Their allowed range/levels come from the pinned specification, not an assumed universal 0–1 reward.
Infrastructure failure and absent probabilities are not failed task assessments. A verified task failure can be zero;
a missing measurement cannot. Missing input, evaluator, or specification pins forbid all determinate assessments.

## Coverage and incomplete traces

`selection_digest` identifies the exact selection artifact defining the policy and eligible step IDs for the pinned
input and scope. The eligible set must be fixed independently of observed scores; later adapters must resolve and
verify it. Counts are step counts, not confidence values. A pass and an abstention over two eligible steps have one
determinate step, two attempted steps, and two eligible steps: 50% determinate coverage, not 100%.

- `complete`: every eligible step is determinate: `determinate_steps == attempted_steps == eligible_steps > 0`, with
  exactly one determinate step entry per eligible ID in the pinned selection. It also requires complete evaluated input
  and no redaction. Run scope requires complete source capture; selection scope may evaluate an explicit subset of a
  partial source. Equality, step identity, and membership require the future semantic validator, not this schema.
- `partial`: known positive denominator. Process may fail on explicit evidence or abstain/error, but has no aggregate score.
- `unknown`: unknown eligible denominator represented by null, not zero; the same process restrictions as partial apply.
- `not_applicable`: all three counts are zero, steps are empty, and the process assessment is not applicable.

Outcome remains independent: outcome pass/process fail or outcome pass/process abstain can be valid. An execution error
forbids all determinate assessments and requires zero determinate steps. Declared complete coverage does not prove it:
schema conformance cannot compare these counters with each other or with the actual input. Current trace clipping must
not be silently called complete. Unknown source/input/redaction flags prevent run-wide complete claims.

## Deliberate limits before runtime adoption

A counted production validator is still required to reject well-shaped but false evidence, foreign-run references,
duplicate step IDs with different assessments, arithmetic inconsistencies, false complete-coverage claims (including
one determinate step over two eligible steps), unannounced actual/requested substitutions,
nonfinite or duplicate-key JSON, and values outside a pinned rubric's range. It must establish exact input completeness,
selection membership and denominator, calibration scope, and access controls. The conformance tests explicitly include
examples that **pass this schema but fail those intended semantic requirements**; they are not safe-to-use examples.

This artifact has no reward, confidence-to-score conversion, evaluator approval, candidate decision, or promotion field.
Training eligibility and execution need a separate design that excludes invalid/contaminated tasks, infrastructure
errors, missing token probabilities, and insufficient evidence. Schema validation alone is never sufficient.

## Deterministic conformance tests

```sh
uv sync --locked
uv run pytest -q tests/test_evaluation_contract.py
uv run ruff check src tests scripts docs/assets
uv run pyright
uv run pytest -q
python scripts/loc_budget.py
```

These tests use the existing `jsonschema` dependency and synthetic fixtures under `tests/fixtures/evaluation/`. They
make no network/model calls. The schema adds no production validator, dependency, command, schema migration, or source
budget exemption. Revision 1 is a closed experimental shape; additions require a new revision and a deliberate reader
compatibility policy rather than silently changing the existing Parquet interfaces' guarantees.
