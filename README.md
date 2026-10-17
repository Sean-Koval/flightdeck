# flightdeck

Flightdeck is the **Judge** in Run / Judge / Govern. [Hangar](https://github.com/Sean-Koval/hangar) runs coding agents
in sandboxes and records what they ran with and what they did. Flightdeck reads those records, judges them with paired
statistics and behavior predicates, owns the task sets and sealed holdouts, and decides how many trials an experiment
needs. The governed workspace governs: one policy decision point, approvals and receipts.

> **Boundary** ([ADR-0001](docs/decisions/0001-boundary-with-hangar.md))
>
> - Flightdeck has **no sandbox code** and holds no sandbox, provider or team credentials.
> - It reads hangar's three versioned interfaces, `hangar.manifest/v1`, `hangar.trace/v1` and
>   `hangar.experiment/v1` ([hangar spec 0014](https://github.com/Sean-Koval/hangar/blob/main/docs/specs/0014-sister-tool-interfaces.md),
>   [hangar `docs/api/`](https://github.com/Sean-Koval/hangar/tree/main/docs/api)), from a GCS → Parquet data plane.
> - It owns **sampling** (how many trials, which tasks, when to stop) and asks hangar to execute trials; hangar
>   executes `task × variant × n` against pinned conditions and does no analysis.
> - The only runner here will be a local Docker runner for fixtures and CI.

## What it does

- **Paired statistics**: paired bootstrap over tasks, Wilson intervals, pass@k and pass^k, dollars per resolved task,
  with exclusions (`infra_error`, cancelled, drift) always printed.
- **Behavior specs**: predicates over `hangar.trace/v1` (tool kinds, shell ops, `hangar.seq` order, paths) that count
  only trusted test runs. Outcome graders come first.
- **Task sets and holdouts**: a Harbor-compatible task format, regression tasks mined from labelled failures, sealed
  holdouts scored once.
- **Reports and promotion evidence**: markdown reports on the PR; the approver is never the author.

Vocabulary (run, turn, trial, check vs grader...) is in [docs/concepts.md](docs/concepts.md); the statistics are
explained once in [docs/statistics.md](docs/statistics.md).

## Status

v0, pre-release. The v0 analysis code stays under **1,500 lines** (`scripts/loc_budget.py`, enforced in CI) and has to
change one real team decision before anything else, a UI included, gets built.

Built so far:

| Module | What |
| --- | --- |
| `flightdeck.dataplane` | `flightdeck.parquet/v1` tables (runs, spans, events, manifests, grades, test_cases), flatteners from hangar's manifest, OTLP trace and experiment index, DuckDB views; `flightdeck query`. See [docs/data-plane.md](docs/data-plane.md) |
| `flightdeck.stats` | Wilson, pass@k, pass^k, clean-run bound, paired task bootstrap, $ per resolved task, McNemar counts, the r1 power simulation. See [docs/statistics.md](docs/statistics.md) |
| `flightdeck.specs` | `flightdeck.spec/v1` behavior specs: YAML predicates over `hangar.trace/v1`, a Python reference evaluator and a DuckDB compiler, the trusted-test rule; `flightdeck spec lint\|test`. See [docs/behavior-specs.md](docs/behavior-specs.md) |
| `flightdeck.tasks` | Harbor-compatible task directories: load, check and digest them, map them onto a `hangar.experiment/v1` spec; `flightdeck task new\|check\|digest`; the semver smoke task in `tasks/smoke/`. See [docs/tasks.md](docs/tasks.md) |

Planned (see the issue tracker): ingest from hangar exports, `flightdeck stats compare` and the report, the nightly spec runner
and the experiment submission client.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```sh
uv sync
uv run flightdeck --help
uv run ruff check src tests scripts
uv run pyright
uv run pytest -q
python scripts/loc_budget.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Team data never goes in this repository
([ADR-0002](docs/decisions/0002-public-code-private-data.md)).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
