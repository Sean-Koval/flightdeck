# Plan: preserve process-evidence integrity

This bounded KAN-175 slice fixes existing analysis behavior on synthetic traces. It does not implement causal credit or complete KAN-175/KAN-176.

## Scope and choices

Use the existing trace flattener, Parquet tables and SQL views. Do not introduce an evaluator service or hide runtime validation in tests.
Keep the source cap and counted total unchanged. Preserve the KAN-31 decision gate and ADR 0007's proposed status.

1. Reproduce the DuckDB connection failure with a local empty data plane. Initialize UTC after connection creation, without adding counted lines.
2. Establish the complete test-suite baseline, recording Docker skips separately.
3. Add failing integration tests for unknown test outcomes and duplicated or conflicting span evidence. Keep known failures separate from unknown results.
4. Fix the existing SQL views minimally. Retain raw evidence; never infer success or causal reward from a process label.
5. Document later run/task-family split controls and unchanged-incumbent, raw-history and explicit-rule baselines. Do not execute transfer evaluation.
6. Run lint, types, all tests and the unchanged line-budget check. Review the diff independently and prepare a draft PR.

## Review focus

- An unknown tool result must not finish a repair loop or suppress a later known pass.
- Identical copied evidence must not multiply counts. Conflicting evidence must not become a trusted aggregate.
- Run and source boundaries must prevent one run's edit or success completing another run's chain.
- A tool call labelled `test` is not a trusted test outcome. Neither one establishes causal contribution.
- Synthetic integrity results cannot claim generalization, real-trace quality or KAN-25 human gold labels.

## Verification boundaries

No model calls, paid workers, private traces, production deployment or changed permissions. Dependency setup is separate from the offline test matrix.
The EvolveIPI permission check and combined KAN-175/KAN-176 preflight remain separate work. Passing these tests does not complete either gate.
