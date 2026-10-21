# Contributing

## Dev loop

```sh
uv sync                                                        # Python 3.12 and the dev tools
uv run ruff check src tests scripts docs/assets
uv run pyright
uv run pytest -q
python scripts/loc_budget.py
```

Style is `ruff check` (line length 120, as in hangar); there is no formatter gate, so keep code compact and readable.
CI runs the same four jobs (`lint`, `types`, `test`, `loc-budget`) on every PR, plus `assets` and `local-runner`. They need no secrets and no cloud
access: tests use synthetic fixtures only.

## Front-page assets

The README and the docs home page show a recording, a report screenshot and a diagram. They are generated, never hand
made: `uv run --group assets python docs/assets/build.py` (once: `uv run --group assets playwright install chromium`)
runs the real CLI on the fixture experiment and rewrites everything in `docs/assets/`. The `assets` CI job re-runs it
and fails when a committed text asset differs, or when a PNG's source page changed without a re-render
(`docs/assets/sources.sha256`). Change the CLI's output, the report or the fixture, and re-run it in the same PR.

## Docs

The site is built with [zensical](https://zensical.org) from `mkdocs.yml` and `docs/`, as the `docs` workflow does:

```sh
pip install zensical==0.0.71
zensical serve        # http://localhost:8000/flightdeck/, rebuilt on save
zensical build        # into site/ (ignored by git)
```

Two parts of the reference are generated from the code: `docs/cli.md` (every command and option of the Typer app) and
the `flightdeck.parquet/v1` column tables in `docs/contracts.md` (from `src/flightdeck/dataplane/schema.py`). After
changing a command, an option, a help text or a column, run `uv run python scripts/docs_reference.py` and commit the
result; `tests/test_docs_reference.py` fails when they are stale.

## The line budget

v0 is deliberately small: a fixed number of non-blank, non-comment lines under `src/flightdeck/` (`LIMIT` in the script).
`scripts/loc_budget.py` prints the count per area and fails above the limit. Code ported from ai-dlc or hangar and kept
close to its source goes in `src/flightdeck/ported/`, which is reported but not counted; code that adapts it to
flightdeck counts. If a change needs more room, cut something or argue for a higher budget in an ADR (the last one:
[0005](docs/decisions/0005-post-v0-budget.md), which the post-v0 batch amends); don't move code into `ported/` to dodge the count.

## Code map

| Module | What |
| --- | --- |
| `flightdeck.dataplane` | `flightdeck.parquet/v1` tables (runs, spans, events, manifests, grades, test_cases), flatteners from hangar's manifest, OTLP trace and experiment index, DuckDB views; `flightdeck query`. See [Data plane](docs/data-plane.md) |
| `flightdeck.dataplane.ingest` | `flightdeck ingest export\|experiment\|job\|session`: hangar REST or `hangar experiment export` into local Parquet, idempotent, validated against vendored hangar schemas. See [Data plane](docs/data-plane.md#ingest) |
| `flightdeck.stats` | Wilson, pass@k, pass^k, clean-run bound, paired task bootstrap, $ per resolved task, McNemar counts, a power simulation (`simulate_power`); `flightdeck stats compare` with exclusions and saturated tasks. See [Statistics](docs/statistics.md) |
| `flightdeck.report` | `flightdeck report experiment`: the markdown report with a pre-registered verdict, posted as one PR or issue comment. See [Reports](docs/reports.md) |
| `flightdeck.specs` | `flightdeck.spec/v1` behavior specs: YAML predicates over `hangar.trace/v1`, a Python reference evaluator and a DuckDB compiler, the trusted-test rule; `flightdeck spec lint\|test`; the nightly runner over the data plane with ADR `checks:`, change-point alerts and `flightdeck check run\|diff`. Mutation scoring of suites: `flightdeck mutate plan\|run\|score`. See [Behavior specs](docs/behavior-specs.md) |
| `flightdeck.tasks` | Harbor-compatible task directories: load, check and digest them, map them onto a `hangar.experiment/v1` spec; `flightdeck task new\|check\|digest`; `flightdeck task import-aidlc` for ai-dlc evaluation suites; sealed holdout custody, `flightdeck holdout brief\|seal\|score\|canary-scan` ([Holdouts](docs/holdouts.md)); the knowledge gold set, `flightdeck knowledge seal\|score` ([Knowledge evals](docs/knowledge-evals.md)); rubric judges, `flightdeck judge label\|calibrate\|score\|estimate` ([Judges](docs/judges.md)); the semver smoke task in `tasks/smoke/`. See [Tasks](docs/tasks.md) |
| `flightdeck.runners` | The experiment submission client: suite plans to `hangar.experiment/v1` specs, a cost gate, `flightdeck experiment run\|status\|collect`. See [Running experiments](docs/runners.md) |
| `flightdeck.ported` | Code moved in and kept close to its source, outside the line budget: hangar's model-concreteness rule and trace classifier; ai-dlc's local runner, evaluation contracts and suite checks |

v0 is pre-release. flightdeck has to change one real team decision ([#20](https://github.com/Sean-Koval/flightdeck/issues/20))
before anything else, a UI included, gets built.

## Running the smoke tasks locally

The local backend runs tasks in Docker on your machine, with no hangar and no model calls ([docs/runners.md](docs/runners.md#local)).
With Docker running:

```sh
uv run flightdeck experiment run tasks/fixtures/local.yaml --backend local --data /tmp/plane
```

It builds each task's `environment/Dockerfile`, runs the task's solution as the deterministic driver in an isolated
container, grades the collected tree with the task's `tests/` and writes `reward.json` under
`/tmp/plane/raw/<run-set>/<task>/<variant>/<trial>/`, and the rows into the data plane. CI's `local-runner` job runs the
same command; `tests/test_local_runner.py` runs it too and skips, saying why, when Docker is unavailable.

## Never commit team data

The code is public; the team's data is not ([ADR-0002](docs/decisions/0002-public-code-private-data.md)). Never commit
traces, Parquet files, mined regression tasks, sealed holdout material, gold-set answers, judge labels, or reports
that quote team code. Fixtures under `tests/fixtures/` are synthetic and built from hangar's documented schemas.
`tests/test_fixtures_clean.py` rejects fixtures that match the deny-list in `tests/fixtures/deny.txt` (add your
team's repo-URL and person patterns there).

## Boundary

No sandbox, provider or credential code ([ADR-0001](docs/decisions/0001-boundary-with-hangar.md)).
`tests/test_boundary.py` rejects imports of sandbox SDKs outside `ported/` and `runners/local`. Read hangar's runs
only through its versioned interfaces (`hangar.manifest/v1`, `hangar.trace/v1`, `hangar.experiment/v1`) and the
Parquet data plane, never hangar's database or data directory.

## Adding a behavior spec

Behavior specs are YAML predicates over `hangar.trace/v1` ([docs/behavior-specs.md](docs/behavior-specs.md)). Public
examples go in `specs/`; team specs live in the private data repository. Specs that need proof of testing match
trusted `test.run` events, not the agent's own shell `test` op. Loosening or deleting a check needs a second reviewer.

## Adding a task

Public smoke tasks go in `tasks/smoke/<id>/` in the Harbor-compatible layout (`task.toml`, `instruction.md`,
`environment/`, `tests/`; [docs/tasks.md](docs/tasks.md)). Start from `flightdeck task new`, and after changing
hidden tests run `flightdeck task digest --write <dir>` and `flightdeck task check <dir>`. Mined and sealed tasks never
go here.

## Decisions (ADRs)

Copy [docs/decisions/0000-template.md](docs/decisions/0000-template.md) to the next number, open a PR, and get a
review from someone who isn't the author. An ADR may carry a `checks:` block of trace predicates that flightdeck runs
nightly.

## Commits

Conventional commit prefixes (`feat:`, `fix:`, `docs:`, `build:`, `test:`, `refactor:`, `chore:`). Squash merge.

## Design

flightdeck's docs, reports and any future UI use **Airframe**, the suite's design system. Its source of truth is
[Sean-Koval/agent-factory](https://github.com/Sean-Koval/agent-factory) (`airframe/`; docs and component gallery at
<https://sean-koval.github.io/agent-factory/airframe/>). Read `airframe/README.md` and the component READMEs there before
visual work. Use `var(--af-*)` tokens and `af-` classes only, never a color literal (`tests/test_airframe.py` checks
`docs/stylesheets/`); flightdeck's hue is `--af-product-flightdeck`, for its mark, the docs header and the 2px nav marker.
`docs/stylesheets/airframe*.css` are vendored: never edit them; refresh with `sh scripts/sync-airframe.sh theme-vN`.
The generated front-page assets (`docs/assets/*.svg`, `report-comment.html`, the PNGs) are exempt from the
no-literal rule: GitHub renders the README's images outside any stylesheet, so `docs/assets/build.py` writes each
color of the diagram as an Airframe token with its hex fallback (`var(--af-fg, #FFFFFF)`), the terminal recordings
with Airframe's dark values as literals, and the PR-comment page with GitHub's own colors, since it shows how GitHub
renders the report. Change colors in `build.py`, never in its output.
