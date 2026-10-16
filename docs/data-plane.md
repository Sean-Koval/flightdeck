# Data plane: `flightdeck.parquet/v1`

Flightdeck reads hangar's runs from Parquet files, never from a live hangar (ADR-0001 point 3), so reports work while
hangar's sandbox pools are off. The plan: hangar writes each finished run to a GCS outbox
(`gs://<bucket>/v1/{date}/{run_id}/{manifest.json, trace.otlp.json, grade.json, ...}`), a nightly compactor turns it
into these tables, and DuckDB queries them. Until the outbox exists, the same flatteners run over
`hangar experiment export` and REST exports.

Code: `src/flightdeck/dataplane/` (`schema.py` the tables, `flatten.py` the flatteners, `duck.py` the views).

## Layout and versioning

```
<root>/<table>/dt=YYYY-MM-DD/part-*.parquet      zstd; dt is in the path (hive partitioning), not the file
```

`<root>` is `FLIGHTDECK_DATA_URI`: a local directory or a private `gs://` bucket (ADR-0002). Each file's schema
metadata carries `flightdeck.schema = flightdeck.parquet/v1` and its table name. Within v1, columns are only added;
removing or renaming one is v2. Rows are wide and denormalized: resource attributes (job, session, environment,
person) are copied onto every span row. Every row has `run_id`, `source` (`job`, `session`, `experiment`,
`shadow`) and `dt`.

## Tables

| Table | Grain | From | Notes |
| --- | --- | --- | --- |
| `runs` | one turn (`run_id` = `hangar.run.id`) or one trial (`run_id` = `<experiment>/<task>/<variant>/<n>`) | trace `turn` span + its job's events; experiment `trials[]` | `verify_passed` from the job's `verify` event (`phase = after_turn`) or the trial's `verify.passed`; `diff_files` from `hangar.diff.files`, since shell writes aren't `file.change` events; `merged`/`merged_by` from `pr.merge`; `truncated` from `hangar.export.truncated` |
| `spans` | one OTLP span | trace | Columns for the taxonomy (`kind` = `hangar.kind`, `tool_kind`, `shell_ops`, `seq`, `seq_end`, `file_repo_path`, `mcp_*`, `approval_*`); everything else in `attrs` JSON. Job/session root spans take the job or session id as `run_id` |
| `events` | one span event, except test results | trace | `seq` is null for `steer`/`interrupt` (hangar gives them none yet), so their order is by time only |
| `manifests` | one `hangar.manifest/v1`, deduplicated by `digest` | manifest | `skills_effective` as `name@digest`; `json` keeps the whole manifest |
| `grades` | one grader result for a trial | experiment `trials[].grade` | `data` is the JSON the grader wrote to `$HANGAR_GRADE_OUT` |
| `test_cases` | one `test.run` (its `case_name` is null) or one `test.case` | trace `test.run`/`test.case` events | `trusted` is false for the agent's own in-turn runs; specs that need proof of testing use `trusted and total > 0` |

Nullable now, filled as soon as hangar emits them with no schema change: `harness_digest`, `environment_digest`,
`knowledge_snapshot`, `grader_digest`, and an `infra_error` value of `outcome`.

## Decoding

OTLP/JSON per opentelemetry-proto 1.11.1: `intValue` is a decimal string, lists are `arrayValue.values`,
`kvlistValue` becomes a dict. Unknown attributes are kept in `attrs`, never an error (hangar adds fields within v1).
A different `hangar.trace.schema`, manifest or experiment schema is refused. Hangar redacts every export; the
flatteners also mask anything that still looks like a credential (private keys, GitHub, Anthropic/OpenAI, AWS and
Slack tokens) as `***`, and clip event text to 2,000 characters.

## Querying

```sh
flightdeck query "select variant, count(*) from runs join grades using (run_id) group by 1" --data ./plane
```

`duck.connect(uri)` registers one view per table that has files (`read_parquet(..., hive_partitioning=true,
union_by_name=true)`). For `gs://` it loads DuckDB's `httpfs`; the caller supplies a DuckDB GCS secret (HMAC or
credential chain), since flightdeck holds no credentials.

## Size

About 1.5 MiB of OTLP per run gives roughly 1.5 GiB a month as zstd Parquet at the team's volume. DuckDB over Parquet
is enough until about 1 TB.
