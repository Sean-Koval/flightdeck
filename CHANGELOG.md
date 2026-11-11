# Changelog

What each flightdeck release added, newest first. A release is a `vX.Y.Z` tag on main, made with the suite's release
checklist ([agent-factory: Releasing](https://sean-koval.github.io/agent-factory/releases/)). The version lives in
`pyproject.toml` and `src/flightdeck/__init__.py`, and `flightdeck version` prints it.

## Unreleased

- **GitHub Enterprise:** `ingest github` reads `GITHUB_API_URL`, as `report post` already did, so `prs` fills from a GitHub Enterprise Server host (KAN-357).
- **Ingest:** `flightdeck ingest file TRACE.json [--manifest M.json]` loads a saved job or session trace (an MCP
  client's `hangar://jobs/<id>/trace`, an offline `hangar.trace/v1` export) with no hangar URL or token. It writes
  the rows `ingest job` or `ingest session` writes and replaces them by `run_id`; a manifest that misses hangar's
  schema warns. Without a manifest, ids come from the trace: a turn with no run id is `<session>/turn/<n>`, and a
  trace with no turns is one run ([Data plane: ingest](https://sean-koval.github.io/flightdeck/data-plane/#ingest), KAN-312).
- **Data plane:** trace ingest fills `runs.harness_digest` and `environment_digest` from the turn span, and
  `job_state` and the new `job_reason` from the job span. The new `runs.cache_write_tokens` comes from
  `gen_ai.usage.cache_write.input_tokens`, or the outbox's `usage.cache_write_tokens`. Still `flightdeck.parquet/v1`;
  the outbox wins where both have a value, and per-call usage on tool spans stays in `spans.attrs` (KAN-309).
- **Budget:** the counted-line limit is 3,850, up from 3,785, so the step-label and process-integrity work fit
  together ([ADR 0009](https://sean-koval.github.io/flightdeck/decisions/0009-label-and-integrity-budget/), KAN-175).
- **Behavior specs:** opt-in `conservative-v1` distinguishes witnessed forbidden tools from missing evidence on truncated exports. Legacy defaults stay unchanged; stored results and alerts retain policy identity.

- **Integrity:** unknown tool results no longer complete repair loops. Duplicate trace rows do not inflate process counts; conflicting run or span identities exclude the affected aggregate (KAN-175).
- **Data plane:** initialize UTC after DuckDB loads its built-in extensions, fixing local connections with the locked DuckDB release.

- **Metrics:** `flightdeck metrics labels` scores step labels against a hand-labelled gold set: first-label accuracy,
  per-label precision and recall, and the misses; CI scores a synthetic set ([Label gold sets](https://sean-koval.github.io/flightdeck/label-gold-sets/), KAN-273).
- **Metrics:** step labels count what a call does, not the first thing it names. Version and help probes are no
  longer test runs; tests in loops, behind `uv run` flags and in CI scripts are. A call has every label it earns
  (`labels`), with a new `setup` label and more shell edits (`sed -i`, `git apply`, python rewrites), so a call
  that writes and tests counts as an edit and a test run ([Process metrics](https://sean-koval.github.io/flightdeck/process-metrics/), KAN-272).
- **Metrics:** looking around is `explore`, not `other` or `verify`: `which`, `command -v`, `--version`, `pip list`
  and `python -c` that only prints where a module lives. `git init` is `vcs`. Found in an Antigravity run (KAN-273).
- **Metrics:** code survival at merge and human-edit share, from hangar's outcome labels on `pr.merge`, as the
  `pr_outcomes` view and two weekly rows beside the revert rate ([Outcome labels](https://sean-koval.github.io/flightdeck/outcome-labels/), KAN-232).
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
