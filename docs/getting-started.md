# Getting started

Six commands on the synthetic fixture experiment, then the same three against a real hangar. Requires
[uv](https://docs.astral.sh/uv/) (it brings Python 3.12) and git; no hangar, no team data.

## Six commands

```sh
git clone https://github.com/Sean-Koval/flightdeck && cd flightdeck
uv run python scripts/fixture_export.py demo/export
uv run flightdeck ingest export demo/export --out demo/plane
uv run flightdeck check run --data demo/plane --date 2025-10-16 \
    --specs specs/examples/team-default.yaml
uv run flightdeck stats compare job-expdemo --data demo/plane
uv run flightdeck report experiment job-expdemo --data demo/plane \
    --decision demo/export/decision.yaml --out demo/report.md
```

The first `uv run` installs the dependencies; after that the six take a few seconds. `scripts/fixture_export.py`
writes what `hangar experiment export <id> -o DIR` writes. `demo/` is ignored by git.

Two more are worth knowing. `--metric cost_usd` (or `tool_calls`, `wall_s`) on `stats compare` compares a process
metric. `GITHUB_TOKEN=... uv run flightdeck report post demo/report.md --to owner/repo#123` posts the report as one
comment and updates it in place.

## What you just saw

The fixture experiment has 12 tasks × 2 variants × 3 trials. It also has one of each case a report must handle. An
infrastructure failure hangar retried; a cancelled, a drifted and a still-running trial; a truncated trace; an
invalid task.

`ingest` turned the export into the Parquet data plane. `check run` scored five behavior specs over the day's units.
`stats compare` paired the two arms by task and printed the difference with its interval, the power line and the
exclusions:

```text
SPEC                       APPLIED  PASSED  FAILED  UNKNOWN
ask-before-delete                —       —       —        1  not applied
edits-stay-in-repo               1       1       0        1
never-push-main                 72      72       0        1
...
5 specs over 73 units: 0 failed, 5 unknown
...
Paired difference candidate − control: +21.2 pp (95% CI +1.5 pp to +43.9 pp;
  task bootstrap, 11 tasks, 63 trials; 3 concordant, 8 discordant tasks).

At 11 paired tasks × 3 trials the minimum detectable lift at 80% power is
  about 35 pp (simulated).
...
Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6.
```

A spec that applied to no unit reads `—` and *not applied*, so it is never mistaken for a pass. The one `unknown`
per spec is the truncated trace. `report` printed the verdict and wrote `demo/report.md`:

```text
candidate is better than control on resolved: +21.2 pp (95% CI +1.5 to +43.9,
  margin −5.0)
wrote demo/report.md (73 lines)
```

The verdict is the report's headline and one of five words ([Concepts](concepts.md)). The fixture's
`decision.yaml` picks it; that file is committed, in a git repository inside the export, before the first trial.

The fixture is built with a large effect. Even so, the interval at 11 paired tasks runs from +1.5 to +43.9 points; a
real harness change usually moves less ([what flightdeck can tell you](statistics.md#what-flightdeck-can-tell-you)).

## Against a real hangar

Ingest an experiment with `HANGAR_TOKEN=... flightdeck ingest experiment <id> --hangar https://<your hangar>` (or
`ingest job`, `ingest session`). Then run the same `check run`, `stats compare` and `report`.

Without `--data` they use `~/.flightdeck/data` (or `FLIGHTDECK_DATA_URI`). Keep that directory private
([ADR-0002](decisions/0002-public-code-private-data.md)).

To plan and submit trials, see [Running experiments](runners.md). The
[team-harness repo](https://github.com/Sean-Koval/team-harness/tree/main/flightdeck) has a suite, a pre-registered
`decision.yaml` and behavior specs to start from; add a task before its `--dry-run` works.

Flightdeck holds no sandbox code and no credentials. It reads hangar's three versioned interfaces and the Parquet
data plane ([ADR-0001](decisions/0001-boundary-with-hangar.md), [Contracts](contracts.md)).

## See also

- [Concepts](concepts.md): the five verdict words, variant, trial, check against grader.
- [Reports](reports.md): the report's anatomy and the pre-registered rule.
- [Running experiments](runners.md): planning and submitting trials to hangar.
- [CLI reference](cli.md): every command and flag; the dev loop is in
  [CONTRIBUTING.md](https://github.com/Sean-Koval/flightdeck/blob/main/CONTRIBUTING.md).
