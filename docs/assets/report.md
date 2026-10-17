<!-- flightdeck:report:job-expdemo -->
## flightdeck report: `job-expdemo` (treat vs control)

**Verdict**: treat is better than control on resolved (+21.2 pp, CI +1.5…+43.9, margin -5.0).

### Pins

| | control | treat |
| --- | --- | --- |
| harness | claude-code 2.3.1 | claude-code 2.3.1 |
| model | claude-sonnet-5-1 | claude-sonnet-5-1 |
| environment | plain | plain |
| config_digest | `sha256:222222222222…` | `sha256:222222222222…`, `sha256:555555555555…` |
| harness_digest | - | - |
| environment_digest | - | - |
| grader | bash tests/test.sh | bash tests/test.sh |
| hangar version | 0.1.0 | 0.1.0 |

Base SHAs: 12 across 12 tasks (per task below).

### Outcome

**resolved**: treat vs control, experiment `job-expdemo`, seed 0

| variant | trials | resolved (95% Wilson) | $ / resolved (95%) |
| --- | --- | --- | --- |
| control | 32 | 10/32 = 31.2% [18.0%, 48.6%] | 1.333 [0.801, 2.795] |
| treat | 31 | 16/31 = 51.6% [34.8%, 68.0%] | 0.639 [0.448, 1.071] |

Paired difference treat - control: **+21.2 pp**, 95% CI +1.5 pp to +43.9 pp (task bootstrap; 11 tasks, 63 trials; 3 concordant, 8 discordant tasks).
At 11 paired tasks x 3 trials the minimum detectable lift at 80% power is about 35% (r1 simulation).
Resolved: grader for 63 trials (grader = exit 0 and applied; verify = hangar's after-turn verify when no grader ran).
Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6.
Saturated (same outcome in every trial of both arms, no information): t01, t02.

### Process

**tool_calls**: treat vs control, experiment `job-expdemo`, seed 0

| variant | trials | mean | $ / resolved (95%) |
| --- | --- | --- | --- |
| control | 31 | 3.000 | - |
| treat | 31 | 2.323 | - |

Paired difference treat - control: **-0.682**, 95% CI -0.758 to -0.621 (task bootstrap; 11 tasks, 62 trials).
Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6, truncated trace 1.

**wall_s**: treat vs control, experiment `job-expdemo`, seed 0

| variant | trials | mean | $ / resolved (95%) |
| --- | --- | --- | --- |
| control | 31 | 174.935 | - |
| treat | 31 | 182.613 | - |

Paired difference treat - control: **+2.939**, 95% CI -40.818 to +44.697 (task bootstrap; 11 tasks, 62 trials).
Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6, truncated trace 1.

### Cost

**cost_usd**: treat vs control, experiment `job-expdemo`, seed 0

| variant | trials | mean | $ / resolved (95%) |
| --- | --- | --- | --- |
| control | 31 | 0.420 | 1.302 [0.781, 2.773] |
| treat | 31 | 0.330 | 0.639 [0.448, 1.071] |

Paired difference treat - control: **-0.092**, 95% CI -0.109 to -0.074 (task bootstrap; 11 tasks, 62 trials).
Excluded: cancelled 1, drift 1, infra_error 1, not finished 1, task_invalid 6, truncated trace 1.

### Behavior specs

| spec | control pass | treat pass |
| --- | --- | --- |
| never-delete-outside-repo | 31/31 = 100% | 31/31 = 100% |
| never-push-main | 31/31 = 100% | 31/31 = 100% |

### Exclusions and drift

1 drifted trial(s) excluded from paired analysis (`--include-drift` keeps them).
