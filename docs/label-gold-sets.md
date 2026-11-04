# Label gold sets

How often are the [step labels](process-metrics.md#step-labels) right? A gold set answers it. It is a file of tool
calls that a person labelled by hand. `flightdeck metrics labels` scores the labeller against it.

```sh
flightdeck metrics labels --gold gold.jsonl --data /tmp/plane --min-accuracy 0.85
```

It prints the first-label accuracy, then precision and recall for each label, then every call it got wrong. It exits 1
when accuracy is under `--min-accuracy`, so a nightly job can fail on a regression.

## The file

One JSON object per line, one line per tool call:

```json
{"run_id": "run-1", "seq": 7, "label": "test", "labels": ["test", "edit"]}
```

| Field | What |
| --- | --- |
| `run_id`, `seq` | The call, as `step_labels` keys it (`seq` is `hangar.seq`) |
| `label` | The call's main label: the first of its labels in the [taxonomy's order](process-metrics.md#step-labels) |
| `labels` | Optional: every label the call should carry. Without it, `[label]` |

Accuracy compares `label`. Precision and recall compare the label sets, so a call that writes and tests counts for
both `edit` and `test`. A gold call missing from the data plane is counted apart, never as a miss.

## Writing one

Label from the call's whole input and its output, not from the trace's clipped preview. Note the reason for a hard
call. Two people labelling the same calls tell you how sharp the taxonomy is before you trust any score.

Real gold sets are team data: they live in the private data repo, beside the plane they score
([ADR-0002](decisions/0002-public-code-private-data.md)). The repo has a synthetic set,
`tests/fixtures/labels/gold_calls.jsonl`. Its author also wrote the rules, so it shows known limits, not real accuracy.
CI fails when the rules score lower on it than before.
