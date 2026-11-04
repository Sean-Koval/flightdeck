# What does the process-integrity check establish?

This bounded KAN-175 slice checks existing trace-to-label-to-metric behavior, not causal credit. It does not complete KAN-175 or KAN-176.
Public inputs are synthetic. There are no human gold labels, private traces, model calls or harness changes.

## Reproduced defects

The pre-change SQL accepted five misleading results:

| Synthetic mutation | Before | Required behavior |
| --- | --- | --- |
| Unknown test after failure and edit | One completed repair | No completed repair |
| Copied tool span | 18 labels for 17 calls | Count the identical copy once |
| Copied export | Two rows, each with 34 calls and two trusted tests | One row, 17 calls and one trusted test |
| Conflicting content for one span identity | A process aggregate | Exclude that run's aggregate |
| Conflicting truncation flags | Favorable untruncated copy selected | Exclude the entire run/source identity |

The tests traverse the real flattener, local Parquet tables and SQL views. They also check source/run isolation and label-versus-trusted-outcome separation.
Existing semver conformance tests preserve the explicit-rule baseline. Unknown results do not prevent a later known success from completing a repair.

Exact duplicates are collapsed only for analysis. Raw rows remain available for diagnosis.
Conflicts use `(run_id, source, trace_id, span_id)`, not names or output similarity. Conflicting run metadata also excludes the whole identity. Exclusion affects only the conflicting run and source.

## Connection prerequisite

The locked DuckDB version is 1.4.5. Setting UTC during connection creation failed before its built-in ICU extension loaded.
The existing data-plane connection now sets UTC immediately after creation. No dependency changes are needed.
Import consolidation offsets the added statement: counted Python source remains 3,719 of 3,785 lines.

## Reproduce

```sh
uv sync --frozen
uv run pytest -q tests/test_process_integrity.py tests/test_process_metrics.py
uv run ruff check src tests scripts docs/assets
uv run pyright
uv run pytest -q
python scripts/loc_budget.py
```

Dependency setup is not part of the offline fixture run. Docker integration tests require Docker and are reported separately when unavailable.

## Observed on November 3, 2026

The focused check passed 16 tests: 7.019 CPU-seconds and 4.618 seconds elapsed on Linux x86_64, Python 3.12.14.

The full suite passed 351 tests and 254 subtests. Two Docker tests skipped; the existing cache test emitted two NumPy warnings.
Lint, types and the unchanged source budget passed. Independent review reproduced the truncation conflict before its fix and verified the final focused checks.

No model was invoked. Tests used local synthetic inputs. Syscall tracing was denied by the sandbox, so zero network calls were not independently instrumented.

## Not established

- A `test` label is an activity classification, not a verified outcome. A trusted outcome still does not identify which action caused success.
- Duplicate handling does not authenticate producer assertions or detect missing spans, hidden clipping, forged provenance or all conflicting grader events.
- Process counts do not establish authorization, information necessity, wrong-agent credit, learning gains or transfer.
- The full repair-chain, handoff, dependency-intervention and negative-control matrix remains outstanding under KAN-175/KAN-176.
- A missing aggregate is an exclusion, not a zero reward. Downstream users must account for excluded runs separately.

The combined KAN-175/KAN-176 preflight still requires zero model/network calls and under five CPU-minutes for its entire matrix.
This smaller regression check cannot certify that gate.

[The later evaluation protocol](trace-learning-protocol.md) preserves leakage controls and simple baselines without enabling a production evaluator.
ADR 0007 remains Proposed. The KAN-31 cost-primary decision gate and EvolveIPI permission-only scope remain unchanged.
