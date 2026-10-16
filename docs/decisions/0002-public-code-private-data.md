# 0002: Public code, private data

Status: Accepted · Oct 15, 2026

## Context

Flightdeck's code is open source. Its inputs are not: team traces quote team code, prompts and tool output; mined
regression tasks are team repositories at a commit; sealed holdouts are worthless once anyone (or any model's
training set) has seen them; judge labels and gold-set answers are team knowledge. Hangar redacts secrets on every
export (0014 §6), but redaction doesn't make team code public. The split has to be fixed before the first byte of data
lands, because history is hard to rewrite once a public repo has it.

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. Private repo for everything | Code and data together, private | No split to maintain | Loses outside review and reuse of the code; nothing about the code is secret |
| B. Public repo, data in it under a gitignored path | One checkout | Simple local setup | One `git add -A` away from publishing team data |
| C. Public code, private data store and companion repo | Data in a private bucket and a private repo, located by environment variables | The public repo never has a path to team data. CI stays secret-free | Two places to look; a little configuration |

## Decision

Choose C.

- **Public** (this repo): code, schemas, public smoke tasks, example specs, synthetic test fixtures.
- **Private**: team traces and Parquet, mined regression tasks, sealed holdouts, gold-set answers, judge labels, and
  reports that quote team code. They live in a private GCS bucket (`gs://<team>-flightdeck/`) and a private companion
  repository (`Sean-Koval/flightdeck-data`, created with the holdout-custody work).
- Configuration locates them by environment variable only: `FLIGHTDECK_DATA_URI`, `FLIGHTDECK_TASKS_REPO`. No team
  bucket or repo name is committed here.
- CI uses only synthetic fixtures and needs no secrets.

## Consequences

- `.gitignore` excludes `data/` and `*.parquet` outside `tests/fixtures/`.
- `tests/test_fixtures_clean.py` fails if a fixture matches the deny-list (`tests/fixtures/deny.txt`: team repo URLs,
  person names), so real data can't slip in as a fixture.
- Reports posted to public places (this repo's PRs) must not quote team code; reports about team work post where the
  team's code lives.
- If the repo must start private for policy reasons, everything here still applies; flip it public once this split is
  in place.
