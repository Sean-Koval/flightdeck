# Process metrics

How did an agent run get to its result? Two trials can both pass every hidden test and still differ in how they
worked. These metrics count what each run did, from its trace alone.

They are DuckDB views over the [data plane](data-plane.md), defined in one file:
[`src/flightdeck/metrics/process.sql`](https://github.com/Sean-Koval/flightdeck/blob/main/src/flightdeck/metrics/process.sql).
Every connection to the data plane has them, so `flightdeck query` reads them directly:

```sh
flightdeck query "from process_metrics where experiment_id = 'exp-1'" --data /tmp/plane
flightdeck query "select idx, label, tool_input from step_labels where run_id = 'run-1' order by idx"
```

## Step labels

`step_labels` gives every tool call its labels. `labels` lists every rule a call matches, in this order; `label` is the
first. A call that writes files, runs the tests and runs the program has all three.

| Label | When |
| --- | --- |
| `reference` | A `web` tool, or an input that reads a third-party implementation (`node_modules`, `/opt/hangar/harness`, `require(`) |
| `vcs` | `shell_ops` has `git.commit`, `git.push` or `pr.open`, or a shell runs `git init`, `add`, `status`, `log`, `diff` or `show` |
| `test` | `shell_ops` has `test`, or a shell runs a test runner or a test or CI script (`bash scripts/ci/verify.sh`). A probe (`--version`, `--help`, `--collect-only`, nothing else run) is not a test run |
| `edit` | An `edit` tool, or a shell write: `cat >`, `tee`, `sed -i`, `perl -pi`, `git apply`, python that writes or rewrites a file, a redirect into a source file |
| `setup` | A shell installing or syncing dependencies (`pip install`, `uv sync`, `npm ci`, `apt-get install`) |
| `plan` | A `plan` tool |
| `pr` | Opening, updating, merging or reading a pull request: an MCP tool such as `create_pull_request`, or `gh pr create`, `view` or `merge`, or `gh api` on `pulls/N` |
| `ci_wait` | Waiting on CI: an MCP tool such as `actions_list` or `subscribe_pr_activity`, or `gh pr checks`, `gh run watch` or `gh api` on `actions/runs` or `check-runs`. A `sleep` alone is not one |
| `review` | Reading or answering a review: an MCP tool such as `pull_request_review_write`, or `gh pr review` or `gh api` on `pulls/N/comments` |
| `tracker` | A Jira or GitHub issue: an MCP tool with `jira` in its name or Atlassian input, an `issue_*` tool, `gh issue` or `jira` |
| `explore` | A `read` or `search` tool, or a shell `ls`, `cat`, `find`, `grep`, `rg`, `head`, `tail`, `wc`, `tree` or `sed -n`. Also a look around: `which`, `--version`, `pip list`, `python -c "import x; print(x.__file__)"` |
| `verify` | A shell running `python`, `python3` or `node` (not inside quotes, not `-m pytest`, not a look around) |
| `other` | Anything else |

The rules key on `hangar.tool.kind` and `hangar.shell.ops` ([hangar's taxonomy](https://sean-koval.github.io/hangar/api/traces/#normalized-tool-kinds)).
They read the command text where those don't say enough. A runner counts at a command position: a line or segment start,
a loop's `do`, or behind wrappers like `uv run --project x`.

The SDLC labels read an MCP tool by the last part of its name, so any server prefix works. `pull_request_read`
goes by its `method`: `get_check_runs` is `ci_wait`, `get_reviews` is `review`, `get_diff` is `pr`. Calls that only
coordinate agents stay `other`.

hangar clips long inputs, so labels read from text are a lower bound. [Label gold sets](label-gold-sets.md) measure
how often they are right. `idx` is the call's position in its run, from
zero. `answer_key_risk` marks a read of a reference implementation.

## The metrics

`process_metrics` has one row per agent run that is not truncated and has no conflicting rows:

| Column | What it counts |
| --- | --- |
| `tool_calls`, `tool_errors` | Tool calls, and those with `tool_ok` false |
| `tool_calls_before_first_edit` | The `idx` of the first call with `edit`: calls spent before writing anything |
| `edit_calls`, `by_label` | Calls with `edit` in `labels`, and calls per first `label` |
| `test_runs`, `failing_test_runs` | Calls with `test` in `labels`. One fails when its call failed or its output shows `FAILED`, `Error` or `Traceback` |
| `fix_loops` | A failing test run, then an edit, then the next passing test run with `tool_ok` true (the edit may share its call) |
| `reference_lookups`, `answer_key_reads` | `reference` calls, and reads of an implementation on disk |
| `pr_steps`, `ci_wait_steps`, `review_steps`, `tracker_steps` | Calls with that SDLC label in `labels` |
| `trusted_test_runs`, `failing_trusted_test_runs` | hangar's own counted checks (trusted, complete, more than zero tests) |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd`, `wall_s` | From the run itself |

The agent's test runs are its word; trusted runs are hangar's. The two are reported apart on purpose.
None of these counts establishes causal credit.

Exact duplicate rows count once. Two different spans with one identity, or two different run rows, leave that run out.
Raw tables keep both copies. Missing spans, clipping and forged evidence go undetected; see [integrity limits](research/process-integrity.md).

## Moved from this page

| Section | Now at |
| --- | --- |
| <a id="where-they-came-from"></a>Where they came from | [Where the process metrics came from](process-metrics-origins.md) |
| <a id="differences-from-hangars-kit"></a>Differences from hangar's kit | [Differences](process-metrics-origins.md#differences-from-hangars-kit) |

## Next

- [Label gold sets](label-gold-sets.md): how often labels are right.
- [Tasks](task-fixtures.md#the-semver-smoke-task): the semver task.
