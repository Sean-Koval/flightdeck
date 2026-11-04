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
| `vcs` | `shell_ops` has `git.commit`, `git.push` or `pr.open`, or a shell runs `git add`, `status`, `log`, `diff` or `show` |
| `test` | `shell_ops` has `test`, or a shell runs a test runner or a test or CI script (`bash scripts/ci/verify.sh`). A probe (`--version`, `--help`, `--collect-only`, nothing else run) is not a test run |
| `edit` | An `edit` tool, or a shell write: `cat >`, `tee`, `sed -i`, `perl -pi`, `git apply`, python that writes or rewrites a file, a redirect into a source file |
| `setup` | A shell installing or syncing dependencies (`pip install`, `uv sync`, `npm ci`, `apt-get install`) |
| `plan` | A `plan` tool |
| `explore` | A `read` or `search` tool, or a shell `ls`, `cat`, `find`, `grep`, `rg`, `head`, `tail`, `wc`, `tree` or `sed -n` |
| `verify` | A shell running `python`, `python3` or `node` (not inside quotes, not `-m pytest`) |
| `other` | Anything else |

The rules key on `hangar.tool.kind` and `hangar.shell.ops` ([hangar's taxonomy](https://sean-koval.github.io/hangar/api/traces/#normalized-tool-kinds)).
They read the command text where those don't say enough. A runner counts at a command position: a line or segment start,
a loop's `do`, or behind wrappers like `uv run --project x`.

hangar clips long inputs, so labels read from text are a lower bound. [Label gold sets](label-gold-sets.md) measure
how often they are right. `idx` is the call's position in its run, from
zero. `answer_key_risk` marks a read of a reference implementation.

## The metrics

`process_metrics` has one row per agent run that is not truncated:

| Column | What it counts |
| --- | --- |
| `tool_calls`, `tool_errors` | Tool calls, and those with `tool_ok` false |
| `tool_calls_before_first_edit` | The `idx` of the first call with `edit`: calls spent before writing anything |
| `edit_calls`, `by_label` | Calls with `edit` in `labels`, and calls per first `label` |
| `test_runs`, `failing_test_runs` | Calls with `test` in `labels`. One fails when its call failed or its output shows `FAILED`, `Error` or `Traceback` |
| `fix_loops` | A failing test run, then an edit, then the next passing test run (the edit may share its call) |
| `reference_lookups`, `answer_key_reads` | `reference` calls, and reads of an implementation on disk |
| `trusted_test_runs`, `failing_trusted_test_runs` | hangar's own counted checks (trusted, complete, more than zero tests) |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd`, `wall_s` | From the run itself |

The agent's test runs are its word; trusted runs are hangar's. The two are reported apart on purpose.

## Where they came from

They are ported from hangar's `evals/semver` kit, built for its 2026-10-12 harness comparison. That kit parsed pi and
Antigravity logs into its own spans. hangar's trace export now does that job for every harness, so the parser was
dropped. `tests/test_process_metrics.py` checks the views against the kit's `metrics.py` and `classify.rule()` on
one trial.

### Differences from hangar's kit

- **No LLM call count.** Traces record a run's tokens and cost, not each model call.
- **Test runs need a runner at a command position.** The kit matched `pytest` or `unittest` anywhere. So
  `pip install pytest` was a test run, and so was an edit whose path named pytest.
- **Setup has a label, and a call has every label it earns.** The kit gave one label and called installs `other`.
- **Plan tools have a label.** The kit called them `other`.
- **No model labeller.** The kit could also ask a model (Microsoft Decision-1, through OpenRouter) for each label.
  flightdeck holds no model credentials ([ADR-0001](decisions/0001-boundary-with-hangar.md)). Model labels wait
  for a calibrated [judge](judges.md).
- **Wall time** is the run's start to its end, not its first span to its last.

The semver task itself lives in `tasks/smoke/semver/` ([Tasks](tasks.md#the-semver-smoke-task)).
