# Changelog

What each flightdeck release added, newest first. A release is a `vX.Y.Z` tag on main, made with the suite's release
checklist ([agent-factory: Releasing](https://sean-koval.github.io/agent-factory/releases/)). The version lives in
`pyproject.toml` and `src/flightdeck/__init__.py`, and `flightdeck version` prints it.

## Unreleased

- **Data plane:** process metrics and step labels per agent run (`process_metrics`, `step_labels`), ported from
  hangar's `evals/semver` kit onto hangar's trace columns ([Process metrics](https://sean-koval.github.io/flightdeck/process-metrics/), KAN-86).
- **Local backend:** runs only the `deterministic` driver. The unqualified `claude-code@<version>` driver is removed,
  with its run budget, egress proxy and `ANTHROPIC_API_KEY`; model trials run on hangar (KAN-93).
- **Tasks:** `schemas/aidlc/` keeps only `scenario.schema.json`; ai-dlc's profile, event, report and base-image
  contracts, which nothing read, are removed (KAN-93).
- **Docs:** a guide to creating a benchmark and sharing it with your team, with today's commands (KAN-196).

## v0.1.0: the first tagged release

The first pre-1.0 tag. It carries everything merged up to #87: the v0 judge and the work that followed it.

### The judge

- **Data plane:** `flightdeck.parquet/v1` tables and hangar flatteners; `ingest` from hangar's run outbox; a nightly
  outbox compactor on Cloud Run, with weekly team metrics.
- **Stats:** a paired task bootstrap; `compare` prints a verdict, and the markdown report leads with it.
- **Tasks:** a Harbor-compatible task format with digests; ai-dlc's evaluation contracts and `task import-aidlc`;
  sealed holdout custody (`holdout`); knowledge gold-set scoring (`knowledge`).
- **Specs:** the behavior spec language over `hangar.trace/v1`; a nightly spec runner with ADR checks and
  change-point alerts; mutation scoring of behavior suites (`mutate`).
- **Runners:** the experiment client for hangar batch experiments, with model pins and a cost gate; ai-dlc's Docker
  attempt runner as `--backend local`; a trial-result cache and drift sentinel.
- **Judges:** rubric judges with a kappa gate and prediction-powered inference.
- **The evaluation contract** (v1) in `schemas/evaluation/`.

### The product

- The arms are control and candidate, and the report says what each is.
- Terminal readouts, a printed verdict and one-line errors; `--help` lists the three core commands first.
- The docs site and front page on Airframe, now at theme-v15, under the suite's editorial rule.
