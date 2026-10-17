<div class="af-hero" markdown>
<span class="af-eyebrow">Agent factory · Judge plane</span>

# Judge coding-agent runs with evidence, not vibes

<p class="af-lede">Flightdeck reads the runs hangar records and judges them with paired statistics and behavior predicates. It owns the task sets, the sealed holdouts and the sampling plan, so a team can tell whether a harness change actually helped before it ships.</p>

[Get started](concepts.md){ .md-button .md-button--primary } [Suite overview](https://sean-koval.github.io/agent-factory/){ .md-button }
</div>

## What it does

- **Paired statistics**: paired bootstrap over tasks, Wilson intervals, pass@k and pass^k, dollars per resolved task,
  with exclusions (`infra_error`, cancelled, drift) always printed. See [Statistics](statistics.md).
- **Behavior specs**: predicates over `hangar.trace/v1` (tool kinds, shell ops, order, paths) that count only trusted
  test runs. Outcome graders come first.
- **Task sets and holdouts**: a Harbor-compatible task format, regression tasks mined from labelled failures, sealed
  holdouts scored once.
- **Reports and promotion evidence**: markdown reports on the PR; the approver is never the author.
- **Data plane**: hangar's manifests, traces and experiment index flattened into `flightdeck.parquet/v1` tables with
  DuckDB views. See [Data plane](data-plane.md).

## How it fits the suite

The agent factory splits the work into Run, Judge and Govern. [Hangar](https://github.com/Sean-Koval/hangar) runs
coding agents in sandboxes and records what they ran with and what they did. Flightdeck judges: it reads hangar's
versioned interfaces (`hangar.manifest/v1`, `hangar.trace/v1`, `hangar.experiment/v1`), decides how many trials an
experiment needs, and asks hangar to execute them. It holds no sandbox code and no credentials
([ADR-0001](decisions/0001-boundary-with-hangar.md)). The governed workspace governs: one policy decision point,
approvals and receipts.

The [suite architecture](https://sean-koval.github.io/agent-factory/architecture/) shows how the pieces connect.

## Where to go next

- [Concepts](concepts.md): the vocabulary (run, turn, trial, check vs grader).
- [Statistics](statistics.md): why comparisons pair by task, the functions, and the rules every report follows.
- [Data plane](data-plane.md): the Parquet tables and `flightdeck query`.
- [Decisions](decisions/0001-boundary-with-hangar.md): the boundary with hangar and the public-code, private-data split.
- [Source on GitHub](https://github.com/Sean-Koval/flightdeck): development setup and contributing.
