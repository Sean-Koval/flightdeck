# 0001: Hangar runs, flightdeck judges, the governed workspace (now Tower) governs

Status: Accepted · Oct 15, 2026

## Context

Hangar's spec 0014 defines the boundary from hangar's side: hangar is the runtime and control plane and *emits* data;
"a sister tool, in a separate repository, *interprets* runs", and hangar has "no spec language, no evaluators, no
rubrics, no effect sizes, no leaderboards and no visualization" (hangar `docs/specs/0014-sister-tool-interfaces.md`
§1). Hangar's three versioned interfaces are `hangar.manifest/v1` (`docs/api/manifest.schema.json`),
`hangar.trace/v1` (`docs/api/traces.md`) and `hangar.experiment/v1` (`docs/api/experiment.schema.json`).

Flightdeck has to state the same boundary from its side, or sandbox code drifts in here and analysis code drifts into
hangar. Two pressures make that likely: experiments need trials executed (tempting a runner here), and hangar holds
the data (tempting analysis there). Hangar's sandbox pools are also off nine hours a day, so anything that reads a
live hangar to judge runs breaks overnight.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Analysis inside hangar | Specs, stats and reports as hangar modules | One repo, one deploy | Breaks 0014 §1. Analysis gets hangar's credentials and trust boundary. Hangar's MCP surface is at its cap |
| B. Flightdeck runs its own sandboxes | A second runtime here, for evals | No dependency on hangar's scheduling | Two sandbox fleets, two credential stores, two isolation stories to audit |
| C. Interfaces-only judge | Flightdeck reads versioned interfaces and Parquet, owns sampling, asks hangar to execute | Each repo has one job. Works while the cluster sleeps. Contracts stay out of reach of what they judge | Depends on hangar shipping capture work (outbox, digests, `infra_error`) |

## Decision

Choose C.

1. Hangar runs. Flightdeck judges. The governed workspace (now Tower) governs.
2. Flightdeck never holds sandbox, provider or team credentials.
3. Flightdeck reads only hangar's versioned interfaces and the Parquet data plane, never hangar's SQLite or data
   directory. This holds wherever the GCS → Parquet compactor ends up living.
4. Flightdeck owns sampling (how many trials, which tasks, when to stop); hangar executes `task × variant × n`
   against pinned conditions.
5. Behavior contracts live here, keyed by harness *name*, outside anything a harness optimizer can edit.
6. Grading is outcome-first: clean-sandbox graders, then trace predicates, then judges (calibrated, through
   prediction-powered inference).
7. Flightdeck gets its own MCP server later and talks to hangar over REST, adding no tools to hangar's capped MCP list
   (0014 §4 "Access").

The one exception to point 2's spirit is a local Docker runner (ported from ai-dlc) used only for fixtures and CI,
under `src/flightdeck/runners/local` or `ported/`.

## Consequences

- `tests/test_boundary.py` fails on sandbox-SDK imports (`docker`, `kubernetes`, `e2b`) outside those two places.
- Hangar must keep its interfaces additive within v1; flightdeck's flatteners must tolerate unknown fields.
- Flightdeck's v0 can only judge what hangar captures. Missing fields (`harness_digest`, `environment_digest`,
  `infra_error`, grader digests) are nullable columns until hangar emits them.
- This supersedes the earlier panel papers' "clean room" framing: every project is work tooling, and the boundary is
  architectural, not legal.
