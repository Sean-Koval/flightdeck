# What's shipped

Each feature's status, and the page that explains it. *Shipped* means it runs today. *Code merged* means the code is
in, and its issue stays open until it has run for real.

| Feature | Status | Docs |
| --- | --- | --- |
| **Ingest**: hangar REST or `hangar experiment export` into the Parquet data plane, idempotent; `flightdeck query` over it | Shipped ([#7](https://github.com/Sean-Koval/flightdeck/issues/7)) | [Data plane](data-plane.md) |
| **Compactor**: hangar's GCS outbox into the data plane, nightly on Cloud Run | Shipped ([#5](https://github.com/Sean-Koval/flightdeck/issues/5)); needs hangar's outbox on (`HANGAR_OUTBOX_URL`) | [Data plane](data-plane.md#compactor) |
| **Paired statistics**: task bootstrap, Wilson, pass@k and pass^k, $ per resolved task, a power estimate; exclusions always printed | Shipped ([#8](https://github.com/Sean-Koval/flightdeck/issues/8)) | [Statistics](statistics.md) |
| **Behavior specs**: YAML predicates over traces that count only trusted test runs | Shipped ([#14](https://github.com/Sean-Koval/flightdeck/issues/14)) | [Behavior specs](behavior-specs.md) |
| **Nightly checks**: `check run` over a day of the data plane, ADR `checks:`, change-point alerts | Code merged; [#15](https://github.com/Sean-Koval/flightdeck/issues/15) open until it is scheduled with a real team ADR | [ADR checks](adr-checks.md) |
| **Reports**: the pre-registered verdict, pins, outcome, process, cost and spec pass rates, as one PR comment | Shipped ([#9](https://github.com/Sean-Koval/flightdeck/issues/9)) | [Reports](reports.md) |
| **Experiments**: suites of Harbor-compatible tasks submitted to hangar with concrete model pins and a cost gate; a local Docker backend for fixtures and CI | Shipped ([#11](https://github.com/Sean-Koval/flightdeck/issues/11), [#18](https://github.com/Sean-Koval/flightdeck/issues/18)); `harness_lock` variants not yet | [Running experiments](runners.md), [Tasks](tasks.md) |
| **Weekly metrics**: the team's weekly scorecard, one SQL definition over Parquet, as JSON for hangar's digest | Shipped ([#6](https://github.com/Sean-Koval/flightdeck/issues/6)) | [Weekly metrics](metrics.md) |
| **Judges**: rubric judges used only once calibrated against people (κ ≥ 0.6); estimates by prediction-powered inference | Shipped ([#27](https://github.com/Sean-Koval/flightdeck/issues/27)) | [Judges](judges.md) |
| **Sealed holdouts**: hash-manifested, canaried task sets written blind and scored once | Code merged; [#13](https://github.com/Sean-Koval/flightdeck/issues/13) open until the first set is sealed | [Holdouts](holdouts.md) |
| **Knowledge evals**: a 40-question gold set scored on correctness and citation validity | Code merged; [#21](https://github.com/Sean-Koval/flightdeck/issues/21) open until the gold set is written and scored | [Knowledge evals](knowledge-evals.md) |
| **Trial cache**: reuse trials whose inputs haven't changed; a nightly drift sentinel | Code merged; [#24](https://github.com/Sean-Koval/flightdeck/issues/24) open until the sentinel runs nightly | [The trial cache](cache.md) |
| **Mutation scoring**: remove one harness component at a time and check that a grader or spec notices | Code merged; [#16](https://github.com/Sean-Koval/flightdeck/issues/16) open until the first live run | [Mutation scoring](mutation-scoring.md) |
| **Small by design**: 3,875 counted lines of analysis code, enforced in CI | Nearly full; the next growth needs a cut | [ADR-0010](decisions/0010-default-specs-budget.md) |

Every command and flag is in the [CLI reference](cli.md). What flightdeck reads, writes and pins is in
[Contracts](contracts.md).

## Next

- [Getting started](getting-started.md): the shipped path, in six commands on the fixture.
- [Concepts](concepts.md): the vocabulary these features use.
- [Decisions](decisions/index.md): why flightdeck is this small, and where its boundary is.
