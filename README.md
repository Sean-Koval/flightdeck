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
| `flightdeck.dataplane.ingest` | `flightdeck ingest export\|experiment\|job\|session`: hangar REST or `hangar experiment export` into local Parquet, idempotent, validated against vendored hangar schemas. See [docs/data-plane.md](docs/data-plane.md#ingest) |
| `flightdeck.stats` | Wilson, pass@k, pass^k, clean-run bound, paired task bootstrap, $ per resolved task, McNemar counts, the r1 power simulation; `flightdeck stats compare` with exclusions and saturated tasks. See [docs/statistics.md](docs/statistics.md) |
| `flightdeck.report` | `flightdeck report experiment`: the markdown report with a pre-registered verdict, posted as one PR or issue comment. See [docs/reports.md](docs/reports.md) |

Planned (see the issue tracker): the task format, the behavior spec language and the experiment submission client.

## End to end

On the synthetic fixture experiment (12 tasks × 2 variants × 3 trials, with an infrastructure failure, a cancelled,
a drifted and a still-running trial, a truncated trace and an invalid task; no team data):

```sh
uv run python scripts/fixture_export.py /tmp/fd/export          # what `hangar experiment export <id> -o DIR` writes
uv run flightdeck ingest export /tmp/fd/export --out /tmp/fd/plane
uv run flightdeck stats compare job-expdemo --data /tmp/fd/plane                   # resolved, paired by task
uv run flightdeck stats compare job-expdemo --data /tmp/fd/plane --metric cost_usd
uv run flightdeck report experiment job-expdemo --data /tmp/fd/plane \
    --decision /tmp/fd/export/decision.yaml --out /tmp/fd/report.md
GITHUB_TOKEN=... uv run flightdeck report post /tmp/fd/report.md --to owner/repo#123   # one comment, updated in place
```

Against a real hangar: `HANGAR_TOKEN=... flightdeck ingest experiment <id> --hangar https://<your hangar>` (or `ingest
job` / `ingest session`), then the same `stats compare` and `report` with the default data directory
(`~/.flightdeck/data`, or `FLIGHTDECK_DATA_URI`). Keep that directory private (ADR-0002).

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
