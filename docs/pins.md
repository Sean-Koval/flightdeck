# Pins and the cost gate

Before [an experiment](runners.md) is sent to hangar, flightdeck checks its pins and projects its cost. A plan that
fails either is refused.

## Models

Every variant names a concrete model id. Three kinds of name are refused before anything is sent, because the provider
can move them between two trials. They are a policy (`frontier`, `balanced`, `frontier@openai`), an alias (`*-latest`,
OpenRouter's `~…`) and a family name without a version (`opus`, `sonnet`, `gpt-5`, `claude-opus-5`).

The rule is hangar's `modelpolicy.is_concrete` ([hangar#167](https://github.com/Sean-Koval/hangar/issues/167)), ported
to `src/flightdeck/ported/modelpolicy.py` and checked against hangar's own test table
(`tests/fixtures/hangar/model_concreteness.json`). A concrete id names a version or a date: `claude-opus-5-5`,
`claude-opus-4-5-20251101`, `gpt-6.1-sol`, `gpt-4o-2024-08-06`, `gemini-3.8-flash`,
`openrouter/anthropic/claude-opus-5.5`. `run`, `status` and `ingest` share the rule.

flightdeck has no provider model list, so it decides by shape only. An id hangar accepts because its provider lists it
(`claude-opus-5`) needs `--allow-model ID`. `hangar env list` shows what a policy resolves to today.

## Harness versions

`harness@version` must be the version hangar's lock pins (`harnesses.lock.yaml`). Otherwise hangar refuses the
experiment and `run` prints hangar's message.

A variant that names a harness lock (`harness_lock: name@sha256:...`, accepted by hangar since
[hangar#135](https://github.com/Sean-Koval/hangar/issues/135)) is refused here for now: `harness_lock isn't a hangar
variant field`. See [Contracts](contracts.md#the-vendored-schemas).

## After the start

`status` checks the index's pins. Every task has a `base_sha`; no variant's model was pinned to an alias; variants
that asked for the same model got the same id. Any of these is a pin problem, and `status` exits 1.

## The cost gate

Before submitting, `run` projects the plan's cost. Each task's historical median `cost_usd` per trial comes from the
data plane's `runs` (`--data` / `FLIGHTDECK_DATA_URI`), else `--assume` (default $3.00); times trials, times variants.

`run` refuses the plan when the projection is over `--max-usd`, over the team's remaining monthly budget, or over the
author's remaining sub-cap. The refusal names the cap and its file. Spend so far is this calendar month's experiment
`cost_usd` in `runs`: the team's, and the author's where `person` is the author.

The gate is advisory and early. hangar's own budgets (per trial, per experiment, daily) still enforce.

`budgets.yaml` is team configuration and lives in the private data repository, not here. `run` finds it through
`--budgets`, `FLIGHTDECK_BUDGETS`, else `./budgets.yaml` when present:

```yaml
month_usd: 1500       # the team's monthly eval budget
authors:              # per-author monthly sub-caps; with any set, runs must name --author (or FLIGHTDECK_AUTHOR)
  dev-a: 300
  dev-b: 300
```
