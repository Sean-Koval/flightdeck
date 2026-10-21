# The trial cache

Tokens cost far more than compute: about $2 to $3 a trial against well under a cent. So a trial whose inputs haven't
changed is reused rather than re-run. `experiment run <suite> --cache --data <dir>` looks each planned
`(task, variant)` up in the data plane and submits only what is missing. Code: `src/flightdeck/runners/cache.py`.

## The key

The key is `task_digest`, `variant_digest`, the model id and the task's `base_sha`, all stamped on the runs when
flightdeck collects them. `task_digest` covers the task's tests and grader command, so it stands in for
`grader_digest`; `variant_digest` is the variant's overlay and environment as planned.

On top, the identity hangar recorded must equal the latest one that variant recorded. That identity is
`harness_digest + environment_digest`, else `config_digest` plus the manifest's `environment.build.id`
(`config_digest` alone misses a repository rebuild).

So a changed skill is a new `variant_digest`, and only that variant runs again. A provider or environment change
shows up as a new identity on the next trial, and older trials stop matching.

## What counts

Completed trials only: never `infra_error`, cancelled, human, tainted, contaminated, drifted or `task_invalid` ones.
A pair is a hit only with at least `n` such trials, and the `n` most recent are reused.

## Invalidation

A 30-day TTL; a model change, since it is in the key; and `flightdeck cache drop --task <id>` or
`--identity <digest>`. A drop ignores trials finished before it, and is kept in `<data>/cache-drops.json`.

## In reports

The run set's reused trials go to `trial_reuse`. `stats compare <run-set>` and the report read them with the new
trials, each `run_id` once, and say how many were reused and how old they are. When everything hits, nothing is
submitted and the run set is `reuse-<suite>-<time>`.

Cache reads spend nobody's budget. Trials without an identity (older hangar records) never hit.

## Drift sentinel

A silent provider-side change keeps every key the same. So a nightly suite of about 5 fixed tasks × 2 trials runs on
the `stable` harness *without* `--cache`. It costs about $20 a night, on the team budget line. Then:

```sh
flightdeck cache sentinel sentinel.yaml stable --data <dir> [--alerts-repo owner/repo]
```

compares the latest night with its trailing 14 days. Drift is a resolved rate whose Wilson interval misses the
window's. It is also a median cost or wall time outside 0.67 to 1.5 times the window's. Either prints an alert, opens
an issue and exits 1.

!!! note "Status"
    Code merged ([#55](https://github.com/Sean-Koval/flightdeck/pull/55)). Issue
    [#24](https://github.com/Sean-Koval/flightdeck/issues/24) stays open until the drift sentinel is scheduled nightly
    in the private data repository.
