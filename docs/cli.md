# CLI reference

Every command, argument and option of `flightdeck`, generated from the code by `uv run python scripts/docs_reference.py` (`tests/test_docs_reference.py` fails when this page is stale). Every command also takes `--help`. Options with an environment variable read it when the option isn't given; an option without a description here is explained in its group's guide.

| Command | What it does | Subcommands | Guide |
| --- | --- | --- | --- |
| **Judge a change** | | | |
| [`ingest`](#flightdeck-ingest) | Pull hangar runs and experiments into the data plane. | [`export`](#flightdeck-ingest-export), [`experiment`](#flightdeck-ingest-experiment), [`job`](#flightdeck-ingest-job), [`session`](#flightdeck-ingest-session), [`github`](#flightdeck-ingest-github) | [Data plane: ingest](data-plane.md#ingest) |
| [`stats`](#flightdeck-stats) | Compare the arms of an experiment, paired by task. | [`compare`](#flightdeck-stats-compare) | [Statistics](statistics.md#flightdeck-stats-compare) |
| [`report`](#flightdeck-report) | The verdict as a report, posted on the pull request. | [`experiment`](#flightdeck-report-experiment), [`post`](#flightdeck-report-post) | [Reports](reports.md) |
| **Run experiments** | | | |
| [`experiment`](#flightdeck-experiment) | Trials on hangar: submit a suite, follow it, collect it. | [`run`](#flightdeck-experiment-run), [`status`](#flightdeck-experiment-status), [`collect`](#flightdeck-experiment-collect) | [Running experiments](runners.md) |
| [`task`](#flightdeck-task) | Harbor-compatible task directories: write, check, digest. | [`new`](#flightdeck-task-new), [`check`](#flightdeck-task-check), [`digest`](#flightdeck-task-digest), [`import-aidlc`](#flightdeck-task-import-aidlc) | [Tasks](tasks.md) |
| [`cache`](#flightdeck-cache) | The trial-result cache: drop entries, check the drift sentinel. | [`drop`](#flightdeck-cache-drop), [`sentinel`](#flightdeck-cache-sentinel) | [Running experiments: cache](runners.md#cache) |
| **Behavior** | | | |
| [`spec`](#flightdeck-spec) | Behavior specs over traces: lint them, test them on an export. | [`lint`](#flightdeck-spec-lint), [`test`](#flightdeck-spec-test) | [Behavior specs](behavior-specs.md) |
| [`check`](#flightdeck-check) | Run the behavior specs and ADR checks over the data plane; label edits to them. | [`run`](#flightdeck-check-run), [`diff`](#flightdeck-check-diff) | [Behavior specs: nightly runner](behavior-specs.md#adr-checks-and-the-nightly-runner) |
| [`mutate`](#flightdeck-mutate) | Mutation scoring: mutate the harness, check the suite catches each mutant. | [`plan`](#flightdeck-mutate-plan), [`run`](#flightdeck-mutate-run), [`score`](#flightdeck-mutate-score) | [Behavior specs: mutation scoring](behavior-specs.md#mutation-scoring) |
| **Sealed sets** | | | |
| [`holdout`](#flightdeck-holdout) | Sealed holdouts: briefs, seal, canary scan, score once. | [`brief`](#flightdeck-holdout-brief), [`seal`](#flightdeck-holdout-seal), [`score`](#flightdeck-holdout-score), [`canary-scan`](#flightdeck-holdout-canary-scan) | [Holdouts](holdouts.md) |
| [`knowledge`](#flightdeck-knowledge) | The knowledge gold set: seal it, score arms on correctness and citations. | [`seal`](#flightdeck-knowledge-seal), [`score`](#flightdeck-knowledge-score) | [Knowledge evals](knowledge-evals.md) |
| [`judge`](#flightdeck-judge) | Rubric judges: label sheets, calibration, judge labels, corrected estimates. | [`label`](#flightdeck-judge-label), [`calibrate`](#flightdeck-judge-calibrate), [`score`](#flightdeck-judge-score), [`estimate`](#flightdeck-judge-estimate) | [Judges](judges.md) |
| **Data plane** | | | |
| [`metrics`](#flightdeck-metrics) | Weekly team metrics over the data plane. | [`weekly`](#flightdeck-metrics-weekly) | [Weekly metrics](metrics.md) |
| [`compact`](#flightdeck-compact) | Compact hangar's outbox into the data plane (nightly on Cloud Run: deploy/compactor/). | — | [Data plane: compactor](data-plane.md#compactor) |
| [`query`](#flightdeck-query) | Run SQL over the data plane's tables (runs, spans, events, manifests, grades, test_cases); tab-separated. | — | [Data plane: querying](data-plane.md#querying) |
| **About** | | | |
| [`version`](#flightdeck-version) | Print flightdeck's version. | — | — |

## `flightdeck ingest`

Pull hangar runs and experiments into the data plane. Guide: [Data plane: ingest](data-plane.md#ingest).

### `flightdeck ingest export`

Ingest the files `hangar experiment export -o DIR` wrote.

```
flightdeck ingest export [OPTIONS] DIRECTORY
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `DIRECTORY` | path | required |  |  |
| `--out` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` | Data plane directory. |

### `flightdeck ingest experiment`

Fetch an experiment over REST (raw files kept under &lt;out&gt;/raw/&lt;id&gt;/) and ingest it.

```
flightdeck ingest experiment [OPTIONS] EXP_ID
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `EXP_ID` | text | required |  |  |
| `--hangar` | text |  | `HANGAR_URL` | hangar base URL; token from HANGAR_TOKEN. |
| `--out` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` | Data plane directory. |

### `flightdeck ingest job`

Ingest a job's trace and its turns' manifests over REST.

```
flightdeck ingest job [OPTIONS] JOB_ID
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `JOB_ID` | text | required |  |  |
| `--hangar` | text |  | `HANGAR_URL` | hangar base URL; token from HANGAR_TOKEN. |
| `--out` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` | Data plane directory. |

### `flightdeck ingest session`

Ingest a session's trace (or one turn's) and the turns' manifests over REST.

```
flightdeck ingest session [OPTIONS] NAME
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `NAME` | text | required |  |  |
| `--turn` | integer |  |  | Only this turn. |
| `--hangar` | text |  | `HANGAR_URL` | hangar base URL; token from HANGAR_TOKEN. |
| `--out` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` | Data plane directory. |

### `flightdeck ingest github`

Fill the `prs` table from GitHub REST (token from GITHUB_TOKEN).

```
flightdeck ingest github [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--repos` | text | required | `FLIGHTDECK_GITHUB_REPOS` | Comma-separated owner/repo. |
| `--days` | integer | `30` |  | Rewrite the PRs closed in the last N days (revert detection looks back 14). |
| `--out` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |

## `flightdeck stats`

Compare the arms of an experiment, paired by task. Guide: [Statistics](statistics.md#flightdeck-stats-compare).

### `flightdeck stats compare`

Compare the candidate arm against the baseline on one metric, paired by task, with exclusions printed.

```
flightdeck stats compare [OPTIONS] EXPERIMENT
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `EXPERIMENT` | text | required |  |  |
| `--baseline`, `--a` | text | `control` |  | The arm that runs today; the verdict is against it. |
| `--candidate`, `--b` | text | `candidate` |  | The arm with the change under judgement. |
| `--metric` | text | `resolved` |  | resolved&#124;cost_usd&#124;tool_calls&#124;wall_s |
| `--seed` | integer | `0` |  |  |
| `--include-drift` | flag | off |  |  |
| `--data` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` | Data plane: directory or gs:// |
| `--md` | flag | off |  | Print markdown (for an issue or a file) instead of the terminal readout. |

## `flightdeck report`

The verdict as a report, posted on the pull request. Guide: [Reports](reports.md).

### `flightdeck report experiment`

Render an experiment's report from the data plane: print it as a readout, write it (markdown), post it.

```
flightdeck report experiment [OPTIONS] EXPERIMENT
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `EXPERIMENT` | text | required |  |  |
| `--baseline`, `--a` | text | `control` |  | The arm that runs today; the verdict is against it. |
| `--candidate`, `--b` | text | `candidate` |  | The arm with the change under judgement. |
| `--decision` | path |  |  | Pre-registered decision.yaml; the verdict needs it. |
| `--details` / `--no-details` | flag | off |  | Per-task rows and trial links (keep off for public repos). |
| `--hangar` | text |  | `HANGAR_URL` | hangar base URL for trial links. |
| `--out` | path |  |  | Also write the report here. |
| `--post` | text |  |  | owner/repo#n: post as a PR or issue comment (token: GITHUB_TOKEN). |
| `--seed` | integer | `0` |  |  |
| `--data` | text | `~/.flightdeck/data` | `FLIGHTDECK_DATA_URI` |  |
| `--full-url` | text |  |  | Where the full report is (https), linked when a comment is clipped. |
| `--gist` | flag | off |  | Link a clipped comment to a secret gist of the full report. |

### `flightdeck report post`

Post (or update in place) a rendered report as a PR or issue comment.

```
flightdeck report post [OPTIONS] REPORT
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `REPORT` | path | required |  |  |
| `--to` | text | required |  | owner/repo#n |
| `--full-url` | text |  |  | Where the full report is (https), linked when a comment is clipped. |
| `--gist` | flag | off |  | Link a clipped comment to a secret gist of the full report. |

## `flightdeck experiment`

Trials on hangar: submit a suite, follow it, collect it. Guide: [Running experiments](runners.md).

### `flightdeck experiment run`

Gate a suite's plan on model pins and projected cost, then submit it (or print it with --dry-run).

```
flightdeck experiment run [OPTIONS] SUITE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  | Suite file (YAML). |
| `--dry-run` | flag | off |  | Print the spec and the projection; submit nothing. |
| `--max-usd` | number |  |  | Refuse a plan projected above this. |
| `--assume` | number | `3.0` |  | $ per trial for a task without cost history. |
| `--budgets` | path |  | `FLIGHTDECK_BUDGETS` | Caps. |
| `--author` | text |  | `FLIGHTDECK_AUTHOR` | Whose sub-cap the plan spends. |
| `--allow-model` | text, repeatable |  |  | Accept this id as concrete. |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane: cost history, collect target. |
| `--backend` | text | `hangar` |  | hangar, or local: Docker on this machine (fixtures, CI). |
| `--cache` | flag | off |  | Reuse matching trials from --data; submit only the rest. |

### `flightdeck experiment status`

A run set's state, trial counts, and pins that break pairing (exit 1 when there are any).

```
flightdeck experiment status [OPTIONS] RUN_SET
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUN_SET` | text | required |  |  |
| `--json` | flag | off |  |  |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane: cost history, collect target. |

### `flightdeck experiment collect`

Write a run set's trials and grades into the data plane.

```
flightdeck experiment collect [OPTIONS] RUN_SET
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUN_SET` | text | required |  |  |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane: cost history, collect target. |

## `flightdeck task`

Harbor-compatible task directories: write, check, digest. Guide: [Tasks](tasks.md).

### `flightdeck task new`

Write a new task from the template: safe test.sh, hidden tests, Harbor task.toml.

```
flightdeck task new [OPTIONS] PATH
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PATH` | path | required |  |  |
| `--id` | text |  |  | Task id (default: the directory's name). |

### `flightdeck task check`

Validate task directories: layout, symlinks, files_digest, hangar's limits.

```
flightdeck task check PATHS...
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PATHS` | path, one or more | required |  |  |

### `flightdeck task digest`

Print the task digest and the tests' digest (files_digest).

```
flightdeck task digest [OPTIONS] PATH
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PATH` | path | required |  |  |
| `--write` | flag | off |  | Update files_digest in task.toml. |

### `flightdeck task import-aidlc`

Convert an ai-dlc evaluation suite (JSON) into task dirs, specs and a suite file; print the assertion mapping.

```
flightdeck task import-aidlc [OPTIONS] SUITE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  |  |
| `--out` | path | required |  | An empty directory to write into. |

## `flightdeck cache`

The trial-result cache: drop entries, check the drift sentinel. Guide: [Running experiments: cache](runners.md#cache).

### `flightdeck cache drop`

Stop reusing trials of these tasks or identities finished before now.

```
flightdeck cache drop [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root (local). |
| `--task` | text, repeatable |  |  | A task id. |
| `--identity` | text, repeatable |  |  | An identity (harness+environment digest). |

### `flightdeck cache sentinel`

Check the nightly sentinel (`experiment run <suite>` without --cache) for a step change; exit 1 on alerts.

```
flightdeck cache sentinel [OPTIONS] SUITE VARIANT
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  |  |
| `VARIANT` | text | required |  |  |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root (local). |
| `--window` | integer | `14` |  |  |
| `--alerts-repo` | text |  |  | owner/repo for an issue (gh). |

## `flightdeck spec`

Behavior specs over traces: lint them, test them on an export. Guide: [Behavior specs](behavior-specs.md).

### `flightdeck spec lint`

Load specs and print warnings; exit 1 when one does not load.

```
flightdeck spec lint PATHS...
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PATHS` | path, one or more | required |  |  |

### `flightdeck spec test`

Evaluate specs on one export: `spec<TAB>unit<TAB>result` lines; exit 1 on any fail or unknown.

```
flightdeck spec test [OPTIONS] SPEC
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SPEC` | path | required |  |  |
| `--trace` | path | required |  | A hangar.trace/v1 OTLP/JSON export. |
| `--engine` | text | `python` |  | python (the reference evaluator) or sql (the nightly one). |

## `flightdeck check`

Run the behavior specs and ADR checks over the data plane; label edits to them. Guide: [Behavior specs: nightly runner](behavior-specs.md#adr-checks-and-the-nightly-runner).

### `flightdeck check run`

Evaluate every spec and accepted ADR check over one day, write spec_results, and flag violation jumps.

```
flightdeck check run [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root: a directory or gs:// URI. |
| `--date` | text |  |  | The dt partition to judge (default: yesterday, UTC). |
| `--specs` | path, repeatable |  |  | Spec files, or directories of \*.yaml. |
| `--adrs` | text, repeatable |  |  | &lt;git checkout&gt;:&lt;dir&gt; of ADRs (HEAD), or a dir. |
| `--out` | text |  |  | Local plane root to write spec_results to (default: --data). |
| `--window` | integer | `14` |  | Days of spec_results history for change-point alerts. |
| `--alerts-repo` | text |  |  | owner/repo to open flightdeck:violation issues in (via gh). |

### `flightdeck check diff`

Label an edit to checks (spec files or ADRs): tightened, loosened or removed. A missing file has no checks.

```
flightdeck check diff OLD NEW
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `OLD` | path | required |  |  |
| `NEW` | path | required |  |  |

## `flightdeck mutate`

Mutation scoring: mutate the harness, check the suite catches each mutant. Guide: [Behavior specs: mutation scoring](behavior-specs.md#mutation-scoring).

### `flightdeck mutate plan`

Write a suite with the base variant and its mutants, n trials each. Equivalent mutants (the no-op control; skills no trace in --data used) are listed but not run.

```
flightdeck mutate plan [OPTIONS] SUITE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  |  |
| `--harness` | text | required |  | The base variant in the suite. |
| `--out` | path | required |  | The mutants' suite file to write. |
| `--ops` | text | `drop-skill,drop-instruction-line,approvals,noop` |  |  |
| `--max` | integer | `12` |  |  |
| `--n` | integer | `2` |  |  |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane root. |

### `flightdeck mutate run`

Submit the mutants through `experiment run`'s cost gate (projection first; refused above --max-usd).

```
flightdeck mutate run [OPTIONS] PLAN_FILE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PLAN_FILE` | path | required |  |  |
| `--max-usd` | number | `40.0` |  |  |
| `--dry-run` / `--no-dry-run` | flag | off |  |  |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane root. |

### `flightdeck mutate score`

Kill rate with its interval, every mutant's verdict, and the survivors with a spec to add (markdown).

```
flightdeck mutate score [OPTIONS] PLAN_FILE RUN_SET
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `PLAN_FILE` | path | required |  |  |
| `RUN_SET` | text | required |  |  |
| `--specs` | path, repeatable | required |  | Spec files. |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane root. |
| `--bound` | number | `0.9` |  |  |
| `--out` | path |  |  |  |

## `flightdeck holdout`

Sealed holdouts: briefs, seal, canary scan, score once. Guide: [Holdouts](holdouts.md).

### `flightdeck holdout brief`

Write one brief per blind writer to briefs/&lt;set&gt;_writer_&lt;x&gt;.txt.

```
flightdeck holdout brief [OPTIONS] NAME
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `NAME` | text | required |  |  |
| `--writers` | integer | `2` |  |  |
| `--family` | text | `regression` |  |  |
| `--count` | integer | `20` |  |  |
| `--mined-after` | text |  |  |  |
| `--holdouts` | path | `holdouts` |  | The holdouts directory of the private data repo. |

### `flightdeck holdout seal`

Seal the writers' incoming tasks as one set and record it in the manifest (commit manifest.json alone).

```
flightdeck holdout seal [OPTIONS] NAME
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `NAME` | text | required |  |  |
| `--writer` | text, repeatable | required |  | &lt;id&gt;=&lt;harness or person&gt;, once per writer |
| `--fresh-after` | text | required |  | YYYY-MM-DD: the later of snapshot and model cutoff |
| `--holdouts` | path | `holdouts` |  | The holdouts directory of the private data repo. |

### `flightdeck holdout score`

Score a sealed set once: results/&lt;set&gt;.json and the manifest are committed together.

```
flightdeck holdout score [OPTIONS] NAME
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `NAME` | text | required |  |  |
| `--run-set` | text | required |  | The run set that ran the set's tasks. |
| `--against` | text | required |  | The candidate's harness_digest (or config_digest). |
| `--approve` | text | required |  | GitHub login of the approver. |
| `--author` | text | required |  | GitHub login of the candidate change's author. |
| `--by` | text | required | `FLIGHTDECK_AUTHOR` | Who runs the scoring. |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |
| `--min-hangar` | text | `0` |  |  |
| `--holdouts` | path | `holdouts` |  | The holdouts directory of the private data repo. |

### `flightdeck holdout canary-scan`

Find canaries in traces (tool input/output, messages, attributes) and logs; a hit voids its set.

```
flightdeck holdout canary-scan [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |
| `--since` | integer | `7` |  | Days back to scan. |
| `--logs` | path, repeatable |  |  | Retrieval or tool logs to scan too. |
| `--alerts-repo` | text |  |  | owner/repo to open an issue in (gh). |
| `--holdouts` | path | `holdouts` |  | The holdouts directory of the private data repo. |

## `flightdeck knowledge`

The knowledge gold set: seal it, score arms on correctness and citations. Guide: [Knowledge evals](knowledge-evals.md).

### `flightdeck knowledge seal`

Check the suite, plant canaries in the answer keys and write manifest.json (commit it on its own).

```
flightdeck knowledge seal [OPTIONS] SUITE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  |  |
| `--holdouts` | path |  |  | Register canaries here. |

### `flightdeck knowledge score`

Score each arm; with --baseline and --candidate, the paired difference and the 15-point rule.

```
flightdeck knowledge score [OPTIONS] SUITE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SUITE` | path | required |  |  |
| `--arm` | text, repeatable | required |  | An arm with answers/&lt;arm&gt;.jsonl. |
| `--baseline` | text |  |  |  |
| `--candidate` | text |  |  |  |
| `--seed` | integer | `0` |  |  |

## `flightdeck judge`

Rubric judges: label sheets, calibration, judge labels, corrected estimates. Guide: [Judges](judges.md).

### `flightdeck judge label`

A labelling sheet (CSV on stdout): a stratified sample of runs, the first `overlap` items for every rater and the rest shared out; variant names stay off the sheet (blind).

```
flightdeck judge label [OPTIONS] RUBRIC
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUBRIC` | path | required |  |  |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |
| `--sample` | integer | `150` |  |  |
| `--stratify-by` | text | `variant` |  |  |
| `--raters` | integer | `2` |  |  |
| `--overlap` | integer | `30` |  |  |
| `--seed` | integer | `0` |  |  |

### `flightdeck judge calibrate`

Kappa with its interval, the calibration curve and the status; writes &lt;rubric&gt;.calibration.json.

```
flightdeck judge calibrate [OPTIONS] RUBRIC HUMAN JUDGE
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUBRIC` | path | required |  |  |
| `HUMAN` | path | required |  |  |
| `JUDGE` | path | required |  |  |
| `--seed` | integer | `0` |  |  |

### `flightdeck judge score`

Store a judge's labels (`run_id, label, rationale`) as judge_labels: rationale text stays out, its digest in.

```
flightdeck judge score [OPTIONS] RUBRIC LABELS
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUBRIC` | path | required |  |  |
| `LABELS` | path | required |  |  |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |

### `flightdeck judge estimate`

The PPI estimate of the rubric's mean over the judge-labelled runs, from the human labels and the judge's.

```
flightdeck judge estimate [OPTIONS] RUBRIC HUMAN
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `RUBRIC` | path | required |  |  |
| `HUMAN` | path | required |  |  |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |

## `flightdeck metrics`

Weekly team metrics over the data plane. Guide: [Weekly metrics](metrics.md).

### `flightdeck metrics weekly`

The weekly scorecard; team-wide runs with --reports also write &lt;week&gt;.json, &lt;week&gt;.md and latest.json.

```
flightdeck metrics weekly [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--week` | text |  |  | ISO week, e.g. 2026-W45 (default: last complete week). |
| `--format` | text | `md` |  | md, json or slack (Block Kit JSON). |
| `--person` | text |  |  | Only this person's jobs (share with that person and admins only). |
| `--repo` | text |  |  | Only this repository (owner/repo). |
| `--data` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |
| `--reports` | text |  | `FLIGHTDECK_REPORTS_URI` | Write reports/weekly/ here (private). |

## `flightdeck compact`

Compact hangar's outbox into the data plane (nightly on Cloud Run: deploy/compactor/). Guide: [Data plane: compactor](data-plane.md#compactor).

```
flightdeck compact [OPTIONS]
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `--date` | text |  |  | UTC outbox date, YYYY-MM-DD (default: today). |
| `--lookback` | integer | `3` |  | Also recompact this many days before --date whose inputs changed. |
| `--rebuild` / `--no-rebuild` | flag | off |  | Rewrite the dates even if their inputs are unchanged. |
| `--input` | text | required | `FLIGHTDECK_RUNS_URI` | Outbox root: gs://, file:// or path. |
| `--out` | text | required | `FLIGHTDECK_DATA_URI` | Data plane root. |

## `flightdeck query`

Run SQL over the data plane's tables (runs, spans, events, manifests, grades, test_cases); tab-separated. Guide: [Data plane: querying](data-plane.md#querying).

```
flightdeck query [OPTIONS] SQL
```

| Argument or option | Type | Default | Environment | Description |
| --- | --- | --- | --- | --- |
| `SQL` | text | required |  |  |
| `--data` | text |  | `FLIGHTDECK_DATA_URI` | Data plane root: a directory or gs:// URI. |

## `flightdeck version`

Print flightdeck's version.

```
flightdeck version
```

## Environment

Besides the options' environment variables above, flightdeck reads these directly:

| Variable | Used for |
| --- | --- |
| `HANGAR_TOKEN` | Bearer token for hangar REST: `ingest experiment|job|session`, `experiment run|status|collect`. |
| `GITHUB_TOKEN` | `report post` and `report experiment --post` (`issues:write` / `pull_requests:write`; `gist` for `--gist`), and `ingest github` (read-only). |
| `GITHUB_API_URL` | GitHub API root for posting reports (default `https://api.github.com`). |
| `FLIGHTDECK_AUTHOR` | Also read by `mutate run`, whose cost gate charges that author's sub-cap. |
| `ANTHROPIC_API_KEY` | Local backend only, for a real-model `claude-code@<version>` trial (an API key, never a subscription login); never used in CI. |
