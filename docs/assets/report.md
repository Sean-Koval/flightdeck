<!-- flightdeck:report:job-expdemo -->
## treat is better than control on resolved: +21.2 pp (95% CI +1.5 to +43.9, margin −5.0)

`job-expdemo`: treat against control, 12 tasks, 73 trials, seed 0. The arms differ in config_digest (pins at the end).

Rule, pre-registered in `decision.yaml`: resolved, higher is better, margin −5.0 pp, at least 10 paired tasks.

### Outcome

| variant | trials | resolved | 95% Wilson | $ per resolved (95%) |
| --- | --- | --- | --- | --- |
| control | 32 | 10 of 32 (31%) | 18% to 49% | $1.33 ($0.80 to $2.79) |
| treat | 31 | 16 of 31 (52%) | 35% to 68% | $0.64 ($0.45 to $1.07) |

Paired difference treat − control: **+21.2 pp** (95% CI +1.5 pp to +43.9 pp; task bootstrap, 11 tasks, 63 trials; 3 concordant, 8 discordant tasks).

At 11 paired tasks × 3 trials the minimum detectable lift at 80% power is about 35 pp (simulated).

Resolved: grader for 63 trials (grader = exit 0 and applied; verify = hangar's after-turn verify when no grader ran).

Saturated (same outcome in every trial of both arms, no information): t01, t02.

### Process

Tool calls

| variant | trials | mean |
| --- | --- | --- |
| control | 31 | 3.0 calls |
| treat | 31 | 2.3 calls |

Paired difference treat − control: **−0.7 calls** (95% CI −0.8 calls to −0.6 calls; task bootstrap, 11 tasks, 62 trials).

Wall time

| variant | trials | mean |
| --- | --- | --- |
| control | 31 | 174.9 s |
| treat | 31 | 182.6 s |

Paired difference treat − control: **+2.9 s** (95% CI −40.8 s to +44.7 s; task bootstrap, 11 tasks, 62 trials).

### Cost

| variant | trials | mean | $ per resolved (95%) |
| --- | --- | --- | --- |
| control | 31 | $0.42 | $1.30 ($0.78 to $2.77) |
| treat | 31 | $0.33 | $0.64 ($0.45 to $1.07) |

Paired difference treat − control: **−$0.09** (95% CI −$0.11 to −$0.07; task bootstrap, 11 tasks, 62 trials).

### Behavior specs

| spec | control pass | treat pass |
| --- | --- | --- |
| never-delete-outside-repo | 31 of 31 (100%) | 31 of 31 (100%) |
| never-push-main | 31 of 31 (100%) | 31 of 31 (100%) |

### Exclusions and drift

Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6; from the process and cost tables also truncated trace 1.

1 drifted trial excluded from paired analysis (`--include-drift` keeps it).

<details><summary>Pins</summary>

| | control | treat |
| --- | --- | --- |
| config_digest | `sha256:2222222222222222222222222222222222222222222222222222222222222222` | `sha256:2222222222222222222222222222222222222222222222222222222222222222`, `sha256:5555555555555555555555555555555555555555555555555555555555555555` |

Same in both arms: harness `claude-code 2.3.1`; model `claude-sonnet-5-1`; environment `plain`; harness_digest not recorded; environment_digest not recorded; grader `bash tests/test.sh`; hangar version `0.1.0`. Base SHAs: 12 across 12 tasks.

</details>
