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
CI runs the same four jobs (`lint`, `types`, `test`, `loc-budget`) on every PR, plus `assets`. They need no secrets and no cloud
access: tests use synthetic fixtures only.

## Front-page assets

The README and the docs home page show a recording, a report screenshot and a diagram. They are generated, never hand
made: `uv run --group assets python docs/assets/build.py` (once: `uv run --group assets playwright install chromium`)
runs the real CLI on the fixture experiment and rewrites everything in `docs/assets/`. The `assets` CI job re-runs it
and fails when a committed text asset differs, or when a PNG's source page changed without a re-render
(`docs/assets/sources.sha256`). Change the CLI's output, the report or the fixture, and re-run it in the same PR.

## The line budget

v0 is deliberately small: at most **2,500** non-blank, non-comment lines under `src/flightdeck/`.
`scripts/loc_budget.py` prints the count per area and fails above the limit. Code ported from ai-dlc or hangar goes in
`src/flightdeck/ported/`, which is reported but not counted. If a change needs more room, cut something or argue for a
higher budget in an ADR (the last one: [0003](docs/decisions/0003-line-budget.md)); don't move code into `ported/` to dodge the count.

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
